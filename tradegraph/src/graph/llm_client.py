"""Ollama chat client with structured (JSON-schema-constrained) output.

docs/06 requires typed handoffs between every node — "never prose
handoffs." docs/02/D-1 notes that a self-hosted model is weaker at strict
schema adherence than the frontier hosted models this pattern is usually
demonstrated with, so **constrained decoding is required, not optional**:
every call here passes the target Pydantic model's JSON schema as Ollama's
`format` parameter, which constrains generation at the token level rather
than hoping the model's prose happens to parse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.observability.metrics import OLLAMA_INFLIGHT, OLLAMA_MODEL_LATENCY

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_TIMEOUT_SECONDS = 600.0
# ❗ Discovered live, via real jobs through the API/Celery worker, twice:
# the evidence_extractor call — the node that reasons over the most input
# text (several numbered passages at once) — hit `httpx.ReadTimeout` at
# 180s, then again at 300s once the rest of the dev stack (API, worker,
# Vite, a real browser) was competing for the same CPU cores the earlier
# isolated pytest run didn't have to share. Same class of problem already
# found and fixed once for batch embedding
# (src/rag/embeddings/ollama_embedder.py). A research job is not
# latency-critical the way a live chat turn is, so the timeout should track
# "won't hang forever," not "as fast as the isolated best case."


class LLMCallError(Exception):
    pass


def _is_transient_ollama_error(exc: BaseException) -> bool:
    """True for errors worth retrying: connection failures, and 5xx
    responses. Found live (2026-08-19): on a VRAM-constrained GPU, Ollama's
    internal llama-server child can crash mid-request under memory pressure
    and return a bare 500 — but its supervisor respawns it within a second
    or two, so the *next* call usually succeeds. `raise_for_status()` raises
    `httpx.HTTPStatusError`, a sibling of `httpx.TransportError` in httpx's
    exception hierarchy (not a subclass), so a retry predicate scoped to
    TransportError alone never catches this and the transient crash surfaces
    as a hard failure instead of self-healing.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


@dataclass(frozen=True)
class LLMCallMetrics:
    """Raw material for a `PerCallLLMRecord` (docs/09, D-26) — the caller
    (the prompt runner) turns this into a persisted row; this client only
    reports what Ollama told it about the call.
    """

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class OllamaChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._model = model

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaChatClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[ModelT],
        temperature: float,
        max_tokens: int | None = None,
    ) -> tuple[ModelT, LLMCallMetrics]:
        """One constrained-decoding call. Raises `LLMCallError` — never a
        raw httpx exception — for every failure mode: no content, output
        that doesn't validate against `schema` even under a grammar
        constraint, a connection failure, or an Ollama-side 5xx that
        outlasted the retry budget. Callers (e.g. apps/reranker/main.py)
        only need to catch one exception type; a raw httpx.HTTPStatusError
        escaping here once meant a persistent Ollama crash produced an
        unhandled 500 with a full traceback instead of the caller's
        intended degrade-gracefully path (found live, 2026-08-19).
        """
        try:
            return self._generate_structured(
                prompt=prompt, schema=schema, temperature=temperature, max_tokens=max_tokens
            )
        except httpx.HTTPError as exc:
            raise LLMCallError(
                f"Ollama call failed for model {self._model!r} (schema {schema.__name__}): {exc}"
            ) from exc

    @retry(
        retry=retry_if_exception(_is_transient_ollama_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _generate_structured(
        self,
        *,
        prompt: str,
        schema: type[ModelT],
        temperature: float,
        max_tokens: int | None = None,
    ) -> tuple[ModelT, LLMCallMetrics]:
        options: dict[str, object] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        OLLAMA_INFLIGHT.labels(call_type="chat").inc()
        start = time.monotonic()
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "format": schema.model_json_schema(),
                    "options": options,
                    # ❗ Qwen3 reasons by default ("thinking" mode) before
                    # emitting content. Discovered live: with a capped
                    # num_predict, thinking alone can consume the whole budget
                    # and content comes back empty. The reasoning trace isn't
                    # part of any node's schema anyway and directly works
                    # against the D-21 token/latency budgets, so it's disabled
                    # for every structured call, not just token-constrained
                    # ones.
                    "think": False,
                    "stream": False,
                },
            )
        finally:
            OLLAMA_MODEL_LATENCY.labels(call_type="chat", model=self._model).observe(
                time.monotonic() - start
            )
            OLLAMA_INFLIGHT.labels(call_type="chat").dec()
        response.raise_for_status()
        payload = response.json()

        content = payload.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMCallError(
                f"Ollama returned no content for model {self._model!r} (schema {schema.__name__})"
            )

        try:
            parsed = schema.model_validate_json(content)
        except ValidationError as exc:
            raise LLMCallError(
                f"model {self._model!r} produced output that does not match "
                f"{schema.__name__} even under a constrained schema: {exc}"
            ) from exc

        metrics = LLMCallMetrics(
            model=self._model,
            input_tokens=int(payload.get("prompt_eval_count", 0)),
            output_tokens=int(payload.get("eval_count", 0)),
            latency_ms=payload.get("total_duration", 0) / 1_000_000,
        )
        return parsed, metrics
