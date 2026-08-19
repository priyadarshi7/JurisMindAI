"""BM25 sparse vector encoding via fastembed (docs/15 D-3, resolved 🔒).

Qdrant's native sparse vectors need something to *produce* a sparse vector
— fastembed's `Qdrant/bm25` model does that: real BM25 term weighting
(length-normalized document term frequencies, IDF-like query weighting),
emitting `(indices, values)` pairs shaped for Qdrant's sparse vector type
directly. This is the "Qdrant native sparse vectors" implementation D-3
resolved to, not a from-scratch BM25 implementation and not `rank_bm25`
(explicitly ruled out).

Documents and queries are encoded asymmetrically on purpose — real BM25
treats them differently (document term weights are length-normalized;
query term weights are not), and fastembed exposes that as two methods
rather than one.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from fastembed import SparseTextEmbedding

BM25_MODEL_NAME = "Qdrant/bm25"


@dataclass(frozen=True)
class SparseVectorData:
    indices: list[int]
    values: list[float]


class Bm25SparseEncoder:
    def __init__(self, *, model_name: str = BM25_MODEL_NAME) -> None:
        self._model = SparseTextEmbedding(model_name=model_name)

    def encode_documents(self, texts: list[str]) -> list[SparseVectorData]:
        if not texts:
            return []
        embeddings = list(self._model.passage_embed(texts))
        return [_to_sparse_vector_data(e) for e in embeddings]

    def encode_query(self, text: str) -> SparseVectorData:
        embeddings = list(self._model.query_embed([text]))
        return _to_sparse_vector_data(embeddings[0])


def _to_sparse_vector_data(embedding: object) -> SparseVectorData:
    return SparseVectorData(
        indices=[int(i) for i in embedding.indices],  # type: ignore[attr-defined]
        values=[float(v) for v in embedding.values],  # type: ignore[attr-defined]
    )


@lru_cache
def get_bm25_encoder() -> Bm25SparseEncoder:
    return Bm25SparseEncoder()
