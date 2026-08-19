"""End-to-end integration test: the full Phase 1 ingestion pipeline against
every real service — SEC EDGAR (live network), PostgreSQL, MinIO, Qdrant,
and Ollama serving the real Qwen3-Embedding model. No mocks, no stubs.

This is the strongest verification available for docs/16 Phase 1's exit
criterion ("a cited financial research report works end-to-end") on the
ingestion half of that pipeline: a real NVIDIA 8-K goes in, real vectors
come out, and they are retrievable by real hybrid search.

Requires: `docker compose up -d postgres minio qdrant ollama`,
`ollama pull qwen3-embedding:0.6b`, `alembic upgrade head`, and a `.env`
with working local credentials for all four services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.config import get_settings
from src.data.object_storage import ObjectStorageClient
from src.models.orm import Chunk, Document, IngestionStatus
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.hybrid.retriever import HybridRetriever
from src.rag.ingestion.pipeline import ingest_filing
from src.rag.ingestion.sec_edgar import SecEdgarClient
from src.rag.vector.qdrant_store import QdrantStore, build_metadata_filter


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
        await s.rollback()  # never persist test ingestion data
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

    # Unlike the PostgreSQL session (rolled back by the `session` fixture),
    # Qdrant writes in this test are real and permanent. Without a reset,
    # repeated runs accumulate duplicate chunks from the same filing in the
    # collection, which can crowd the newly-ingested document out of a
    # small top_n and make the final retrieval assertion flaky. Start every
    # run from an empty collection instead.
    if settings.qdrant_collection_name in {c.name for c in client.get_collections().collections}:
        client.delete_collection(settings.qdrant_collection_name)

    store = QdrantStore(client, collection_name=settings.qdrant_collection_name)
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
        pytest.skip(f"Ollama not reachable: {exc}")
    return e


@pytest.fixture
def bm25_encoder() -> Bm25SparseEncoder:
    return Bm25SparseEncoder()


@pytest.fixture
def edgar_client() -> SecEdgarClient:
    return SecEdgarClient(user_agent="TradeGraph-Test research@example.com")


async def test_ingest_real_nvda_filing_end_to_end(
    session: AsyncSession,
    storage: ObjectStorageClient,
    qdrant_store: QdrantStore,
    embedder: OllamaEmbedder,
    bm25_encoder: Bm25SparseEncoder,
    edgar_client: SecEdgarClient,
) -> None:
    settings = get_settings()

    try:
        # 8-K, not 10-K: smallest of the three V1 document types, keeps
        # this test's embedding-call volume (and runtime) reasonable.
        filings = edgar_client.list_filings("NVDA", forms=frozenset({"8-K"}))
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")

    assert filings, "expected at least one recent NVDA 8-K"
    filing = max(filings, key=lambda f: f.filing_date)

    outcome = await ingest_filing(
        filing,
        edgar_client=edgar_client,
        storage=storage,
        session=session,
        embedder=embedder,
        bm25_encoder=bm25_encoder,
        qdrant_store=qdrant_store,
        raw_bucket=settings.s3_bucket_raw_documents,
    )

    assert outcome.status == IngestionStatus.SUCCEEDED
    assert outcome.chunks_created > 0

    # 1. PostgreSQL: the document and its chunks are really there.
    document = await session.get(Document, outcome.document_id)
    assert document is not None
    assert document.ticker == "NVDA"
    assert document.content_hash

    chunk_rows = (
        (await session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert len(chunk_rows) == outcome.chunks_created
    assert all(c.qdrant_point_id for c in chunk_rows)

    # 2. Object storage: the untouched raw filing is really there.
    assert storage.object_exists(
        bucket=settings.s3_bucket_raw_documents, key=document.raw_object_key
    )
    raw_bytes = storage.get_object(
        bucket=settings.s3_bucket_raw_documents, key=document.raw_object_key
    )
    assert len(raw_bytes) > 100

    # 3. Re-ingesting the same filing is a real no-op (docs/04 requirement 1)
    #    — no new embedding calls, no new Qdrant points, same document id.
    repeat_outcome = await ingest_filing(
        filing,
        edgar_client=edgar_client,
        storage=storage,
        session=session,
        embedder=embedder,
        bm25_encoder=bm25_encoder,
        qdrant_store=qdrant_store,
        raw_bucket=settings.s3_bucket_raw_documents,
    )
    assert repeat_outcome.status == IngestionStatus.SKIPPED_DUPLICATE
    assert repeat_outcome.document_id == outcome.document_id

    # 4. Retrieval: the ingested chunk is actually findable by real hybrid
    #    search, filtered to this ticker — the same filter path D-3 requires
    #    for both arms.
    retriever = HybridRetriever(store=qdrant_store, embedder=embedder, sparse_encoder=bm25_encoder)
    query_filter = build_metadata_filter(ticker="NVDA")
    results = retriever.search("NVIDIA", query_filter=query_filter, top_n=5)

    assert results
    result_document_ids = {r.payload.get("document_id") for r in results}
    assert str(document.id) in result_document_ids
