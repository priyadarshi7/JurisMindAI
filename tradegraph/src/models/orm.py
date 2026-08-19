"""SQLAlchemy ORM models — the PostgreSQL system of record.

Covers every entity docs/16 Phase 1 lists: users, jobs, documents, chunks,
claims, evidence, citations, reports, audits — plus `tenants` (D-11) and
`ingestion_runs` (docs/04 requirement 5, ingestion telemetry) which the
other nine entities depend on or are required to populate.

Shape mirrors the forward-built evidence chain in docs/08:

    documents -< chunks -< evidence_items >-< claims -< citations
                                                 |
                                              reports

Every table that can hold private data carries a nullable `tenant_id`
(D-11). NULL means "shared corpus" (SEC filings, IR materials — public by
nature); a real tenant id means the row is private and must be filtered
everywhere the row could be read, including retrieval (docs/11 — the
PostgreSQL filter is necessary but not sufficient by itself).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.models.db_types import GUID, PortableJSON


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


# All timestamps are timezone-aware, explicitly — relying on SQLAlchemy's
# type-map inference from a bare `Mapped[datetime]` silently produces a
# naive DateTime, which is exactly the kind of ambiguity a financial
# research system (filing dates, point-in-time market data, audit
# timestamps) cannot afford. Every timestamp column goes through one of
# these three helpers so the choice is made once, not per-column.
def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _nullable_timestamp() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------
# Enums (native_enum=False: portable VARCHAR+CHECK, so adding a value is a
# data migration, not a schema ALTER TYPE, on every dialect including
# PostgreSQL).
# --------------------------------------------------------------------------


class DocumentType(StrEnum):
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"
    ANNUAL_REPORT = "annual_report"
    EARNINGS_RELEASE = "earnings_release"
    INVESTOR_PRESENTATION = "investor_presentation"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    NEWS = "news"
    OTHER = "other"

    # Legal corpus (NyayaGraph pivot, 2026-08-19) — see docs/16 for the
    # phased build order. A single Document/Chunk/evidence-chain schema
    # serves both domains; these values are additive, not a replacement.
    CONSTITUTION = "constitution"
    CENTRAL_ACT = "central_act"
    JUDGMENT_SC = "judgment_sc"
    JUDGMENT_HC = "judgment_hc"
    NOTIFICATION = "notification"


class IngestionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"  # D-5 human review interrupt
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CitationStatus(StrEnum):
    """The four entailment-gate outcomes (docs/08, D-23)."""

    ACCEPT = "accept"
    REWRITE = "rewrite"
    REMOVE = "remove"
    FLAG = "flag"


class IngestionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


# --------------------------------------------------------------------------
# Tenancy & identity (D-11)
# --------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = _created_at()

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="users")


# --------------------------------------------------------------------------
# Corpus (docs/03, docs/04)
# --------------------------------------------------------------------------


class Document(Base):
    """One version of one source document.

    Field set is the union required by docs/03: `datasource.txt` §4's list
    (stable ID, source/provenance, company/ticker, document type,
    period/date, content hash, version, ingestion timestamp) plus the
    Blueprint §4 schema fields (fiscal_year, quarter, section is chunk-level
    not document-level here since a filing spans many sections).
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        Index("ix_documents_company_type_period", "company", "document_type", "filing_date"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.id"), nullable=True, index=True
    )

    company: Mapped[str] = mapped_column(String(255), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, native_enum=False))
    filing_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # docs/03: filing_date is the primary structural defence against
    # look-ahead bias (D-6) — never nullable, always the real filing date.
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String(64))  # e.g. "sec_edgar", "investor_relations"
    source_url: Mapped[str] = mapped_column(Text)

    # Legal corpus fields (NyayaGraph pivot, 2026-08-19) — all nullable so
    # the finance-domain rows this schema originally served stay untouched.
    # `company`/`ticker` above still hold the finance identifiers; a legal
    # row leaves them blank rather than repurposing them, since "ticker" has
    # no legal-domain analogue and forcing one in would be more confusing
    # than an unused pair of columns.
    court: Mapped[str | None] = mapped_column(String(128), nullable=True)
    case_citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    act_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    authority_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 1=Constitution, 2=Central Act, 3=SC judgment, 4=HC judgment,
    # 5=notification/circular — lower is more authoritative. Used by
    # HybridRetriever to break relevance ties toward primary sources
    # (src/rag/hybrid/retriever.py), never to override genuine relevance.

    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("documents.id"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 hex digest

    raw_object_key: Mapped[str] = mapped_column(Text)  # S3/MinIO key of the untouched original
    raw_content_type: Mapped[str] = mapped_column(String(128), default="text/html")

    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, native_enum=False), default=IngestionStatus.PENDING
    )
    ingested_at: Mapped[datetime | None] = _nullable_timestamp()

    metadata_extra: Mapped[dict[str, object]] = mapped_column(PortableJSON, default=dict)

    created_at: Mapped[datetime] = _created_at()

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document")


