"""Unit tests for src.graph.tasks — every real dependency (Qdrant, Ollama
embedder, PromptRunner, PostgreSQL session, run_research itself) mocked at
the module boundary. What's under test is the wrapper's own contract: it
flips the job to RUNNING before the long call, passes the right arguments
through to run_research, always closes the embedder, always disposes its
own engine, and on failure marks the job FAILED with a truncated error
message rather than leaving it stuck RUNNING forever.

The per-task engine (rather than the API's process-wide cached one) is
deliberate and load-bearing — see the module docstring in src/graph/tasks.py
for the real cross-event-loop asyncpg crash that reusing a cached engine
caused when two Celery tasks ran back-to-back under --pool=solo.

Celery dispatch/execution and the real pipeline are covered elsewhere
(test_pipeline.py, test_jobs_api.py, the live integration test) — this file
only exercises the glue.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config import get_settings
from src.graph import tasks
from src.models.orm import JobStatus
from src.observability.metrics import WORKER_JOB_FAILURES


class _FakeSession:
    def __init__(self, job: MagicMock) -> None:
        self.job = job
        self.commit_count = 0

    async def get(self, _model: type, pk: object) -> MagicMock | None:
        return self.job if pk == self.job.id else None

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeSessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _patch_engine_and_session(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> MagicMock:
    """Stands in for `_make_engine_and_session_factory()` — returns the fake
    engine so a test can assert `.dispose()` was actually awaited, the
    behavior that fixes the real stale-event-loop bug this module's
    docstring describes.
    """
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(
        tasks,
        "_make_engine_and_session_factory",
        lambda: (fake_engine, lambda: _FakeSessionCtx(session)),
    )
    return fake_engine


def _patch_heavy_dependencies(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Every real service constructor `_run_research_job` touches, replaced
    with a MagicMock class — returns the fake embedder instance so a test
    can assert `.close()` was called.
    """
    monkeypatch.setattr(tasks, "QdrantClient", MagicMock())
    monkeypatch.setattr(tasks, "QdrantStore", MagicMock())
    fake_embedder = MagicMock()
    monkeypatch.setattr(tasks, "OllamaEmbedder", MagicMock(return_value=fake_embedder))
    monkeypatch.setattr(tasks, "Bm25SparseEncoder", MagicMock())
    monkeypatch.setattr(tasks, "HybridRetriever", MagicMock())
    monkeypatch.setattr(tasks, "PromptRepository", MagicMock())

    fake_prompt_runner = MagicMock()
    fake_prompt_runner.__enter__ = MagicMock(return_value=fake_prompt_runner)
    fake_prompt_runner.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(tasks, "PromptRunner", MagicMock(return_value=fake_prompt_runner))
    return fake_embedder


async def test_run_research_job_flips_to_running_then_calls_run_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = MagicMock()
    job.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    job.status = JobStatus.PENDING
    session = _FakeSession(job)
    fake_engine = _patch_engine_and_session(monkeypatch, session)

    fake_embedder = _patch_heavy_dependencies(monkeypatch)
    run_research_mock = AsyncMock()
    monkeypatch.setattr(tasks, "run_research", run_research_mock)

    await tasks._run_research_job(
        job_id=str(job.id), query="Why did margin decline?", tenant_id=None, trace_id="trace-1"
    )

    assert (
        job.status == JobStatus.RUNNING
    )  # set here; run_research (mocked) would advance it further for real
    assert job.progress_detail == "Starting research"
    run_research_mock.assert_awaited_once()
    _, kwargs = run_research_mock.call_args
    assert kwargs["research_id"] == str(job.id)
    assert kwargs["trace_id"] == "trace-1"
    assert kwargs["model"] == get_settings().ollama_chat_model
    assert kwargs["tenant_id"] is None
    assert callable(kwargs["on_progress"])
    assert session.commit_count >= 2  # the RUNNING flip + the post-run_research commit
    fake_embedder.close.assert_called_once()
    fake_engine.dispose.assert_awaited_once()


async def test_progress_callback_updates_job_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = MagicMock()
    job.id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    session = _FakeSession(job)
    session_factory = lambda: _FakeSessionCtx(session)  # noqa: E731

    on_progress = tasks._make_progress_callback(session_factory, str(job.id))
    await on_progress("Extracting evidence for: q1")

    assert job.progress_detail == "Extracting evidence for: q1"
    assert session.commit_count == 1


async def test_progress_callback_no_op_for_unknown_job() -> None:
    session = _FakeSession(MagicMock(id=uuid.uuid4()))
    session_factory = lambda: _FakeSessionCtx(session)  # noqa: E731

    on_progress = tasks._make_progress_callback(session_factory, str(uuid.uuid4()))
    await on_progress("should be a no-op")  # job id doesn't match session.job.id

    assert session.commit_count == 0


async def test_run_research_job_failure_marks_job_failed_with_truncated_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = MagicMock()
    job.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    job.status = JobStatus.PENDING
    session = _FakeSession(job)
    fake_engine = _patch_engine_and_session(monkeypatch, session)

    fake_embedder = _patch_heavy_dependencies(monkeypatch)
    monkeypatch.setattr(
        tasks, "run_research", AsyncMock(side_effect=RuntimeError("Ollama unreachable"))
    )

    with pytest.raises(RuntimeError, match="Ollama unreachable"):
        await tasks._run_research_job(job_id=str(job.id), query="q", tenant_id=None, trace_id="t")

    assert job.status == JobStatus.FAILED
    assert job.error_message == "Ollama unreachable"
    fake_embedder.close.assert_called_once()
    fake_engine.dispose.assert_awaited_once()


