"""Job endpoints (docs/16 Phase 1 Application): create a research job,
fetch its status/report, and stream status transitions over SSE.

D-16 (locked): research runs in a separate worker, never inline in a
request handler. This router only ever does two things — write a PENDING
`ResearchJob` row and enqueue a Celery task (`src/graph/tasks.py`) — the
actual `run_research()` call happens in that worker process.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from src.core.db import get_session, get_session_factory
from src.graph.tasks import enqueue_research_job
from src.models.orm import (
    AuditLogEntry,
    Citation,
    CitationStatus,
    Claim,
    ClaimEvidence,
    Document,
    EvidenceItem,
    JobStatus,
    Report,
    ResearchJob,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

STREAM_POLL_INTERVAL_SECONDS = 2.0
TERMINAL_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)
# A job outside these two statuses is either about to start or actively
# being written to by the Celery worker (progress_detail, claims, evidence,
# reports). Deleting it out from under that worker reproduces the exact
# ForeignKeyViolationError class of bug this project already hit once
# live (worker writes referencing a job_id/chunk_id that no longer
# exists) — so deletion is only ever allowed once a job is finished.
DELETABLE_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)


class CreateJobRequest(BaseModel):
    query: str = Field(min_length=1)
    tenant_id: uuid.UUID | None = None


class DocumentRef(BaseModel):
    document_id: uuid.UUID
    company: str
    ticker: str
    document_type: str


class CitationResponse(BaseModel):
    citation_id: uuid.UUID
    status: CitationStatus
    rewritten_claim_text: str | None
    justification: str
    supporting_passage: str
    evidence_summary: str
    document: DocumentRef


class ClaimResponse(BaseModel):
    claim_id: uuid.UUID
    text: str
    citations: list[CitationResponse]


class JobResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    query: str
    insufficient_evidence: bool
    progress_detail: str | None = None
    final_report: str | None = None
    error_message: str | None = None
    claims: list[ClaimResponse] = []


class JobSummary(BaseModel):
    """One row of a history listing — deliberately not `JobResponse`: a
    sidebar/history view renders many of these at once and has no use for
    each job's full claim/citation tree, which is the expensive part of
    `_load_job_response` (a join across citations/evidence/documents).
    """

    job_id: uuid.UUID
    query: str
    status: JobStatus
    insufficient_evidence: bool
    created_at: datetime


async def _load_claims(session: AsyncSession, job_id: uuid.UUID) -> list[ClaimResponse]:
    # ❗ Deliberately per-citation, not the flattened `final_report` string —
    # an evidence panel needs the verdict/justification/passage behind each
    # claim (docs/08's evidence chain), which the final report text throws
    # away once it's assembled. `Claim.text` is the Synthesizer's draft, not
    # the accepted/rewritten text — each citation's own `rewritten_claim_text`
    # carries that where the Citation Validator changed it.
    claims_result = await session.execute(
        select(Claim).where(Claim.job_id == job_id).order_by(Claim.created_at)
    )
    claims = claims_result.scalars().all()
    if not claims:
        return []

    claim_ids = [c.id for c in claims]
    rows = (
        await session.execute(
            select(Citation, EvidenceItem, Document)
            .join(EvidenceItem, Citation.evidence_id == EvidenceItem.id)
            .join(Document, Citation.document_id == Document.id)
            .where(Citation.claim_id.in_(claim_ids))
        )
    ).all()

    citations_by_claim: dict[uuid.UUID, list[CitationResponse]] = defaultdict(list)
    for citation, evidence, document in rows:
        citations_by_claim[citation.claim_id].append(
            CitationResponse(
                citation_id=citation.id,
                status=citation.status,
                rewritten_claim_text=citation.rewritten_claim_text,
                justification=citation.justification,
                supporting_passage=evidence.supporting_passage,
                evidence_summary=evidence.summary,
                document=DocumentRef(
                    document_id=document.id,
                    company=document.company,
                    ticker=document.ticker,
                    document_type=document.document_type.value,
                ),
            )
        )

    return [
        ClaimResponse(claim_id=c.id, text=c.text, citations=citations_by_claim.get(c.id, []))
        for c in claims
    ]


async def _load_job_response(session: AsyncSession, job: ResearchJob) -> JobResponse:
    final_report: str | None = None
    claims: list[ClaimResponse] = []
    if job.status == JobStatus.SUCCEEDED:
        result = await session.execute(
            select(Report).where(Report.job_id == job.id).order_by(Report.created_at.desc())
        )
        report = result.scalars().first()
        final_report = report.final_report if report else None
        claims = await _load_claims(session, job.id)

    return JobResponse(
        job_id=job.id,
        status=job.status,
        query=job.query,
        insufficient_evidence=job.insufficient_evidence,
        progress_detail=job.progress_detail,
        final_report=final_report,
        error_message=job.error_message,
        claims=claims,
    )


@router.post("", response_model=JobResponse, status_code=202)
async def create_job(
    body: CreateJobRequest, session: AsyncSession = Depends(get_session)
) -> JobResponse:
    job = ResearchJob(
        trace_id=str(uuid.uuid4()),
        tenant_id=body.tenant_id,
        query=body.query,
        status=JobStatus.PENDING,
        insufficient_evidence=False,
    )
    session.add(job)
    await session.commit()

    enqueue_research_job(
        job_id=str(job.id),
        query=body.query,
        tenant_id=str(body.tenant_id) if body.tenant_id else None,
        trace_id=job.trace_id or str(job.id),
    )

    return await _load_job_response(session, job)


@router.get("", response_model=list[JobSummary])
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[JobSummary]:
    result = await session.execute(
        select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(limit).offset(offset)
    )
    jobs = result.scalars().all()
    return [
        JobSummary(
            job_id=job.id,
            query=job.query,
            status=job.status,
            insufficient_evidence=job.insufficient_evidence,
            created_at=job.created_at,
        )
        for job in jobs
    ]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> JobResponse:
    job = await session.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await _load_job_response(session, job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    """Deletes a finished job and everything the evidence chain (docs/08)
    built for it — evidence items, claims, citations, reports, audit
    entries — none of which carry an ON DELETE CASCADE at the DB level, so
    they're removed explicitly, children before parents, in one
    transaction. See DELETABLE_STATUSES for why a still-running job is
    rejected rather than deleted.
    """
    job = await session.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in DELETABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"cannot delete a job with status {job.status.value!r} — wait for it to finish",
        )

    claims = (
        (await session.execute(select(Claim).where(Claim.job_id == job_id))).scalars().all()
    )
    evidence_items = (
        (await session.execute(select(EvidenceItem).where(EvidenceItem.job_id == job_id)))
        .scalars()
        .all()
    )
    claim_ids = [c.id for c in claims]
    evidence_ids = [e.id for e in evidence_items]

    if claim_ids or evidence_ids:
        citations = (
            (
                await session.execute(
                    select(Citation).where(
                        Citation.claim_id.in_(claim_ids) | Citation.evidence_id.in_(evidence_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for citation in citations:
            await session.delete(citation)

        claim_evidence_links = (
            (
                await session.execute(
                    select(ClaimEvidence).where(
                        ClaimEvidence.claim_id.in_(claim_ids)
                        | ClaimEvidence.evidence_id.in_(evidence_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for link in claim_evidence_links:
            await session.delete(link)

    for claim in claims:
        await session.delete(claim)
    for evidence in evidence_items:
        await session.delete(evidence)

    reports = (
        (await session.execute(select(Report).where(Report.job_id == job_id))).scalars().all()
    )
    for report in reports:
        await session.delete(report)

    audit_entries = (
        (await session.execute(select(AuditLogEntry).where(AuditLogEntry.job_id == job_id)))
        .scalars()
        .all()
    )
    for audit_entry in audit_entries:
        await session.delete(audit_entry)

    await session.delete(job)
    await session.commit()


@router.get("/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    job = await session.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_source() -> AsyncIterator[str]:
        # A fresh short-lived session per poll, not the request-scoped
        # `session` above — the job is updated by a *different* process (the
        # Celery worker), so re-using one long-held connection/transaction
        # for a poll that can run for minutes risks not seeing its commits
        # depending on how the driver manages the identity map.
        session_factory = get_session_factory()
        last_status: JobStatus | None = None
        last_progress: str | None = None
        while True:
            async with session_factory() as poll_session:
                current = await poll_session.get(ResearchJob, job_id)
            if current is None:
                yield "event: error\ndata: job not found\n\n"
                return
            if current.progress_detail is not None and current.progress_detail != last_progress:
                yield f"event: progress\ndata: {current.progress_detail}\n\n"
                last_progress = current.progress_detail
            if current.status != last_status:
                yield f"event: status\ndata: {current.status.value}\n\n"
                last_status = current.status
            if current.status in TERMINAL_STATUSES:
                return
            await asyncio.sleep(STREAM_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_source(), media_type="text/event-stream")
