"""HTTP client for the reranker service (apps/reranker/main.py, D-30).

The retrieval side stays agnostic of how the reranker actually scores
passages (currently LLM-based listwise scoring; if a dedicated
cross-encoder runtime is ever benchmarked in per D-30, it swaps in behind
this same `/rerank` contract) — this module is the one place that contract
is spoken.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

DEFAULT_TIMEOUT_SECONDS = 900.0
# Same "not latency-critical, CPU inference is slow" reasoning as
# src/graph/llm_client.py's DEFAULT_TIMEOUT_SECONDS — the reranker service
# makes a real Ollama call under the hood. Sized for the server's own
# MAX_RERANK_ATTEMPTS=3 retry-on-degenerate-output loop (apps/reranker/
# main.py) — found live, this client's 300s previously timed out mid-retry
# on a request the server would have completed given more room.


class RerankerError(Exception):
    pass


@dataclass(frozen=True)
class RerankedPassage:
    index: int
    score: float


class RerankerClient:
    def __init__(self, *, base_url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RerankerClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def rerank(self, *, query: str, passages: list[str], top_n: int) -> list[RerankedPassage]:
        response = self._client.post(
            "/rerank",
            json={"query": query, "passages": passages, "top_n": top_n},
        )
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results")
        if not isinstance(results, list):
            raise RerankerError(f"reranker returned no usable results: {payload!r}")

        return [RerankedPassage(index=r["index"], score=r["score"]) for r in results]
