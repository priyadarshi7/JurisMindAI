"""Integration test: the embedding client against a real Ollama instance
serving the real Qwen3-Embedding model (`docker compose up -d ollama` +
`ollama pull qwen3-embedding:0.6b`) — not mocked.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from src.rag.embeddings.ollama_embedder import OllamaEmbedder

REAL_MODEL = "qwen3-embedding:0.6b"
REAL_DIMENSION = 1024  # docs/15 D-2 pinned value; confirmed against the live model


@pytest.fixture
def embedder() -> Iterator[OllamaEmbedder]:
    e = OllamaEmbedder(
        base_url="http://localhost:11434",
        model=REAL_MODEL,
        expected_dimension=REAL_DIMENSION,
    )
    try:
        e.embed_query("healthcheck")
    except httpx.HTTPError as exc:
        pytest.skip(f"Ollama / {REAL_MODEL} not available: {exc}")
    yield e
    e.close()


def test_embed_query_against_real_model(embedder: OllamaEmbedder) -> None:
    result = embedder.embed_query("gross margin compression")
    assert len(result.vector) == REAL_DIMENSION
    assert result.model == REAL_MODEL
    assert any(v != 0.0 for v in result.vector)


def test_semantically_similar_queries_are_closer_than_dissimilar_ones(
    embedder: OllamaEmbedder,
) -> None:
    """The actual reason a dense embedder is in the stack (docs/02):
    paraphrase recall. Verified against the real model, not asserted.
    """
    a = embedder.embed_query("gross margin declined due to higher costs")
    b = embedder.embed_query("margin compression from increased cost of revenue")
    c = embedder.embed_query("the quarterly board meeting was rescheduled")

    def cosine(x: list[float], y: list[float]) -> float:
        dot = sum(xi * yi for xi, yi in zip(x, y, strict=True))
        norm_x = sum(xi * xi for xi in x) ** 0.5
        norm_y = sum(yi * yi for yi in y) ** 0.5
        return dot / (norm_x * norm_y)

    sim_related = cosine(a.vector, b.vector)
    sim_unrelated = cosine(a.vector, c.vector)

    assert sim_related > sim_unrelated


def test_embed_texts_batch_against_real_model(embedder: OllamaEmbedder) -> None:
    results = embedder.embed_texts(["first filing excerpt", "second filing excerpt"])
    assert len(results) == 2
    assert all(len(r.vector) == REAL_DIMENSION for r in results)
