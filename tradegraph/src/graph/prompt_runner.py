"""Ties the prompt repository, the LLM client, and per-call accounting
together (docs/09, docs/17, D-26).

One `PromptRunner.run()` call is one "important LLM call" in the docs/09
sense: it renders a versioned, immutable prompt, calls the model under a
schema constraint, and returns both the typed result and a
`PerCallLLMRecord` the caller persists to PostgreSQL. Nothing here decides
*where* that record goes — this module only produces it, staying agnostic
of the audit-log/budget-enforcement wiring downstream.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from src.core.config import get_settings
from src.graph.llm_client import OllamaChatClient
from src.models.run_manifest import PerCallLLMRecord
from src.prompts.loader import PromptRepository

ModelT = TypeVar("ModelT", bound=BaseModel)


def format_numbered_list(items: list[str]) -> str:
    """Render a list as `[0] ...\\n[1] ...` — the one place every
    index-referencing prompt's numbering comes from, so a node function and
    the prompt it calls can never disagree about where numbering starts.
    """
    return "\n".join(f"[{i}] {item}" for i, item in enumerate(items))


class PromptRunner:
    def __init__(self, *, base_url: str, prompt_repository: PromptRepository) -> None:
        self._base_url = base_url
        self._repository = prompt_repository
        self._clients: dict[str, OllamaChatClient] = {}
        self._imputed_cost_rate = get_settings().imputed_cost_rate_per_1k_tokens

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

    def __enter__(self) -> PromptRunner:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _client_for_model(self, model: str) -> OllamaChatClient:
        if model not in self._clients:
            self._clients[model] = OllamaChatClient(base_url=self._base_url, model=model)
        return self._clients[model]

    def run(
        self,
        *,
        node: str,
        version: int,
        model: str,
        variables: dict[str, str],
        schema: type[ModelT],
        research_id: str,
        trace_id: str,
    ) -> tuple[ModelT, PerCallLLMRecord]:
        prompt_def = self._repository.get(node, version)
        rendered = prompt_def.render(**variables)

        client = self._client_for_model(model)
        result, metrics = client.generate_structured(
            prompt=rendered,
            schema=schema,
            temperature=prompt_def.model_requirements.temperature,
            max_tokens=prompt_def.model_requirements.max_tokens,
        )

        total_tokens = metrics.input_tokens + metrics.output_tokens
        record = PerCallLLMRecord(
            research_id=research_id,
            trace_id=trace_id,
            node=node,
            model=metrics.model,
            prompt_name=prompt_def.name,
            prompt_version=prompt_def.version,
            temperature=prompt_def.model_requirements.temperature,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            latency_ms=metrics.latency_ms,
            imputed_cost=(total_tokens / 1000) * self._imputed_cost_rate,
        )
        return result, record
