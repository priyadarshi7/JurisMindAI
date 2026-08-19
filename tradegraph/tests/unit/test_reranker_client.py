"""Unit tests for src.rag.reranking.reranker_client — HTTP mocked via
respx. What's under test is the client's own contract against the
`/rerank` response shape apps/reranker/main.py defines; the reranker
service's actual scoring logic is covered in tests/unit/test_reranker_app.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from src.rag.reranking.reranker_client import RerankerClient, RerankerError

BASE_URL = "http://localhost:8081"


@pytest.fixture
def client() -> Iterator[RerankerClient]:
    with RerankerClient(base_url=BASE_URL) as c:
        yield c


@respx.mock
def test_rerank_parses_results(client: RerankerClient) -> None:
    respx.post(f"{BASE_URL}/rerank").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "results": [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.4}],
            },
        )
    )

    results = client.rerank(query="q", passages=["a", "b", "c"], top_n=2)

    assert results[0].index == 2
    assert results[0].score == 0.9
    assert results[1].index == 0
    assert results[1].score == 0.4


@respx.mock
def test_rerank_sends_query_passages_top_n(client: RerankerClient) -> None:
    route = respx.post(f"{BASE_URL}/rerank").mock(
        return_value=httpx.Response(200, json={"model": "m", "results": []})
    )

    client.rerank(query="what is revenue?", passages=["a", "b"], top_n=5)

    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"query": "what is revenue?", "passages": ["a", "b"], "top_n": 5}


@respx.mock
def test_rerank_raises_on_malformed_response(client: RerankerClient) -> None:
    respx.post(f"{BASE_URL}/rerank").mock(
        return_value=httpx.Response(200, json={"model": "m"})  # no "results" key
    )

    with pytest.raises(RerankerError, match="no usable results"):
        client.rerank(query="q", passages=["a"], top_n=1)