class Chunk(Base):
    """Section-aware chunk (docs/04, D-19) — the citation-granularity unit.

    `qdrant_point_id` links this row to its Qdrant point so citation
    provenance and vector search results resolve to the same identity in
    both stores (docs/08's "machine-readable provenance").
    """

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document_index", "document_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[ChunkType] = mapped_column(
        Enum(ChunkType, native_enum=False), default=ChunkType.TEXT
    )

    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)

    # Table-aware chunks (docs/04, D-19) carry structured fields alongside
    # `text` (which holds a linearized rendering for embedding/display).
    table_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    table_headers: Mapped[list[str] | None] = mapped_column(PortableJSON, nullable=True)
    table_rows: Mapped[list[list[str]] | None] = mapped_column(PortableJSON, nullable=True)

    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = _created_at()

    document: Mapped[Document] = relationship(back_populates="chunks")
    evidence_items: Mapped[list[EvidenceItem]] = relationship(back_populates="chunk")


class LegalSection(Base):
    """One section/article of a Constitution or Act (NyayaGraph pivot).

    Gives statutory provisions first-class identity distinct from a generic
    `Chunk`: a section can be the target of a Neo4j citation edge ("Case X
    interprets Section 17") even before/independent of how it happens to be
    chunked for embedding. `chunk_id` links to the chunk actually retrieved
    when this section is the answer, once ingestion has run; nullable
    because the row can exist (from parsing the Act's table of contents)
    before chunking has happened.
    """

    __tablename__ = "legal_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "section_number", name="uq_legal_sections_document_number"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("documents.id"), index=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("chunks.id"), nullable=True
    )

    section_number: Mapped[str] = mapped_column(String(32))  # e.g. "17", "21", "Article 14"
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = _created_at()

    document: Mapped[Document] = relationship()
    chunk: Mapped[Chunk | None] = relationship()


# --------------------------------------------------------------------------
# Research jobs (docs/06 — ResearchState persists via the LangGraph
# checkpointer in V2; this table is the product-level job record the API
# and D-27's research_id/trace_id scheme are built on)
# --------------------------------------------------------------------------


