"""Unit tests for apps/api/routers/jobs.py — DB session faked (no real
PostgreSQL; see tests/unit/test_pipeline.py for the same convention), Celery
enqueue faked (no real Redis/worker). What's under test is the API's own
contract: create writes a PENDING row and enqueues exactly once, fetch
resolves the report only once SUCCEEDED, unknown ids 404, and the SSE stream
emits status transitions and stops at a terminal state.

Real end-to-end job execution (API -> Celery -> run_research -> Postgres)
is out of scope here — that requires a live worker process and belongs in
an integration test, not this unit suite.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from src.core.db import get_session
from src.models.orm import (
    AuditLogEntry,
    Citation,
    CitationStatus,
    Claim,
    ClaimEvidence,
    Document,
    DocumentType,
    EvidenceItem,
    JobStatus,
    Report,
    ResearchJob,
)


def _selected_entity_names(stmt: object) -> list[str]:
    descriptions = getattr(stmt, "column_descriptions", [])
    return [d["entity"].__name__ for d in descriptions if d.get("entity") is not None]


class FakeAsyncSession:
    """Just enough of AsyncSession's surface for the jobs router: add/commit
    a job, get it back by id, and resolve its latest report/claims/citations
    by a select — dispatched on the query's selected entity, since the
    router issues three structurally different selects against this same
    fake.
    """

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, ResearchJob] = {}
        self.reports: list[Report] = []
        self.claims: list[Claim] = []
        self.citation_rows: list[tuple[Citation, EvidenceItem, Document]] = []
        self.evidence_items: list[EvidenceItem] = []
        self.claim_evidence: list[ClaimEvidence] = []
        self.audit_entries: list[AuditLogEntry] = []
        self.deleted: list[object] = []

    def add(self, obj: object) -> None:
        if isinstance(obj, ResearchJob):
            if obj.id is None:
                # Real SQLAlchemy only assigns the `default=uuid.uuid4`
                # primary key at flush time — a fake standing in for a real
                # session has to replicate that, not silently leave it None.
                obj.id = uuid.uuid4()
            self.jobs[obj.id] = obj

    async def commit(self) -> None:
        pass

    async def get(self, model: type, pk: uuid.UUID) -> object | None:
        if model is ResearchJob:
            return self.jobs.get(pk)
        return None

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)
        if isinstance(obj, ResearchJob):
            self.jobs.pop(obj.id, None)
        elif isinstance(obj, Claim):
            self.claims = [c for c in self.claims if c.id != obj.id]
        elif isinstance(obj, EvidenceItem):
            self.evidence_items = [e for e in self.evidence_items if e.id != obj.id]
        elif isinstance(obj, Citation):
            self.citation_rows = [row for row in self.citation_rows if row[0].id != obj.id]
        elif isinstance(obj, ClaimEvidence):
            self.claim_evidence = [
                link
                for link in self.claim_evidence
                if (link.claim_id, link.evidence_id) != (obj.claim_id, obj.evidence_id)
            ]
        elif isinstance(obj, Report):
            self.reports = [r for r in self.reports if r is not obj]
        elif isinstance(obj, AuditLogEntry):
            self.audit_entries = [a for a in self.audit_entries if a.id != obj.id]

    async def execute(self, stmt: object) -> MagicMock:
        entities = _selected_entity_names(stmt)
        result = MagicMock()
        if entities == ["Report"]:
            result.scalars.return_value.first.return_value = (
                self.reports[0] if self.reports else None
            )
            result.scalars.return_value.all.return_value = self.reports
        elif entities == ["Claim"]:
            result.scalars.return_value.all.return_value = self.claims
        elif entities == ["Citation", "EvidenceItem", "Document"]:
            result.all.return_value = self.citation_rows
        elif entities == ["Citation"]:
            result.scalars.return_value.all.return_value = [row[0] for row in self.citation_rows]
        elif entities == ["EvidenceItem"]:
            result.scalars.return_value.all.return_value = self.evidence_items
        elif entities == ["ClaimEvidence"]:
            result.scalars.return_value.all.return_value = self.claim_evidence
        elif entities == ["AuditLogEntry"]:
            result.scalars.return_value.all.return_value = self.audit_entries
        elif entities == ["ResearchJob"]:
            ordered = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
            limit = stmt._limit_clause.value if stmt._limit_clause is not None else None  # type: ignore[attr-defined]
            offset = stmt._offset_clause.value if stmt._offset_clause is not None else 0  # type: ignore[attr-defined]
            paged = ordered[offset : offset + limit if limit is not None else None]
            result.scalars.return_value.all.return_value = paged
        return result


def _override_session(fake: FakeAsyncSession) -> object:
    async def _get_session() -> AsyncIterator[object]:
        yield fake

    return _get_session


def test_create_job_persists_pending_row_and_enqueues_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeAsyncSession()
    app.dependency_overrides[get_session] = _override_session(fake)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "apps.api.routers.jobs.enqueue_research_job",
        lambda **kwargs: calls.append(kwargs),
    )

    try:
        with TestClient(app) as client:
            response = client.post("/jobs", json={"query": "Why did margin decline?"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["query"] == "Why did margin decline?"
    assert body["final_report"] is None

    assert len(fake.jobs) == 1
    assert len(calls) == 1
    assert calls[0]["job_id"] == body["job_id"]
    assert calls[0]["query"] == "Why did margin decline?"


def test_get_job_returns_404_for_unknown_id() -> None:
    fake = FakeAsyncSession()
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 404


def test_get_job_includes_final_report_only_once_succeeded() -> None:
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    job = ResearchJob(id=job_id, query="q", status=JobStatus.RUNNING, insufficient_evidence=False)
    fake.jobs[job_id] = job
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            running_response = client.get(f"/jobs/{job_id}")
            assert running_response.json()["final_report"] is None

            job.status = JobStatus.SUCCEEDED
            fake.reports.append(
                Report(job_id=job_id, final_report="Margin declined due to higher costs.")
            )
            succeeded_response = client.get(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = succeeded_response.json()
    assert body["status"] == "succeeded"
    assert body["final_report"] == "Margin declined due to higher costs."


def test_get_job_includes_claims_and_citations_once_succeeded() -> None:
    """The evidence panel needs claim -> citation -> evidence/document detail,
    not the flattened `final_report` string — this is what a frontend
    evidence panel actually renders.
    """
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    job = ResearchJob(id=job_id, query="q", status=JobStatus.SUCCEEDED, insufficient_evidence=False)
    fake.jobs[job_id] = job
    fake.reports.append(Report(job_id=job_id, final_report="Margin declined."))

    claim_id = uuid.uuid4()
    fake.claims.append(Claim(id=claim_id, job_id=job_id, text="Margin declined due to costs."))

    document_id = uuid.uuid4()
    document = Document(
        id=document_id,
        company="NVIDIA CORP",
        ticker="NVDA",
        document_type=DocumentType.FORM_10Q,
        filing_date=datetime(2026, 5, 20, tzinfo=UTC),
        source="sec_edgar",
        source_url="https://example.com",
        raw_object_key="key",
        content_hash="hash",
    )
    evidence = EvidenceItem(
        id=uuid.uuid4(),
        job_id=job_id,
        chunk_id=uuid.uuid4(),
        supporting_passage="Gross margin declined due to higher costs.",
        summary="Margin decline explained",
    )
    citation = Citation(
        id=uuid.uuid4(),
        claim_id=claim_id,
        evidence_id=evidence.id,
        document_id=document_id,
        status=CitationStatus.ACCEPT,
        rewritten_claim_text=None,
        justification="matches exactly",
    )
    fake.citation_rows.append((citation, evidence, document))

    app.dependency_overrides[get_session] = _override_session(fake)
    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = response.json()
    assert len(body["claims"]) == 1
    claim = body["claims"][0]
    assert claim["text"] == "Margin declined due to costs."
    assert len(claim["citations"]) == 1
    citation_body = claim["citations"][0]
    assert citation_body["status"] == "accept"
    assert citation_body["supporting_passage"] == "Gross margin declined due to higher costs."
    assert citation_body["document"]["ticker"] == "NVDA"
    assert citation_body["document"]["company"] == "NVIDIA CORP"


def test_get_job_includes_progress_detail() -> None:
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    job = ResearchJob(id=job_id, query="q", status=JobStatus.RUNNING, insufficient_evidence=False)
    job.progress_detail = "Extracting evidence for: What was revenue?"
    fake.jobs[job_id] = job
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.json()["progress_detail"] == "Extracting evidence for: What was revenue?"


def test_get_job_surfaces_error_message_when_failed() -> None:
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    fake.jobs[job_id] = ResearchJob(
        id=job_id,
        query="q",
        status=JobStatus.FAILED,
        insufficient_evidence=False,
        error_message="Ollama unreachable",
    )
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "Ollama unreachable"


def test_list_jobs_returns_summaries_ordered_newest_first() -> None:
    fake = FakeAsyncSession()
    older = ResearchJob(
        id=uuid.uuid4(),
        query="older question",
        status=JobStatus.SUCCEEDED,
        insufficient_evidence=False,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    newer = ResearchJob(
        id=uuid.uuid4(),
        query="newer question",
        status=JobStatus.RUNNING,
        insufficient_evidence=False,
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    fake.jobs[older.id] = older
    fake.jobs[newer.id] = newer
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get("/jobs")
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = response.json()
    assert [row["query"] for row in body] == ["newer question", "older question"]
    # A summary row has no claims/citations — the whole point is staying
    # cheap for a sidebar rendering many of these at once.
    assert "claims" not in body[0]


def test_list_jobs_respects_limit_and_offset() -> None:
    fake = FakeAsyncSession()
    for i in range(5):
        job_id = uuid.uuid4()
        fake.jobs[job_id] = ResearchJob(
            id=job_id,
            query=f"question {i}",
            status=JobStatus.SUCCEEDED,
            insufficient_evidence=False,
            created_at=datetime(2026, 8, 1 + i, tzinfo=UTC),
        )
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get("/jobs", params={"limit": 2, "offset": 1})
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = response.json()
    # created_at descending: question 4, 3, 2, 1, 0 -> offset 1, limit 2 -> [3, 2]
    assert [row["query"] for row in body] == ["question 3", "question 2"]


def test_delete_job_returns_404_for_unknown_id() -> None:
    fake = FakeAsyncSession()
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.delete(f"/jobs/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 404


def test_delete_job_rejects_a_still_running_job() -> None:
    """Deleting a job the worker is actively writing to would reproduce the
    ForeignKeyViolationError class of bug this project already hit live —
    a running job must be rejected, not deleted.
    """
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    fake.jobs[job_id] = ResearchJob(
        id=job_id, query="q", status=JobStatus.RUNNING, insufficient_evidence=False
    )
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.delete(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 409
    assert job_id in fake.jobs


def test_delete_job_removes_a_succeeded_job_and_its_evidence_chain() -> None:
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    fake.jobs[job_id] = ResearchJob(
        id=job_id, query="q", status=JobStatus.SUCCEEDED, insufficient_evidence=False
    )
    fake.reports.append(Report(id=uuid.uuid4(), job_id=job_id, final_report="Margin declined."))

    claim_id = uuid.uuid4()
    fake.claims.append(Claim(id=claim_id, job_id=job_id, text="Margin declined due to costs."))

    evidence = EvidenceItem(
        id=uuid.uuid4(),
        job_id=job_id,
        chunk_id=uuid.uuid4(),
        supporting_passage="Gross margin declined.",
        summary="Margin decline explained",
    )
    fake.evidence_items.append(evidence)
    fake.claim_evidence.append(ClaimEvidence(claim_id=claim_id, evidence_id=evidence.id))

    document_id = uuid.uuid4()
    document = Document(
        id=document_id,
        company="NVIDIA CORP",
        ticker="NVDA",
        document_type=DocumentType.FORM_10Q,
        filing_date=datetime(2026, 5, 20, tzinfo=UTC),
        source="sec_edgar",
        source_url="https://example.com",
        raw_object_key="key",
        content_hash="hash",
    )
    citation = Citation(
        id=uuid.uuid4(),
        claim_id=claim_id,
        evidence_id=evidence.id,
        document_id=document_id,
        status=CitationStatus.ACCEPT,
        rewritten_claim_text=None,
        justification="matches exactly",
    )
    fake.citation_rows.append((citation, evidence, document))
    fake.audit_entries.append(AuditLogEntry(id=uuid.uuid4(), job_id=job_id, actor="system", action="x"))

    app.dependency_overrides[get_session] = _override_session(fake)
    try:
        with TestClient(app) as client:
            response = client.delete(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 204
    assert job_id not in fake.jobs
    assert fake.claims == []
    assert fake.evidence_items == []
    assert fake.claim_evidence == []
    assert fake.citation_rows == []
    assert fake.reports == []
    assert fake.audit_entries == []


def test_delete_job_allows_a_failed_job() -> None:
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    fake.jobs[job_id] = ResearchJob(
        id=job_id,
        query="q",
        status=JobStatus.FAILED,
        insufficient_evidence=False,
        error_message="Ollama unreachable",
    )
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.delete(f"/jobs/{job_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 204
    assert job_id not in fake.jobs


def test_stream_job_404_for_unknown_id_before_streaming() -> None:
    fake = FakeAsyncSession()
    app.dependency_overrides[get_session] = _override_session(fake)

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{uuid.uuid4()}/stream")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 404


def test_stream_job_emits_status_transitions_and_stops_at_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stream polls a *separate* short-lived session per tick (it must —
    the job is updated by a different process, the Celery worker). Faked
    here as a queue of statuses handed out one per poll, standing in for the
    worker's session committing progress over time without any real
    concurrency or sleeping in the test itself.
    """
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    job = ResearchJob(id=job_id, query="q", status=JobStatus.RUNNING, insufficient_evidence=False)
    fake.jobs[job_id] = job
    app.dependency_overrides[get_session] = _override_session(fake)

    statuses = iter([JobStatus.RUNNING, JobStatus.RUNNING, JobStatus.SUCCEEDED])

    class _PollSession:
        async def get(self, _model: type, pk: uuid.UUID) -> ResearchJob | None:
            polled = fake.jobs.get(pk)
            if polled is None:
                return None
            polled.status = next(statuses, polled.status)
            return polled

    class _PollSessionCtx:
        async def __aenter__(self) -> _PollSession:
            return _PollSession()

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(
        "apps.api.routers.jobs.get_session_factory", lambda: lambda: _PollSessionCtx()
    )
    monkeypatch.setattr("apps.api.routers.jobs.STREAM_POLL_INTERVAL_SECONDS", 0.0)

    try:
        with TestClient(app) as client, client.stream("GET", f"/jobs/{job_id}/stream") as response:
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]
    finally:
        app.dependency_overrides.pop(get_session, None)

    data_lines = [line for line in lines if line.startswith("data:")]
    assert data_lines == ["data: running", "data: succeeded"]


