"""Ingestion pipeline orchestration (docs/04 Flow A, docs/16 Phase 1).

Ties every Phase 1 module into the one ordering docs/01 Flow A specifies:

    adapter -> raw object storage -> content-hash gate -> parse ->
    version -> chunk -> embed -> index (Qdrant + PostgreSQL) -> telemetry

Each stage is independently testable (see the other src/rag/* modules'
tests); this module's own tests cover the *ordering* and *gating*
guarantees — the raw bytes hit object storage before anything else
happens to them, duplicate content short-circuits before any embedding
call, and a document row only reaches `succeeded` after its chunks are
indexed in both stores.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.data.object_storage import ObjectStorageClient, build_raw_document_key
from src.models.orm import Chunk, ChunkType, Document, IngestionRunStatus, IngestionStatus
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.chunking.chunker import CHUNKING_CONFIG_VERSION, TableChunk, chunk_document
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.ingestion.dedup import ExistingVersion, compute_content_hash, determine_version
from src.rag.ingestion.parser import parse_filing_html
from src.rag.ingestion.sec_edgar import FilingMetadata, SecEdgarClient
from src.rag.vector.qdrant_store import ChunkPoint, QdrantStore


class PipelineError(Exception):
    pass


@dataclass(frozen=True)
class IngestionOutcome:
    document_id: uuid.UUID
    status: IngestionStatus
    chunks_created: int


async def ingest_filing(
    filing: FilingMetadata,
    *,
    edgar_client: SecEdgarClient,
    storage: ObjectStorageClient,
    session: AsyncSession,
    embedder: OllamaEmbedder,
    bm25_encoder: Bm25SparseEncoder,
    qdrant_store: QdrantStore,
    raw_bucket: str,
    tenant_id: uuid.UUID | None = None,
) -> IngestionOutcome:
    """Ingest one filing end to end. Idempotent: re-running against
    unchanged content is a no-op that returns `SKIPPED_DUPLICATE` without
    calling the embedder or writing to Qdrant (docs/04 requirement 1).
    """
    raw_bytes = edgar_client.fetch_filing_document(filing.document_url)
    content_hash = compute_content_hash(raw_bytes)

    existing = (
        await session.execute(select(Document).where(Document.content_hash == content_hash))
    ).scalar_one_or_none()
    if existing is not None:
        return IngestionOutcome(
            document_id=existing.id, status=IngestionStatus.SKIPPED_DUPLICATE, chunks_created=0
        )

    # ❗ Raw bytes go to object storage BEFORE any parsing (docs/04 Stage 2)
    # — untouched, so any parse can be re-derived and audited later.
    extension = (
        filing.primary_document.rsplit(".", 1)[-1] if "." in filing.primary_document else "htm"
    )
    raw_key = build_raw_document_key(
        source="sec_edgar",
        ticker=filing.ticker,
        document_type=filing.document_type.value,
        content_hash=content_hash,
        extension=extension,
    )
    storage.put_object(bucket=raw_bucket, key=raw_key, body=raw_bytes, content_type="text/html")

    prior_versions = await _existing_versions(
        session,
        ticker=filing.ticker,
        document_type=filing.document_type,
        filing_date=filing.filing_date,
    )
    version_decision = determine_version(prior_versions)

    parsed = parse_filing_html(raw_bytes)

    document = Document(
        tenant_id=tenant_id,
        company=filing.company_name,
        ticker=filing.ticker,
        document_type=filing.document_type,
        filing_date=datetime.combine(filing.filing_date, datetime.min.time(), tzinfo=UTC),
        source="sec_edgar",
        source_url=filing.document_url,
        version=version_decision.version,
        supersedes_id=version_decision.supersedes_id,
        content_hash=content_hash,
        raw_object_key=raw_key,
        raw_content_type="text/html",
        ingestion_status=IngestionStatus.PENDING,
    )
    session.add(document)
    await session.flush()  # assigns document.id

    chunks = chunk_document(parsed)
    if chunks:
        texts = [c.text for c in chunks]
        embeddings = embedder.embed_texts(texts)
        sparse_vectors = bm25_encoder.encode_documents(texts)

        chunk_rows: list[Chunk] = []
        qdrant_points: list[ChunkPoint] = []
        for chunk, embedding, sparse in zip(chunks, embeddings, sparse_vectors, strict=True):
            chunk_id = uuid.uuid4()

            if isinstance(chunk, TableChunk):
                table_title, table_headers, table_rows = chunk.title, chunk.headers, chunk.rows
            else:
                table_title, table_headers, table_rows = None, None, None

            chunk_rows.append(
                Chunk(
                    id=chunk_id,
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    chunk_type=ChunkType(chunk.chunk_type),
                    section=chunk.section,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    table_title=table_title,
                    table_headers=table_headers,
                    table_rows=table_rows,
                    embedding_model=embedding.model,
                    embedding_dimension=embedding.dimension,
                    qdrant_point_id=str(chunk_id),
                )
            )
            qdrant_points.append(
                ChunkPoint(
                    point_id=str(chunk_id),
                    dense_vector=embedding.vector,
                    sparse_indices=sparse.indices,
                    sparse_values=sparse.values,
                    payload={
                        "company": document.company,
                        "ticker": document.ticker,
                        "document_type": document.document_type.value,
                        "filing_date_ts": filing.filing_date.toordinal(),
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "document_id": str(document.id),
                        # ❗ chunk_id + text: without these, a retrieval hit
                        # carries only where a passage came from, not the
                        # passage itself — the Evidence Extractor node has
                        # nothing to extract from. Denormalized here
                        # deliberately, so retrieval never needs a
                        # round-trip to PostgreSQL just to read text back.
                        "chunk_id": str(chunk_id),
                        "text": chunk.text,
                        "section": chunk.section,
                        "chunk_type": chunk.chunk_type,
                    },
                )
            )

        session.add_all(chunk_rows)
        # Qdrant write happens before the PostgreSQL commit below is durable
        # in the caller's transaction, but after `session.flush()` above —
        # if this raises, the caller's rollback removes the document/chunk
        # rows and the ingestion run is retried from a clean slate next time
        # (content-hash gate makes the retry a no-op for the object-storage
        # write, which already succeeded).
        qdrant_store.upsert_chunks(qdrant_points)

    document.ingestion_status = IngestionStatus.SUCCEEDED
    document.ingested_at = datetime.now(UTC)

    return IngestionOutcome(
        document_id=document.id,
        status=IngestionStatus.SUCCEEDED,
        chunks_created=len(chunks),
    )


async def _existing_versions(
    session: AsyncSession, *, ticker: str, document_type: object, filing_date: object
) -> list[ExistingVersion]:
    rows = (
        await session.execute(
            select(Document).where(
                Document.ticker == ticker,
                Document.document_type == document_type,
                Document.filing_date
                == datetime.combine(filing_date, datetime.min.time(), tzinfo=UTC),  # type: ignore[arg-type]
            )
        )
    ).scalars()
    return [
        ExistingVersion(document_id=row.id, version=row.version, content_hash=row.content_hash)
        for row in rows
    ]


def default_raw_bucket() -> str:
    return get_settings().s3_bucket_raw_documents


__all__ = [
    "CHUNKING_CONFIG_VERSION",
    "IngestionOutcome",
    "IngestionRunStatus",
    "PipelineError",
    "default_raw_bucket",
    "ingest_filing",
]
