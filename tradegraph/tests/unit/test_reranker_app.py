"""Unit tests for apps/reranker/main.py — the underlying Ollama call
mocked via respx (no live model needed). What's under test: the service
builds a listwise scoring prompt, asks for one score per passage, and
returns the top_n highest-scoring passages sorted descending — the
contract src/rag/reranking/reranker_client.py depends on.
"""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

from apps.reranker.main import OLLAMA_BASE_URL, RERANK_BATCH_SIZE, app

client = TestClient(app)


def _ollama_response(scores: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen3:4b",
            "message": {"role": "assistant", "content": json.dumps({"scores": scores})},
            "prompt_eval_count": 10,
            "eval_count": 20,
            "total_duration": 100,
        },
    )


def test_health_reports_llm_listwise_mode() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "llm-listwise"


@respx.mock
def test_rerank_returns_top_n_sorted_by_score_descending() -> None:
    respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=_ollama_response(
            [
                {"index": 0, "score": 0.2},
                {"index": 1, "score": 0.9},
                {"index": 2, "score": 0.5},
            ]
        )
    )

    response = client.post(
        "/rerank",
        json={"query": "what is revenue?", "passages": ["a", "b", "c"], "top_n": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"index": 1, "score": 0.9}, {"index": 2, "score": 0.5}]


@respx.mock
def test_rerank_ignores_out_of_range_indices() -> None:
    """A hallucinated index outside the passage list must not surface as a
    real result — this is a caller-facing contract, not a formality.
    """
    respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=_ollama_response([{"index": 0, "score": 0.5}, {"index": 99, "score": 0.99}])
    )

    response = client.post("/rerank", json={"query": "q", "passages": ["a", "b"], "top_n": 5})

    body = response.json()
    assert body["results"] == [{"index": 0, "score": 0.5}]


@respx.mock
def test_rerank_sends_one_prompt_scoring_every_passage() -> None:
    route = respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=_ollama_response([{"index": 0, "score": 0.2}, {"index": 1, "score": 0.8}])
    )

    client.post("/rerank", json={"query": "what is revenue?", "passages": ["aaa", "bbb"]})

    assert route.call_count == 1
    sent_body = json.loads(route.calls[0].request.content)
    prompt = sent_body["messages"][0]["content"]
    assert "what is revenue?" in prompt
    assert "[0] aaa" in prompt
    assert "[1] bbb" in prompt
    assert sent_body["think"] is False


@respx.mock
def test_rerank_retries_on_degenerate_all_identical_scores() -> None:
    """Found live and reproduced (2026-08-17): the exact same real query and
    passages, scored twice at temperature=0.0, came back once with real,
    differentiated scores and once with every passage scored identically —
    CPU-backend floating-point non-determinism, not a content problem. A
    same-score response for a real multi-passage set is a red flag worth
    retrying once, not trusting as a final answer.
    """
    route = respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        side_effect=[
            _ollama_response([{"index": 0, "score": 0.0}, {"index": 1, "score": 0.0}]),
            _ollama_response([{"index": 0, "score": 0.1}, {"index": 1, "score": 0.9}]),
        ]
    )

    response = client.post("/rerank", json={"query": "q", "passages": ["a", "b"], "top_n": 2})

    assert route.call_count == 2
    body = response.json()
    assert body["results"] == [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]


@respx.mock
def test_rerank_gives_up_after_max_attempts_of_degenerate_scores() -> None:
    route = respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=_ollama_response([{"index": 0, "score": 0.0}, {"index": 1, "score": 0.0}])
    )

    response = client.post("/rerank", json={"query": "q", "passages": ["a", "b"], "top_n": 2})

    assert route.call_count == 3  # MAX_RERANK_ATTEMPTS
    body = response.json()
    assert body["results"] == [{"index": 0, "score": 0.0}, {"index": 1, "score": 0.0}]


@respx.mock
def test_rerank_single_passage_never_retries() -> None:
    """A single passage always has exactly one score, so "all scores
    identical" is trivially true and must not trigger a wasted retry.
    """
    route = respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=_ollama_response([{"index": 0, "score": 0.0}])
    )

    client.post("/rerank", json={"query": "q", "passages": ["a"], "top_n": 1})

    assert route.call_count == 1


@respx.mock
def test_rerank_scores_large_candidate_sets_in_batches() -> None:
    """Found live (2026-08-18): once GPU inference made scoring far more
    reproducible run-to-run, a single call over 30-40 candidates reliably
    came back degenerate (every passage scored identically) instead of
    just occasionally, because the model genuinely can't discriminate
    reliably at that batch size — retries no longer help since GPU
    inference isn't the noisy CPU non-determinism the retry loop was built
    for. Splitting into RERANK_BATCH_SIZE-sized calls keeps each
    individual call within a size the model handles, while the service's
    external contract (one `/rerank` call in, correctly globally-ranked
    top_n out) is unchanged for the caller.
    """
    passage_count = RERANK_BATCH_SIZE + 5  # forces exactly two batches
    passages = [f"passage {i}" for i in range(passage_count)]

    def _respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        # The second batch is the last 5 passages, including "passage 17";
        # give that one the single highest score, wherever it lands.
        if "passage 17" in prompt:
            local_index = 17 - RERANK_BATCH_SIZE
            scores = [
                {"index": i, "score": 0.9 if i == local_index else 0.1}
                for i in range(passage_count - RERANK_BATCH_SIZE)
            ]
        else:
            scores = [{"index": i, "score": 0.05 * i} for i in range(RERANK_BATCH_SIZE)]
        return _ollama_response(scores)

    route = respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(side_effect=_respond)

    response = client.post(
        "/rerank", json={"query": "q", "passages": passages, "top_n": 1}
    )

    assert route.call_count == 2  # RERANK_BATCH_SIZE + 5 passages -> two batches
    body = response.json()
    assert body["results"] == [{"index": 17, "score": 0.9}]


@respx.mock
def test_rerank_returns_502_on_llm_failure() -> None:
    respx.post(f"{OLLAMA_BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {"role": "assistant", "content": ""},
                "prompt_eval_count": 1,
                "eval_count": 0,
                "total_duration": 1,
            },
        )
    )

    response = client.post("/rerank", json={"query": "q", "passages": ["a"]})

    assert response.status_code == 502
