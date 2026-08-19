"""Unit tests for the ORM models (docs/16 Phase 1 — Storage & indexes).

Exercises the models against in-memory SQLite so this suite needs no live
service. The real PostgreSQL migration is separately verified in
tests/integration/test_migration.py — these two together are what let
`alembic check` (run manually / in CI once Postgres is available) mean
something: the models are sound, and the migration matches them exactly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.models.orm import (
    AuditLogEntry,
    Base,
    Chunk,
    ChunkType,
    Citation,
    CitationStatus,
    Claim,
    ClaimEvidence,
    Document,
    DocumentType,
    EvidenceItem,
    IngestionRun,
    IngestionRunStatus,
    IngestionStatus,
    JobStatus,
    Report,
    ResearchJob,
    Tenant,
    User,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s


def _make_document(**overrides: object) -> Document:
    defaults: dict[str, object] = {
        "company": "NVIDIA",
        "ticker": "NVDA",
        "document_type": DocumentType.FORM_10K,
        "filing_date": datetime(2025, 2, 26, tzinfo=UTC),
        "fiscal_year": 2025,
        "source": "sec_edgar",
        "source_url": "https://www.sec.gov/example",
        "content_hash": "a" * 64,
        "raw_object_key": "raw/nvda/2025-10k.htm",
    }
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


def test_create_all_tables(session: Session) -> None:
    assert {
        "tenants",
        "users",
        "documents",
        "chunks",
        "jobs",
        "evidence_items",
        "claims",
        "claim_evidence",
        "citations",
        "reports",
        "audits",
        "ingestion_runs",
    }.issubset(Base.metadata.tables.keys())


def test_document_round_trip(session: Session) -> None:
    doc = _make_document()
    session.add(doc)
    session.commit()

    fetched = session.get(Document, doc.id)
    assert fetched is not None
    assert fetched.company == "NVIDIA"
    assert fetched.ticker == "NVDA"
    assert fetched.document_type == DocumentType.FORM_10K
    assert fetched.ingestion_status == IngestionStatus.PENDING
    assert fetched.version == 1


def test_content_hash_uniqueness_enforced(session: Session) -> None:
    """docs/04 requirement 1: identical content must not be embedded twice —
    enforced at the schema level, not just application logic.
    """
    session.add(_make_document(content_hash="b" * 64))
    session.commit()

    session.add(_make_document(content_hash="b" * 64, ticker="OTHER"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_document_versioning_via_supersedes(session: Session) -> None:
    original = _make_document(content_hash="c" * 64, version=1)
    session.add(original)
    session.commit()

    amended = _make_document(content_hash="d" * 64, version=2, supersedes_id=original.id)
    session.add(amended)
    session.commit()

    assert amended.supersedes_id == original.id


def test_chunk_belongs_to_document(session: Session) -> None:
    doc = _make_document(content_hash="e" * 64)
    session.add(doc)
    session.commit()

    chunk = Chunk(
        document_id=doc.id,
        chunk_index=0,
        chunk_type=ChunkType.TEXT,
        section="Item 7 MD&A",
        text="Gross margin declined due to...",
        token_count=42,
    )
    session.add(chunk)
    session.commit()

    fetched_doc = session.get(Document, doc.id)
    assert fetched_doc is not None
    assert len(fetched_doc.chunks) == 1
    assert fetched_doc.chunks[0].section == "Item 7 MD&A"


def test_evidence_chain_forward_built(session: Session) -> None:
    """docs/08: Source -> Passage -> Evidence item -> Claim -> Citation."""
    doc = _make_document(content_hash="f" * 64)
    session.add(doc)
    session.commit()

    chunk = Chunk(
        document_id=doc.id,
        chunk_index=0,
        text="Revenue grew 94% year over year.",
        token_count=8,
    )
    session.add(chunk)
    session.commit()

    job = ResearchJob(query="Why did revenue grow?", status=JobStatus.RUNNING)
    session.add(job)
    session.commit()

    evidence = EvidenceItem(
        job_id=job.id,
        chunk_id=chunk.id,
        supporting_passage="Revenue grew 94% year over year.",
        summary="Establishes YoY revenue growth rate.",
    )
    session.add(evidence)
    session.commit()

    claim = Claim(job_id=job.id, text="Revenue grew 94% YoY.", confidence="high")
    session.add(claim)
    session.commit()

    session.add(ClaimEvidence(claim_id=claim.id, evidence_id=evidence.id))
    session.commit()

    citation = Citation(
        claim_id=claim.id,
        evidence_id=evidence.id,
        document_id=doc.id,
        status=CitationStatus.ACCEPT,
        justification="Passage states the exact growth figure claimed.",
    )
    session.add(citation)
    session.commit()

    fetched_claim = session.get(Claim, claim.id)
    assert fetched_claim is not None
    assert len(fetched_claim.evidence_links) == 1
    assert fetched_claim.evidence_links[0].evidence.chunk_id == chunk.id
    assert len(fetched_claim.citations) == 1
    assert fetched_claim.citations[0].status == CitationStatus.ACCEPT


def test_report_persists_run_manifest(session: Session) -> None:
    job = ResearchJob(query="test", status=JobStatus.SUCCEEDED)
    session.add(job)
    session.commit()

    report = Report(
        job_id=job.id,
        final_report="...",
        run_manifest={"prompt_name": "research_synthesis", "prompt_version": 3},
    )
    session.add(report)
    session.commit()

    fetched = session.get(Report, report.id)
    assert fetched is not None
    assert fetched.run_manifest["prompt_version"] == 3


def test_audit_entry_can_be_tenant_scoped_without_a_job(session: Session) -> None:
    tenant = Tenant(name="acme-research")
    session.add(tenant)
    session.commit()

    entry = AuditLogEntry(
        tenant_id=tenant.id,
        actor="system",
        action="ingestion_run_started",
        detail={"source": "sec_edgar"},
    )
    session.add(entry)
    session.commit()

    assert session.get(AuditLogEntry, entry.id) is not None


def test_ingestion_run_telemetry_defaults(session: Session) -> None:
    run = IngestionRun(source="sec_edgar")
    session.add(run)
    session.commit()

    fetched = session.get(IngestionRun, run.id)
    assert fetched is not None
    assert fetched.status == IngestionRunStatus.RUNNING
    assert fetched.documents_processed == 0
    assert fetched.parser_errors == []


def test_tenant_and_user_relationship(session: Session) -> None:
    tenant = Tenant(name="acme-research")
    session.add(tenant)
    session.commit()

    user = User(tenant_id=tenant.id, email="analyst@example.com", hashed_password="x")
    session.add(user)
    session.commit()

    fetched_tenant = session.get(Tenant, tenant.id)
    assert fetched_tenant is not None
    assert len(fetched_tenant.users) == 1
    assert fetched_tenant.users[0].email == "analyst@example.com"
