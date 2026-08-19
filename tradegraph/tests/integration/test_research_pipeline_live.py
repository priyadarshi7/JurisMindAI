"""End-to-end integration test: the full linear research pipeline against
every real service — SEC EDGAR, PostgreSQL, MinIO, Qdrant, and Ollama
serving real Qwen3 models (qwen3-embedding:0.6b for retrieval, qwen3:4b for
every reasoning node). No mocks.

This is the strongest available verification of docs/00's MVP flow:
Planner -> Query Decomposer -> {retrieve -> extract -> verify -> detect
contradictions} -> Synthesize -> Critic -> Citation Validator -> a report
whose claims trace back to a real, live-ingested NVIDIA 10-Q.

Slow by nature (a real reasoning chain over a local CPU-served model is
tens of LLM calls) — run deliberately, not as part of the default suite.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.config import get_settings
from src.data.object_storage import ObjectStorageClient
from src.graph.pipeline import run_research
from src.graph.prompt_runner import PromptRunner
from src.models.orm import Citation, Claim
from src.prompts.loader import PromptRepository
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.hybrid.retriever import HybridRetriever
from src.rag.ingestion.pipeline import ingest_filing
from src.rag.ingestion.sec_edgar import SecEdgarClient
from src.rag.vector.qdrant_store import QdrantStore

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "prompts"
CHAT_MODEL = "qwen3:4b"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(str(settings.database_url))
    try:
        async with engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
        return
    async with AsyncSession(engine) as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def storage() -> ObjectStorageClient:
    settings = get_settings()
    client = ObjectStorageClient(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
    )
    try:
        client.ensure_bucket(settings.s3_bucket_raw_documents)
    except Exception as exc:
        pytest.skip(f"MinIO not reachable: {exc}")
    return client


@pytest.fixture
def qdrant_store() -> QdrantStore:
    settings = get_settings()
    try:
        client = QdrantClient(url=settings.qdrant_url, timeout=5)
        client.get_collections()
    except Exception as exc:
        pytest.skip(f"Qdrant not reachable: {exc}")

    collection_name = "tradegraph_research_pipeline_test"
    if collection_name in {c.name for c in client.get_collections().collections}:
        client.delete_collection(collection_name)

    store = QdrantStore(client, collection_name=collection_name)
    store.ensure_collection(dense_dimension=settings.ollama_embedding_dimension)
    return store


@pytest.fixture
def embedder() -> OllamaEmbedder:
    settings = get_settings()
    e = OllamaEmbedder(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        expected_dimension=settings.ollama_embedding_dimension,
    )
    try:
        e.embed_query("healthcheck")
    except httpx.HTTPError as exc:
        pytest.skip(f"Ollama embedding model not reachable: {exc}")
    return e


@pytest.fixture
def bm25_encoder() -> Bm25SparseEncoder:
    return Bm25SparseEncoder()


@pytest.fixture
def edgar_client() -> SecEdgarClient:
    return SecEdgarClient(user_agent="TradeGraph-Test research@example.com")


@pytest.fixture
def prompt_runner() -> Iterator[PromptRunner]:
    settings = get_settings()
    try:
        # Cheap reachability probe before committing to a run that could
        # involve dozens of real LLM calls.
        httpx.get(settings.ollama_base_url, timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"Ollama not reachable: {exc}")

    repository = PromptRepository(PROMPTS_ROOT)
    with PromptRunner(base_url=settings.ollama_base_url, prompt_repository=repository) as runner:
        yield runner


async def test_research_pipeline_over_real_ingested_filing(
    session: AsyncSession,
    storage: ObjectStorageClient,
    qdrant_store: QdrantStore,
    embedder: OllamaEmbedder,
    bm25_encoder: Bm25SparseEncoder,
    edgar_client: SecEdgarClient,
    prompt_runner: PromptRunner,
) -> None:
    settings = get_settings()

    try:
        filings = edgar_client.list_filings("NVDA", forms=frozenset({"10-Q"}))
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")
    assert filings, "expected at least one recent NVDA 10-Q"
    filing = max(filings, key=lambda f: f.filing_date)

    ingestion = await ingest_filing(
        filing,
        edgar_client=edgar_client,
        storage=storage,
        session=session,
        embedder=embedder,
        bm25_encoder=bm25_encoder,
        qdrant_store=qdrant_store,
        raw_bucket=settings.s3_bucket_raw_documents,
    )
    assert ingestion.chunks_created > 0

    retriever = HybridRetriever(store=qdrant_store, embedder=embedder, sparse_encoder=bm25_encoder)

    research_id = str(uuid.uuid4())
    outcome = await run_research(
        "What did NVIDIA report about its revenue and gross margin in this quarterly filing?",
        session=session,
        retriever=retriever,
        prompt_runner=prompt_runner,
        model=CHAT_MODEL,
        research_id=research_id,
        trace_id="trace-live-test",
    )

    # A working pipeline has exactly two honest outcomes: it found and
    # cited real evidence, or it declared insufficiency truthfully. What it
    # must never do is crash, or produce an empty non-insufficient report.
    assert outcome.final_report.strip()
    assert len(outcome.llm_call_records) >= 2  # at minimum: planner + query_rewriter ran

    if not outcome.insufficient_evidence:
        # Claims and citations actually landed in PostgreSQL — not just
        # returned in memory.
        claims = (
            (await session.execute(select(Claim).where(Claim.job_id == outcome.job_id)))
            .scalars()
            .all()
        )
        citations = (
            (
                await session.execute(
                    select(Citation).where(Citation.claim_id.in_([c.id for c in claims]))
                )
            )
            .scalars()
            .all()
        )
        assert len(claims) > 0
        assert len(citations) > 0
        assert all(c.justification for c in citations)