class ResearchJob(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()  # this IS the research_id (D-27)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    query: Mapped[str] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only on JobStatus.FAILED — the research worker crashed (e.g. Ollama
    # unreachable) rather than completing and declaring insufficient evidence.
    # Distinct from `insufficient_evidence`: that is a truthful *answer*,
    # this is the job never producing one.

    progress_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human-readable "what's happening right now" (e.g. "Retrieving passages
    # for sub-question 2/3") — committed on its own short-lived session by
    # the worker (src/graph/tasks.py) as each pipeline stage starts, so a
    # client polling GET /jobs/{id} (or the SSE stream) sees real progress
    # during a run instead of a single opaque "running" for several minutes.

    iteration: Mapped[int] = mapped_column(Integer, default=0)
    max_iterations: Mapped[int] = mapped_column(Integer, default=5)  # D-21
    token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    imputed_cost: Mapped[float] = mapped_column(Float, default=0.0)

    insufficient_evidence: Mapped[bool] = mapped_column(default=False)
    # docs/06: hitting a budget/iteration limit must produce a report that
    # DECLARES insufficiency — this flag is what the report-rendering layer
    # checks, so "ran out of budget" can never silently look like "answered
    # confidently."

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    claims: Mapped[list[Claim]] = relationship(back_populates="job")
    reports: Mapped[list[Report]] = relationship(back_populates="job")


# --------------------------------------------------------------------------
# Evidence chain (docs/08) — built forward, never reconstructed
# --------------------------------------------------------------------------


class EvidenceItem(Base):
    """Passage -> Evidence item (docs/08's second link in the chain)."""

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id"), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("chunks.id"), index=True)

    supporting_passage: Mapped[str] = mapped_column(Text)  # verbatim excerpt, not paraphrase
    summary: Mapped[str] = mapped_column(Text)  # what this passage establishes

    created_at: Mapped[datetime] = _created_at()

    chunk: Mapped[Chunk] = relationship(back_populates="evidence_items")
    claim_links: Mapped[list[ClaimEvidence]] = relationship(back_populates="evidence")


class Claim(Base):
    """Evidence item(s) -> Claim (docs/08's third link)."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id"), index=True)

    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low/medium/high

    created_at: Mapped[datetime] = _created_at()

    job: Mapped[ResearchJob] = relationship(back_populates="claims")
    evidence_links: Mapped[list[ClaimEvidence]] = relationship(back_populates="claim")
    citations: Mapped[list[Citation]] = relationship(back_populates="claim")


class ClaimEvidence(Base):
    """Many-to-many join: a claim may rest on multiple evidence items, and
    (rarely) one evidence item may support multiple claims.
    """

    __tablename__ = "claim_evidence"

    claim_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("claims.id"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence_items.id"), primary_key=True
    )

    claim: Mapped[Claim] = relationship(back_populates="evidence_links")
    evidence: Mapped[EvidenceItem] = relationship(back_populates="claim_links")


class Citation(Base):
    """Claim -> Citation (docs/08's fourth link) — the entailment-gated
    output of the Citation Validator (D-23).
    """

    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("claims.id"), index=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence_items.id"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("documents.id"), index=True)

    status: Mapped[CitationStatus] = mapped_column(Enum(CitationStatus, native_enum=False))
    rewritten_claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str] = mapped_column(Text)  # one-sentence entailment reasoning

    created_at: Mapped[datetime] = _created_at()

    claim: Mapped[Claim] = relationship(back_populates="citations")


class Report(Base):
    """Citation -> Synthesis (docs/08's final link) — the stored report."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.id"), nullable=True, index=True
    )

    draft: Mapped[str | None] = mapped_column(Text, nullable=True)  # pre-Critic
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)  # post-validation
    run_manifest: Mapped[dict[str, object]] = mapped_column(PortableJSON, default=dict)
    # docs/17: the full AI-configuration run manifest is persisted alongside
    # every stored report, so "why did the system say this" stays answerable.

    created_at: Mapped[datetime] = _created_at()

    job: Mapped[ResearchJob] = relationship(back_populates="reports")


# --------------------------------------------------------------------------
# Audit (docs/12 §12 — distinct from tracing; durable, in PostgreSQL)
# --------------------------------------------------------------------------


class AuditLogEntry(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("jobs.id"), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.id"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(255))  # user id, "system", or a node name
    action: Mapped[str] = mapped_column(String(128))  # e.g. "tool_call", "state_transition"
    detail: Mapped[dict[str, object]] = mapped_column(PortableJSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# --------------------------------------------------------------------------
# Ingestion telemetry (docs/04 requirement 5 — "record ingestion status,
# parser errors, embedding model/version, and timestamps")
# --------------------------------------------------------------------------


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(64))  # e.g. "sec_edgar"
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, native_enum=False), default=IngestionRunStatus.RUNNING
    )

    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunking_config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    documents_processed: Mapped[int] = mapped_column(Integer, default=0)
    documents_skipped_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    parser_errors: Mapped[list[dict[str, object]]] = mapped_column(PortableJSON, default=list)

    started_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None] = _nullable_timestamp()
