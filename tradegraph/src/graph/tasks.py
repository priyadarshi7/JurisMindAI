"""Celery task wrapping the linear research pipeline (docs/06, D-16):
research jobs run in a worker process, never inline in an API request
handler. `apps/api/routers/jobs.py` enqueues; this module is what a
`celery ... --queues=research` worker actually executes.

Two-phase status commit, deliberately: a quick RUNNING commit happens
*before* the (potentially many-minutes-long — 494s in
tests/integration/test_research_pipeline_live.py) `run_research()` call, on
its own short-lived session. `run_research()` itself only flushes within its
own session/transaction and never commits, so without this first commit a
client polling `GET /jobs/{id}` would see PENDING right up until the whole
run finished — the RUNNING transition would never be observable.

❗ Deliberately does NOT use `src.core.db.get_engine()` /
`get_session_factory()` — those are `@lru_cache`d singletons correct for
the API process, which keeps one event loop alive for the process's whole
lifetime. This task runs under `--pool=solo` (the only pool that works on
Windows, and simple enough to be the honest default here): each invocation
calls `asyncio.run()`, which spins up and tears down a *new* event loop per
task. A cached engine's asyncpg connection pool is bound to the loop that
created it — reusing it from a second task's new loop crashed for real with
`AttributeError: 'NoneType' object has no attribute 'send'` (a dead
proactor from the first loop) the moment `pool_pre_ping` tried to use it,
found live by actually running two jobs back-to-back through a real worker,
not by inspection. So: a fresh engine, scoped to and disposed within this
one task's own event loop, every time.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import redis
from qdrant_client import QdrantClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.celery_app import app
from src.core.config import get_settings
from src.graph.pipeline import ProgressCallback, run_research
from src.graph.prompt_runner import PromptRunner
from src.models.orm import JobStatus, ResearchJob
from src.observability.metrics import WORKER_JOB_DURATION, WORKER_JOB_FAILURES, WORKER_QUEUE_DEPTH
from src.prompts.loader import PromptRepository
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.hybrid.retriever import HybridRetriever
from src.rag.reranking.reranker_client import RerankerClient
from src.rag.vector.qdrant_store import QdrantStore

RESEARCH_QUEUE_NAME = "research"  # must match celery_app.py's task_routes

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "prompts"

# Truncated rather than unbounded — a raw exception message (e.g. an HTML
# error page from a misbehaving proxy) has no business filling the database.
MAX_ERROR_MESSAGE_LENGTH = 2000


def enqueue_research_job(*, job_id: str, query: str, tenant_id: str | None, trace_id: str) -> None:
    run_research_task.delay(job_id=job_id, query=query, tenant_id=tenant_id, trace_id=trace_id)


def _record_queue_depth() -> None:
    """A gauge, not a counter — read fresh at the start of every task rather
    than polled on a timer, since a `--pool=solo` worker only ever has one
    natural "tick" to hang this off: a task starting. Best-effort: a metrics
    read must never be what fails a real research job.
    """
    settings = get_settings()
    if settings.celery_broker_url is None:
        return
    try:
        # redis-py's stub types llen()'s return as `Awaitable[int] | int` to
        # cover its async client too; this is the sync client, always a
        # plain int at runtime.
        depth = redis.Redis.from_url(str(settings.celery_broker_url)).llen(RESEARCH_QUEUE_NAME)
        WORKER_QUEUE_DEPTH.labels(queue=RESEARCH_QUEUE_NAME).set(depth)  # type: ignore[arg-type]
    except Exception:  # a metrics read is never allowed to fail a real job
        pass


@app.task(  # type: ignore[untyped-decorator]  # celery has no type stubs
    name="tradegraph.research.run"
)
def run_research_task(*, job_id: str, query: str, tenant_id: str | None, trace_id: str) -> None:
    _record_queue_depth()
    start = time.monotonic()
    try:
        asyncio.run(
            _run_research_job(job_id=job_id, query=query, tenant_id=tenant_id, trace_id=trace_id)
        )
    except Exception:
        WORKER_JOB_FAILURES.labels(queue=RESEARCH_QUEUE_NAME).inc()
        raise
    finally:
        WORKER_JOB_DURATION.labels(queue=RESEARCH_QUEUE_NAME).observe(time.monotonic() - start)


def _make_progress_callback(
    session_factory: async_sessionmaker[AsyncSession], job_id: str
) -> ProgressCallback:
    """Each call opens and commits its own short-lived session — same
    two-phase-commit reasoning as the RUNNING flip above: `run_research()`
    holds one long transaction on its own session for the whole run, so a
    write there wouldn't be visible to `GET /jobs/{id}` (a different
    process, different connection) until the very end. Progress is only
    useful if it's visible *during* the run.
    """

    async def on_progress(message: str) -> None:
        async with session_factory() as session:
            job = await session.get(ResearchJob, uuid.UUID(job_id))
            if job is not None:
                job.progress_detail = message
                await session.commit()

    return on_progress


def _make_engine_and_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is not set — see .env.example. The worker must not "
            "silently fall back to a default connection string."
        )
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


async def _run_research_job(
    *, job_id: str, query: str, tenant_id: str | None, trace_id: str
) -> None:
    engine, session_factory = _make_engine_and_session_factory()

    try:
        async with session_factory() as session:
            job = await session.get(ResearchJob, uuid.UUID(job_id))
            if job is not None:
                job.status = JobStatus.RUNNING
                job.progress_detail = "Starting research"
                await session.commit()

        settings = get_settings()
        qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        qdrant_store = QdrantStore(qdrant_client, collection_name=settings.qdrant_collection_name)
        embedder = OllamaEmbedder(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            expected_dimension=settings.ollama_embedding_dimension,
        )
        bm25_encoder = Bm25SparseEncoder()
        reranker = RerankerClient(base_url=settings.reranker_base_url)
        retriever = HybridRetriever(
            store=qdrant_store, embedder=embedder, sparse_encoder=bm25_encoder, reranker=reranker
        )
        prompt_repository = PromptRepository(PROMPTS_ROOT)

        try:
            async with session_factory() as session:
                with PromptRunner(
                    base_url=settings.ollama_base_url, prompt_repository=prompt_repository
                ) as prompt_runner:
                    await run_research(
                        query,
                        session=session,
                        retriever=retriever,
                        prompt_runner=prompt_runner,
                        model=settings.ollama_chat_model,
                        research_id=job_id,
                        trace_id=trace_id,
                        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                        on_progress=_make_progress_callback(session_factory, job_id),
                    )
                await session.commit()
        except Exception as exc:
            async with session_factory() as failure_session:
                failed_job = await failure_session.get(ResearchJob, uuid.UUID(job_id))
                if failed_job is not None:
                    failed_job.status = JobStatus.FAILED
                    failed_job.error_message = str(exc)[:MAX_ERROR_MESSAGE_LENGTH]
                    await failure_session.commit()
            raise
        finally:
            embedder.close()
            reranker.close()
    finally:
        await engine.dispose()
