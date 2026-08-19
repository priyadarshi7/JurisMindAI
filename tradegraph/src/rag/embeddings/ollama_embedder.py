"""Ollama embedding client (docs/15 D-2, D-30) — self-hosted Qwen3-Embedding.

Calls Ollama's `/api/embed` endpoint, which accepts a batch of inputs in
one request. Every call validates the returned vector dimension against
the pinned configuration (`OLLAMA_EMBEDDING_DIMENSION`) — a silent
dimension mismatch is exactly the failure mode that corrupts a Qdrant
collection (docs/04: "pin the dimension before creating the collection").
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

DEFAULT_BATCH_SIZE = 16
DEFAULT_TIMEOUT_SECONDS = 300.0
# ❗ Discovered live: embedding a full batch of chunks from a large filing
# (a real 10-Q, not the small 8-K this was first tested against) on
# CPU-only Ollama comfortably exceeds a 60s timeout — a single query embed
# is fast, but DEFAULT_BATCH_SIZE x ~700 tokens of real batch work is not.
# The smaller batch size and longer timeout both reduce the chance of a
# single slow batch consuming the whole allowance; ingestion is not
# latency-critical the way a live research query is, so a generous ceiling
# costs nothing here.


class EmbeddingError(Exception):
    pass


def _is_transient_ollama_error(exc: BaseException) -> bool:
    """True for connection failures and 5xx responses. `raise_for_status()`
    raises `httpx.HTTPStatusError`, a sibling of `httpx.TransportError` in
    httpx's hierarchy (not a subclass) — a retry scoped to TransportError
    alone misses a 500, including the transient kind where Ollama's internal
    llama-server child crashed under GPU memory pressure and respawns within
    a second or two (src/graph/llm_client.py hit and fixed the same gap
    live, 2026-08-19).
    """
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimension: int


class OllamaEmbedder:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        expected_dimension: int,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._model = model
        self._expected_dimension = expected_dimension
        self._batch_size = batch_size

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaEmbedder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        """Raises `EmbeddingError` — never a raw httpx exception — for every
        failure mode, including a connection failure or an Ollama-side 5xx
        that outlasted the retry budget (same normalization as
        src/graph/llm_client.py's generate_structured, fixed live
        2026-08-19 for the identical reason: callers only catch
        EmbeddingError, and a raw httpx.HTTPStatusError escaping here would
        crash the caller instead of surfacing as the intended error type).
        """
        if not texts:
            return []

        try:
            results: list[EmbeddingResult] = []
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                results.extend(self._embed_batch(batch))
            return results
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding call failed for model {self._model!r}: {exc}") from exc

    def embed_query(self, text: str) -> EmbeddingResult:
        return self.embed_texts([text])[0]

    @retry(
        retry=retry_if_exception(_is_transient_ollama_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _embed_batch(self, batch: list[str]) -> list[EmbeddingResult]:
        response = self._client.post("/api/embed", json={"model": self._model, "input": batch})
        response.raise_for_status()
        payload = response.json()

        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise EmbeddingError(
                f"Ollama returned {len(vectors) if isinstance(vectors, list) else 'no'} "
                f"embeddings for a batch of {len(batch)} inputs"
            )

        results: list[EmbeddingResult] = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != self._expected_dimension:
                actual = len(vector) if isinstance(vector, list) else "unknown"
                raise EmbeddingError(
                    f"embedding dimension mismatch: expected "
                    f"{self._expected_dimension}, got {actual}. The pinned "
                    f"OLLAMA_EMBEDDING_DIMENSION must match the served "
                    f"model's actual output — see docs/15 D-2."
                )
            results.append(EmbeddingResult(vector=vector, model=self._model, dimension=len(vector)))
        return results
