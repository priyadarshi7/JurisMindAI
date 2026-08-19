"""Unit tests for src.rag.vector.qdrant_store against Qdrant's in-memory
mode (`location=":memory:"`) — no server required, real Qdrant behavior.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from qdrant_client import QdrantClient

from src.rag.vector.qdrant_store import ChunkPoint, QdrantStore, build_metadata_filter

DENSE_DIM = 4


def _uuid(name: str) -> str:
    """Real Qdrant point ids must be an unsigned int or a UUID — in the
    real pipeline this is `Chunk.id` from PostgreSQL. Deterministic per
    `name` so test assertions can still refer to readable labels.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


@pytest.fixture
def store() -> Iterator[QdrantStore]:
    client = QdrantClient(location=":memory:")
    s = QdrantStore(client, collection_name="test_chunks")
    s.ensure_collection(dense_dimension=DENSE_DIM)
    yield s


def _chunk(
    point_name: str, dense: list[float], sparse_indices: list[int], **payload: object
) -> ChunkPoint:
    return ChunkPoint(
        point_id=_uuid(point_name),
        dense_vector=dense,
        sparse_indices=sparse_indices,
        sparse_values=[1.0] * len(sparse_indices),
        payload=payload,
    )


def test_ensure_collection_is_idempotent(store: QdrantStore) -> None:
    store.ensure_collection(dense_dimension=DENSE_DIM)  # must not raise


def test_upsert_and_dense_search(store: QdrantStore) -> None:
    store.upsert_chunks(
        [
            _chunk("1", [1.0, 0.0, 0.0, 0.0], [10, 20], company="NVIDIA"),
            _chunk("2", [0.0, 1.0, 0.0, 0.0], [30, 40], company="Apple"),
        ]
    )

    results = store.search_dense([1.0, 0.0, 0.0, 0.0], query_filter=None, limit=5)
    assert results[0].point_id == _uuid("1")
    assert results[0].payload["company"] == "NVIDIA"


def test_upsert_and_sparse_search(store: QdrantStore) -> None:
    store.upsert_chunks(
        [
            _chunk("1", [1.0, 0.0, 0.0, 0.0], [10, 20], company="NVIDIA"),
            _chunk("2", [0.0, 1.0, 0.0, 0.0], [30, 40], company="Apple"),
        ]
    )

    results = store.search_sparse(indices=[10, 20], values=[1.0, 1.0], query_filter=None, limit=5)
    assert results[0].point_id == _uuid("1")


def test_metadata_filter_applies_to_dense_search(store: QdrantStore) -> None:
    store.upsert_chunks(
        [
            _chunk("1", [1.0, 0.0, 0.0, 0.0], [10], company="NVIDIA", ticker="NVDA"),
            _chunk("2", [1.0, 0.0, 0.0, 0.0], [10], company="Apple", ticker="AAPL"),
        ]
    )

    query_filter = build_metadata_filter(ticker="AAPL")
    results = store.search_dense([1.0, 0.0, 0.0, 0.0], query_filter=query_filter, limit=5)

    assert len(results) == 1
    assert results[0].payload["ticker"] == "AAPL"


def test_metadata_filter_applies_identically_to_sparse_search(store: QdrantStore) -> None:
    """D-3's correctness constraint: the same filter construction must
    exclude the same points from both arms.
    """
    store.upsert_chunks(
        [
            _chunk("1", [1.0, 0.0, 0.0, 0.0], [10], company="NVIDIA", ticker="NVDA"),
            _chunk("2", [1.0, 0.0, 0.0, 0.0], [10], company="Apple", ticker="AAPL"),
        ]
    )

    query_filter = build_metadata_filter(ticker="AAPL")
    results = store.search_sparse(indices=[10], values=[1.0], query_filter=query_filter, limit=5)

    assert len(results) == 1
    assert results[0].payload["ticker"] == "AAPL"


def test_filing_date_range_filter(store: QdrantStore) -> None:
    store.upsert_chunks(
        [
            _chunk(
                "old",
                [1.0, 0.0, 0.0, 0.0],
                [10],
                filing_date_ts=date(2020, 1, 1).toordinal(),
            ),
            _chunk(
                "new",
                [1.0, 0.0, 0.0, 0.0],
                [10],
                filing_date_ts=date(2025, 1, 1).toordinal(),
            ),
        ]
    )

    query_filter = build_metadata_filter(filing_date_from=date(2024, 1, 1))
    results = store.search_dense([1.0, 0.0, 0.0, 0.0], query_filter=query_filter, limit=5)

    assert {r.point_id for r in results} == {_uuid("new")}


def test_build_metadata_filter_returns_none_when_no_constraints() -> None:
    assert build_metadata_filter() is None
