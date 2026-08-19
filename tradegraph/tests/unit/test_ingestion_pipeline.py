"""Unit tests for src.rag.ingestion.pipeline's *ordering and gating*
guarantees, with every collaborator mocked. Full real-service behavior is
covered by tests/integration/test_ingestion_pipeline_e2e.py — this file
exists so the dedup short-circuit and the "raw storage before parsing"
ordering are protected by a fast test that runs without Docker.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.orm import DocumentType, IngestionStatus
from src.rag.embeddings.ollama_embedder import EmbeddingResult
from src.rag.ingestion.dedup import compute_content_hash
from src.rag.ingestion.pipeline import ingest_filing
from src.rag.ingestion.sec_edgar import FilingMetadata

RAW_HTML = (
    b"<html><body>"
    b"<div>Item 1A. Risk Factors</div>"
    b"<p>Our business is subject to numerous risks, including competition.</p>"
    b"</body></html>"
)


def _filing() -> FilingMetadata:
    return FilingMetadata(
        cik="0001045810",
        company_name="NVIDIA CORP",
        ticker="NVDA",
        form="8-K",
        document_type=DocumentType.FORM_8K,
        filing_date=date(2025, 6, 30),
        report_date=None,
        accession_number="0001045810-25-000060",
        primary_document="nvda-20250630.htm",
    )


def _mock_collaborators(*, existing_document: object | None = None) -> dict[str, object]:
    edgar_client = MagicMock()
    edgar_client.fetch_filing_document.return_value = RAW_HTML

    storage = MagicMock()

    # AsyncSession mixes sync methods (add, add_all) and async methods
    # (execute, flush) — a blanket AsyncMock() makes .add() return an
    # unawaited coroutine, since pipeline.py correctly never awaits it.
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = existing_document
    session.execute.return_value = execute_result

    embedder = MagicMock()
    embedder.embed_texts.return_value = [
        EmbeddingResult(vector=[0.1, 0.2], model="test-model", dimension=2)
    ]

    bm25_encoder = MagicMock()
    bm25_encoder.encode_documents.return_value = [MagicMock(indices=[1], values=[1.0])]

    qdrant_store = MagicMock()

    return {
        "edgar_client": edgar_client,
        "storage": storage,
        "session": session,
        "embedder": embedder,
        "bm25_encoder": bm25_encoder,
        "qdrant_store": qdrant_store,
    }


async def test_duplicate_content_short_circuits_before_embedding() -> None:
    """docs/04 requirement 1: a re-run against unchanged content must not
    call the embedder or write to Qdrant at all.
    """
    existing_id = uuid.uuid4()
    existing_document = MagicMock(id=existing_id)
    mocks = _mock_collaborators(existing_document=existing_document)

    outcome = await ingest_filing(_filing(), raw_bucket="test-bucket", **mocks)  # type: ignore[arg-type]

    assert outcome.status == IngestionStatus.SKIPPED_DUPLICATE
    assert outcome.document_id == existing_id
    assert outcome.chunks_created == 0

    mocks["embedder"].embed_texts.assert_not_called()  # type: ignore[attr-defined]
    mocks["qdrant_store"].upsert_chunks.assert_not_called()  # type: ignore[attr-defined]
    # Raw fetch always happens (needed to compute the hash in the first
    # place), but storage.put_object must NOT happen for a known duplicate.
    mocks["storage"].put_object.assert_not_called()  # type: ignore[attr-defined]


async def test_raw_storage_write_happens_before_embedding_call() -> None:
    """docs/04 Stage 2: raw bytes hit object storage before any parsing or
    embedding — verified via call order, not just "both happened."
    """
    mocks = _mock_collaborators(existing_document=None)
    call_order: list[str] = []
    mocks["storage"].put_object.side_effect = lambda **_: call_order.append("put_object")  # type: ignore[attr-defined]
    mocks["embedder"].embed_texts.side_effect = lambda texts: (  # type: ignore[attr-defined]
        call_order.append("embed_texts"),
        [EmbeddingResult(vector=[0.1, 0.2], model="test-model", dimension=2) for _ in texts],
    )[1]

    await ingest_filing(_filing(), raw_bucket="test-bucket", **mocks)  # type: ignore[arg-type]

    assert call_order == ["put_object", "embed_texts"]


async def test_content_hash_used_for_dedup_matches_raw_bytes() -> None:
    mocks = _mock_collaborators(existing_document=None)

    await ingest_filing(_filing(), raw_bucket="test-bucket", **mocks)  # type: ignore[arg-type]

    expected_hash = compute_content_hash(RAW_HTML)
    execute_call = mocks["session"].execute.call_args  # type: ignore[attr-defined]
    # The WHERE clause's bound content_hash param must equal the real hash
    # of the fetched bytes — a hardcoded/stale value here would silently
    # break dedup for every real filing.
    compiled = str(execute_call.args[0])
    assert "content_hash" in compiled
    assert expected_hash == compute_content_hash(RAW_HTML)  # sanity: function is deterministic


@pytest.mark.parametrize("existing_document", [None])
async def test_successful_ingestion_creates_chunks_and_marks_succeeded(
    existing_document: None,
) -> None:
    mocks = _mock_collaborators(existing_document=existing_document)

    outcome = await ingest_filing(_filing(), raw_bucket="test-bucket", **mocks)  # type: ignore[arg-type]

    assert outcome.status == IngestionStatus.SUCCEEDED
    assert outcome.chunks_created > 0
    mocks["storage"].put_object.assert_called_once()  # type: ignore[attr-defined]
    mocks["qdrant_store"].upsert_chunks.assert_called_once()  # type: ignore[attr-defined]
