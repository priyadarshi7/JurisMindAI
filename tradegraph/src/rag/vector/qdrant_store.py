"""Qdrant vector store — dense + native sparse (BM25) in one collection
(docs/15 D-3, resolved 🔒).

One collection, two named vectors (`dense`, `bm25`), one metadata filter
language. That is the entire justification for D-3: dense and sparse
retrieval share the same datastore, so applying the *same* `Filter` object
to both arms — which `build_metadata_filter` exists to make the only way
to build one — makes filter parity structural rather than a thing to
maintain by discipline across two systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Range,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from src.core.config import get_settings

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"

_FILTERABLE_PAYLOAD_FIELDS: dict[str, PayloadSchemaType] = {
    "company": PayloadSchemaType.KEYWORD,
    "ticker": PayloadSchemaType.KEYWORD,
    "document_type": PayloadSchemaType.KEYWORD,
    "tenant_id": PayloadSchemaType.KEYWORD,
    "filing_date_ts": PayloadSchemaType.INTEGER,
}


@dataclass(frozen=True)
class ChunkPoint:
    """One chunk, ready to upsert — dense + sparse vectors and the payload
    fields that `build_metadata_filter` can filter on.
    """

    point_id: str
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    payload: dict[str, object]


@dataclass(frozen=True)
class ScoredPoint:
    point_id: str
    score: float
    payload: dict[str, object]


class QdrantStore:
    def __init__(self, client: QdrantClient, *, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    def ensure_collection(self, *, dense_dimension: int) -> None:
        """Idempotent collection + payload-index creation.

        ❗ `dense_dimension` must be the pinned Qwen3-Embedding output
        dimension (docs/15 D-2) — changing it after data exists requires a
        full re-embed, not a schema migration.
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection_name not in existing:
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(size=dense_dimension, distance=Distance.COSINE)
                },
                sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams()},
            )

        for field_name, schema in _FILTERABLE_PAYLOAD_FIELDS.items():
            self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=schema,
            )

    def upsert_chunks(self, chunks: list[ChunkPoint]) -> None:
        points = [
            PointStruct(
                id=chunk.point_id,
                vector={
                    DENSE_VECTOR_NAME: chunk.dense_vector,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=chunk.sparse_indices, values=chunk.sparse_values
                    ),
                },
                payload=chunk.payload,
            )
            for chunk in chunks
        ]
        self._client.upsert(collection_name=self._collection_name, points=points)

    def search_dense(
        self, query_vector: list[float], *, query_filter: Filter | None, limit: int
    ) -> list[ScoredPoint]:
        result = self._client.query_points(
            self._collection_name,
            using=DENSE_VECTOR_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [_to_scored_point(p) for p in result.points]

    def search_sparse(
        self,
        *,
        indices: list[int],
        values: list[float],
        query_filter: Filter | None,
        limit: int,
    ) -> list[ScoredPoint]:
        result = self._client.query_points(
            self._collection_name,
            using=SPARSE_VECTOR_NAME,
            query=SparseVector(indices=indices, values=values),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [_to_scored_point(p) for p in result.points]


def _to_scored_point(point: object) -> ScoredPoint:
    return ScoredPoint(
        point_id=str(point.id),  # type: ignore[attr-defined]
        score=float(point.score),  # type: ignore[attr-defined]
        payload=dict(point.payload or {}),  # type: ignore[attr-defined]
    )


def build_metadata_filter(
    *,
    company: str | None = None,
    ticker: str | None = None,
    document_type: str | None = None,
    tenant_id: str | None = None,
    filing_date_from: date | None = None,
    filing_date_to: date | None = None,
) -> Filter | None:
    """The single filter-construction path for both dense and sparse
    queries (docs/05: metadata constraints applied identically **before**
    both retrieval arms). There is deliberately no separate filter builder
    for the sparse arm — using this function for both is what makes D-3's
    filter-parity guarantee real rather than aspirational.
    """
    conditions: list[FieldCondition] = []

    if company is not None:
        conditions.append(FieldCondition(key="company", match=MatchValue(value=company)))
    if ticker is not None:
        conditions.append(FieldCondition(key="ticker", match=MatchValue(value=ticker)))
    if document_type is not None:
        conditions.append(
            FieldCondition(key="document_type", match=MatchValue(value=document_type))
        )
    if tenant_id is not None:
        conditions.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))
    if filing_date_from is not None or filing_date_to is not None:
        conditions.append(
            FieldCondition(
                key="filing_date_ts",
                range=Range(
                    gte=_date_to_ts(filing_date_from) if filing_date_from else None,
                    lte=_date_to_ts(filing_date_to) if filing_date_to else None,
                ),
            )
        )

    if not conditions:
        return None
    return Filter(must=conditions)


def _date_to_ts(d: date) -> int:
    """Integer day-ordinal — sortable, filterable, and avoids timezone
    ambiguity in a Qdrant integer range filter.
    """
    return d.toordinal()


@lru_cache
def get_qdrant_store() -> QdrantStore:
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return QdrantStore(client, collection_name=settings.qdrant_collection_name)