def test_stream_job_emits_progress_events_alongside_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real per-stage progress (docs/16 Application) — a client should see
    "Planning research approach" -> "Decomposing into sub-questions" -> ...
    over the wire as separate `event: progress` frames, not just the three
    coarse status values.
    """
    fake = FakeAsyncSession()
    job_id = uuid.uuid4()
    job = ResearchJob(id=job_id, query="q", status=JobStatus.RUNNING, insufficient_evidence=False)
    fake.jobs[job_id] = job
    app.dependency_overrides[get_session] = _override_session(fake)

    # One (progress, status) pair handed out per poll tick.
    ticks = iter(
        [
            ("Planning research approach", JobStatus.RUNNING),
            ("Planning research approach", JobStatus.RUNNING),  # unchanged -> no duplicate event
            ("Decomposing into sub-questions", JobStatus.RUNNING),
            (None, JobStatus.SUCCEEDED),
        ]
    )

    class _PollSession:
        async def get(self, _model: type, pk: uuid.UUID) -> ResearchJob | None:
            polled = fake.jobs.get(pk)
            if polled is None:
                return None
            progress, status = next(ticks, (polled.progress_detail, polled.status))
            if progress is not None:
                polled.progress_detail = progress
            polled.status = status
            return polled

    class _PollSessionCtx:
        async def __aenter__(self) -> _PollSession:
            return _PollSession()

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(
        "apps.api.routers.jobs.get_session_factory", lambda: lambda: _PollSessionCtx()
    )
    monkeypatch.setattr("apps.api.routers.jobs.STREAM_POLL_INTERVAL_SECONDS", 0.0)

    try:
        with TestClient(app) as client, client.stream("GET", f"/jobs/{job_id}/stream") as response:
            lines = [line for line in response.iter_lines() if line]
    finally:
        app.dependency_overrides.pop(get_session, None)

    events = list(zip(lines[::2], lines[1::2], strict=True))
    progress_data = [data for event, data in events if event == "event: progress"]
    assert progress_data == [
        "data: Planning research approach",
        "data: Decomposing into sub-questions",
    ]
