"""Unit tests for src.rag.embeddings.ollama_embedder — HTTP mocked via
respx. Live-server behaviour is covered in
tests/integration/test_ollama_embedder_live.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from src.rag.embeddings.ollama_embedder import EmbeddingError, OllamaEmbedder

BASE_URL = "http://localhost:11434"


@pytest.fixture
def embedder() -> Iterator[OllamaEmbedder]:
    with OllamaEmbedder(base_url=BASE_URL, model="qwen3-embedding-0.6b", expected_dimension=4) as e:
        yield e


@respx.mock
def test_embed_query_returns_vector(embedder: OllamaEmbedder) -> None:
    respx.post(f"{BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3, 0.4]]})
    )
    result = embedder.embed_query("gross margin compression")
    assert result.vector == [0.1, 0.2, 0.3, 0.4]
    assert result.model == "qwen3-embedding-0.6b"
    assert result.dimension == 4


@respx.mock
def test_embed_texts_batches_requests(embedder: OllamaEmbedder) -> None:
    embedder._batch_size = 2  # force multiple batches for a 5-item input
    call_count = 0

    def _responder(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = request.content
        import json

        n = len(json.loads(body)["input"])
        return httpx.Response(200, json={"embeddings": [[0.0, 0.0, 0.0, 0.0]] * n})

    respx.post(f"{BASE_URL}/api/embed").mock(side_effect=_responder)

    results = embedder.embed_texts([f"text {i}" for i in range(5)])
    assert len(results) == 5
    assert call_count == 3  # 2 + 2 + 1


@respx.mock
def test_dimension_mismatch_raises(embedder: OllamaEmbedder) -> None:
    respx.post(f"{BASE_URL}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})  # wrong dim
    )
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        embedder.embed_query("test")


@respx.mock
def test_wrong_batch_count_raises(embedder: OllamaEmbedder) -> None:
    respx.post(f"{BASE_URL}/api/embed").mock(
        return_value=httpx.Response(
            200, json={"embeddings": [[0.1, 0.2, 0.3, 0.4], [0.1, 0.2, 0.3, 0.4]]}
        )
    )
    with pytest.raises(EmbeddingError, match="embeddings for a batch"):
        embedder.embed_texts(["only one text"])


def test_embed_empty_list_returns_empty(embedder: OllamaEmbedder) -> None:
    assert embedder.embed_texts([]) == []
