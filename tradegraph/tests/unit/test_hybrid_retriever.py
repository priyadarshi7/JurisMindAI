"""Unit tests for src.rag.hybrid.retriever — real Qdrant (in-memory), real
BM25 encoder, Ollama mocked via respx (no live model server needed).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest
import respx
from qdrant_client import QdrantClient

from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.hybrid.retriever import HybridRetriever
from src.rag.reranking.reranker_client import RerankedPassage
from src.rag.vector.qdrant_store import ChunkPoint, QdrantStore, build_metadata_filter

OLLAMA_BASE_URL = "http://fake-ollama:11434"
DENSE_DIM = 4


def _uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


@pytest.fixture
def store() -> QdrantStore:
    client = QdrantClient(location=":memory:")
    s = QdrantStore(client, collection_name="test_hybrid")
    s.ensure_collection(dense_dimension=DENSE_DIM)
    return s


@pytest.fixture
def bm25_encoder() -> Bm25SparseEncoder:
    return Bm25SparseEncoder()


@pytest.fixture
def embedder() -> Iterator[OllamaEmbedder]:
    with OllamaEmbedder(
        base_url=OLLAMA_BASE_URL, model="qwen3-embedding-0.6b", expected_dimension=DENSE_DIM
    ) as e:
        yield e


def _seed(store: QdrantStore, bm25: Bm25SparseEncoder) -> None:
    docs = {
        "nvda_margin": (
            "nvda_margin",
            [1.0, 0.0, 0.0, 0.0],
            "Gross margin compression was driven by higher cost of revenue.",
            "NVDA",
        ),
        "aapl_unrelated": (
            "aapl_unrelated",
            [0.0, 1.0, 0.0, 0.0],
            "Services revenue grew due to App Store performance.",
            "AAPL",
        ),
    }
    sparse_vectors = {
        name: bm25.encode_documents([text])[0] for name, (_, _, text, _) in docs.items()
    }

    chunks = [
        ChunkPoint(
            point_id=_uuid(name),
            dense_vector=dense,
            sparse_indices=sparse_vectors[name].indices,
            sparse_values=sparse_vectors[name].values,
            payload={"ticker": ticker, "text": text},
        )
        for name, (_, dense, text, ticker) in docs.items()
    ]
    store.upsert_chunks(chunks)


@respx.mock
def test_hybrid_search_returns_fused_results(
    store: QdrantStore, bm25_encoder: Bm25SparseEncoder, embedder: OllamaEmbedder
) -> None:
    _seed(store, bm25_encoder)

    respx.post(f"{OLLAMA_BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0, 0.0]]})
    )

    retriever = HybridRetriever(store=store, embedder=embedder, sparse_encoder=bm25_encoder)
    results = retriever.search(
        "gross margin compression cost of revenue", query_filter=None, top_n=5
    )

    assert results
    assert results[0].point_id == _uuid("nvda_margin")


@respx.mock
def test_hybrid_search_respects_metadata_filter(
    store: QdrantStore, bm25_encoder: Bm25SparseEncoder, embedder: OllamaEmbedder
) -> None:
    """D-3: the same filter must exclude the same points from both arms —
    here, filtering to AAPL must exclude the NVDA point even though it is
    the best dense+sparse match for the query.
    """
    _seed(store, bm25_encoder)

    respx.post(f"{OLLAMA_BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0, 0.0]]})
    )

    retriever = HybridRetriever(store=store, embedder=embedder, sparse_encoder=bm25_encoder)
    query_filter = build_metadata_filter(ticker="AAPL")
    results = retriever.search(
        "gross margin compression cost of revenue", query_filter=query_filter, top_n=5
    )

    point_ids = {r.point_id for r in results}
    assert _uuid("nvda_margin") not in point_ids


@respx.mock
def test_hybrid_search_top_n_truncates(
    store: QdrantStore, bm25_encoder: Bm25SparseEncoder, embedder: OllamaEmbedder
) -> None:
    _seed(store, bm25_encoder)
    respx.post(f"{OLLAMA_BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0, 0.0]]})
    )

    retriever = HybridRetriever(store=store, embedder=embedder, sparse_encoder=bm25_encoder)
    results = retriever.search("margin", query_filter=None, top_n=1)
    assert len(results) == 1


class _FakeReranker:
    """Stands in for RerankerClient — returns a caller-scripted order rather
    than actually scoring, so a test can prove `search()` defers to the
    reranker's ordering instead of raw RRF score.
    """

    def __init__(self, order: list[int]) -> None:
        self._order = order

    def rerank(self, *, query: str, passages: list[str], top_n: int) -> list[RerankedPassage]:
        return [
            RerankedPassage(index=i, score=1.0 - position * 0.1)
            for position, i in enumerate(self._order[:top_n])
        ]


@respx.mock
def test_hybrid_search_uses_reranker_to_reorder_candidates(
    store: QdrantStore, bm25_encoder: Bm25SparseEncoder, embedder: OllamaEmbedder
) -> None:
    """Without reranking (test_hybrid_search_returns_fused_results above),
    nvda_margin ranks first by raw RRF score for this query. A reranker
    that says otherwise must be the one that wins — this is the entire
    point of reranking (docs/16, found live 2026-08-17: RRF score alone
    put a real answer at fused rank ~22-41).
    """
    _seed(store, bm25_encoder)
    respx.post(f"{OLLAMA_BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0, 0.0]]})
    )

    reranker = _FakeReranker(order=[1, 0])  # reverse RRF order
    retriever = HybridRetriever(
        store=store, embedder=embedder, sparse_encoder=bm25_encoder, reranker=reranker
    )
    results = retriever.search(
        "gross margin compression cost of revenue", query_filter=None, top_n=2
    )

    assert results[0].point_id == _uuid("aapl_unrelated")
    assert results[1].point_id == _uuid("nvda_margin")


@respx.mock
def test_hybrid_search_no_reranker_falls_back_to_rrf_order(
    store: QdrantStore, bm25_encoder: Bm25SparseEncoder, embedder: OllamaEmbedder
) -> None:
    """Default behavior (reranker=None) must be unchanged — every existing
    call site that doesn't pass a reranker keeps working exactly as before.
    """
    _seed(store, bm25_encoder)
    respx.post(f"{OLLAMA_BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0, 0.0]]})
    )

    retriever = HybridRetriever(store=store, embedder=embedder, sparse_encoder=bm25_encoder)
    results = retriever.search(
        "gross margin compression cost of revenue", query_filter=None, top_n=2
    )

    assert results[0].point_id == _uuid("nvda_margin")