def test_make_engine_and_session_factory_is_not_cached_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this guards: a Celery task running under
    `asyncio.run()` (--pool=solo) gets a *new* event loop every invocation.
    An engine cached across invocations (as `src.core.db.get_engine()` is,
    correctly, for the single-event-loop API process) is bound to whichever
    loop created it — reusing it from a second task's loop is what produced
    the real `AttributeError: 'NoneType' object has no attribute 'send'`
    crash. `_make_engine_and_session_factory()` must build a genuinely new
    engine on every call, not hand back a memoized one.
    """
    if get_settings().database_url is None:
        pytest.skip("DATABASE_URL not set")

    sentinel_engines = [MagicMock(name="engine-1"), MagicMock(name="engine-2")]
    monkeypatch.setattr(tasks, "create_async_engine", MagicMock(side_effect=sentinel_engines))
    monkeypatch.setattr(tasks, "async_sessionmaker", MagicMock())

    first_engine, _ = tasks._make_engine_and_session_factory()
    second_engine, _ = tasks._make_engine_and_session_factory()

    assert first_engine is sentinel_engines[0]
    assert second_engine is sentinel_engines[1]
    assert first_engine is not second_engine


async def test_run_research_job_truncates_overlong_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = MagicMock()
    job.id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    job.status = JobStatus.PENDING
    session = _FakeSession(job)
    _patch_engine_and_session(monkeypatch, session)

    _patch_heavy_dependencies(monkeypatch)
    huge_message = "x" * (tasks.MAX_ERROR_MESSAGE_LENGTH + 500)
    monkeypatch.setattr(tasks, "run_research", AsyncMock(side_effect=RuntimeError(huge_message)))

    with pytest.raises(RuntimeError):
        await tasks._run_research_job(job_id=str(job.id), query="q", tenant_id=None, trace_id="t")

    assert job.error_message is not None
    assert len(job.error_message) == tasks.MAX_ERROR_MESSAGE_LENGTH


def test_run_research_task_calls_asyncio_run_with_the_async_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_with: dict[str, object] = {}

    async def fake_run_research_job(**kwargs: object) -> None:
        called_with.update(kwargs)

    monkeypatch.setattr(tasks, "_run_research_job", fake_run_research_job)
    # A real _record_queue_depth() would open a live connection to whatever
    # CELERY_BROKER_URL happens to be configured in this environment — a
    # "unit" test must not depend on a real Redis being reachable.
    monkeypatch.setattr(tasks, "_record_queue_depth", lambda: None)

    tasks.run_research_task(job_id="j1", query="q1", tenant_id="t1", trace_id="trace-1")

    assert called_with == {"job_id": "j1", "query": "q1", "tenant_id": "t1", "trace_id": "trace-1"}


def test_run_research_task_does_not_record_a_failure_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_run_research_job", AsyncMock())
    monkeypatch.setattr(tasks, "_record_queue_depth", lambda: None)
    before = WORKER_JOB_FAILURES.labels(queue=tasks.RESEARCH_QUEUE_NAME)._value.get()

    tasks.run_research_task(job_id="j1", query="q1", tenant_id=None, trace_id="t1")

    after = WORKER_JOB_FAILURES.labels(queue=tasks.RESEARCH_QUEUE_NAME)._value.get()
    assert after == before


def test_run_research_task_records_a_failure_and_still_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks, "_run_research_job", AsyncMock(side_effect=RuntimeError("Ollama unreachable"))
    )
    monkeypatch.setattr(tasks, "_record_queue_depth", lambda: None)
    before = WORKER_JOB_FAILURES.labels(queue=tasks.RESEARCH_QUEUE_NAME)._value.get()

    with pytest.raises(RuntimeError, match="Ollama unreachable"):
        tasks.run_research_task(job_id="j1", query="q1", tenant_id=None, trace_id="t1")

    after = WORKER_JOB_FAILURES.labels(queue=tasks.RESEARCH_QUEUE_NAME)._value.get()
    assert after == before + 1


def test_record_queue_depth_is_a_noop_without_a_configured_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings = MagicMock(celery_broker_url=None)
    monkeypatch.setattr(tasks, "get_settings", lambda: fake_settings)

    tasks._record_queue_depth()  # must not raise, must not touch redis at all


def test_record_queue_depth_swallows_a_broken_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A metrics read failing (Redis down, a bad URL, whatever) must never be
    what fails a real research job — this is best-effort telemetry, not a
    dependency of the pipeline.
    """
    fake_settings = MagicMock(celery_broker_url="redis://example.invalid:6379/0")
    monkeypatch.setattr(tasks, "get_settings", lambda: fake_settings)
    fake_redis_class = MagicMock()
    fake_redis_class.from_url.return_value.llen.side_effect = ConnectionError("down")
    monkeypatch.setattr(tasks.redis, "Redis", fake_redis_class)

    tasks._record_queue_depth()  # must not raise


def test_enqueue_research_job_dispatches_via_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    delay_calls: list[dict[str, object]] = []
    monkeypatch.setattr(tasks.run_research_task, "delay", lambda **kw: delay_calls.append(kw))

    tasks.enqueue_research_job(job_id="j1", query="q1", tenant_id=None, trace_id="trace-1")

    assert delay_calls == [
        {"job_id": "j1", "query": "q1", "tenant_id": None, "trace_id": "trace-1"}
    ]
