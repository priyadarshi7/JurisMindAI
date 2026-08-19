"""Unit tests for src.rag.bm25.sparse_encoder — the real fastembed BM25
model (small, cached locally after first download; no live service call at
test time, which is why this lives in tests/unit rather than integration).
"""

from __future__ import annotations

from src.rag.bm25.sparse_encoder import Bm25SparseEncoder


def test_encode_documents_returns_one_vector_per_input() -> None:
    encoder = Bm25SparseEncoder()
    vectors = encoder.encode_documents(
        [
            "NVIDIA reported gross margin compression in Q3.",
            "Item 7A quantitative disclosures for NVDA.",
        ]
    )
    assert len(vectors) == 2
    for v in vectors:
        assert len(v.indices) > 0
        assert len(v.indices) == len(v.values)


def test_encode_documents_empty_list() -> None:
    encoder = Bm25SparseEncoder()
    assert encoder.encode_documents([]) == []


def test_encode_query_returns_one_vector() -> None:
    encoder = Bm25SparseEncoder()
    vector = encoder.encode_query("gross margin compression")
    assert len(vector.indices) > 0
    assert len(vector.indices) == len(vector.values)


def test_same_term_produces_overlapping_indices() -> None:
    """The exact-term-match property hybrid retrieval depends on (docs/05):
    a query sharing a distinctive token with a document should share at
    least one sparse index with it.
    """
    encoder = Bm25SparseEncoder()
    doc_vector = encoder.encode_documents(["Item 7A quantitative disclosures for NVDA."])[0]
    query_vector = encoder.encode_query("NVDA Item 7A disclosures")

    assert set(doc_vector.indices) & set(query_vector.indices)


def test_indices_fit_qdrant_sparse_vector_range() -> None:
    """Qdrant sparse vector indices are unsigned 32-bit integers — the
    murmurhash-based term ids fastembed produces must fit that range.
    """
    encoder = Bm25SparseEncoder()
    vector = encoder.encode_query("revenue growth and cost of goods sold")
    assert all(0 <= i < 2**32 for i in vector.indices)
