"""Unit tests for src.graph.prompt_runner — uses the real prompt
repository (loaded from src/prompts/) with the underlying HTTP call
mocked via respx.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from src.graph.prompt_runner import PromptRunner, format_numbered_list
from src.graph.schemas import PlannerOutput
from src.prompts.loader import PromptRepository

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "prompts"
BASE_URL = "http://localhost:11434"


def test_format_numbered_list() -> None:
    assert format_numbered_list(["a", "b", "c"]) == "[0] a\n[1] b\n[2] c"


def test_format_numbered_list_empty() -> None:
    assert format_numbered_list([]) == ""


@respx.mock
def test_run_renders_real_prompt_and_returns_record() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "entities": ["NVIDIA"],
                            "evidence_needed": "quantitative",
                            "is_compound": False,
                            "plan_notes": "check the 10-K",
                        }
                    ),
                },
                "prompt_eval_count": 42,
                "eval_count": 17,
                "total_duration": 250_000_000,
            },
        )
    )

    repository = PromptRepository(PROMPTS_ROOT)
    with PromptRunner(base_url=BASE_URL, prompt_repository=repository) as runner:
        result, record = runner.run(
            node="planner",
            version=1,
            model="qwen3:4b",
            variables={"query": "Why did NVIDIA's margin decline?"},
            schema=PlannerOutput,
            research_id="research_test",
            trace_id="trace_test",
        )

    assert isinstance(result, PlannerOutput)
    assert result.entities == ["NVIDIA"]

    assert record.research_id == "research_test"
    assert record.trace_id == "trace_test"
    assert record.node == "planner"
    assert record.prompt_name == "research_planner"
    assert record.prompt_version == 1
    assert record.model == "qwen3:4b"
    assert record.input_tokens == 42
    assert record.output_tokens == 17


@respx.mock
def test_run_reuses_client_per_model() -> None:
    """Two calls against the same model must reuse one underlying HTTP
    client, not reconnect per call.
    """
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "entities": [],
                            "evidence_needed": "qualitative",
                            "is_compound": False,
                            "plan_notes": "x",
                        }
                    ),
                },
                "prompt_eval_count": 1,
                "eval_count": 1,
                "total_duration": 1,
            },
        )
    )

    repository = PromptRepository(PROMPTS_ROOT)
    with PromptRunner(base_url=BASE_URL, prompt_repository=repository) as runner:
        runner.run(
            node="planner",
            version=1,
            model="qwen3:4b",
            variables={"query": "q1"},
            schema=PlannerOutput,
            research_id="r1",
            trace_id="t1",
        )
        runner.run(
            node="planner",
            version=1,
            model="qwen3:4b",
            variables={"query": "q2"},
            schema=PlannerOutput,
            research_id="r1",
            trace_id="t1",
        )
        assert len(runner._clients) == 1

    assert route.call_count == 2


def test_imputed_cost_is_zero_by_default(monkeypatch: object) -> None:  # type: ignore[valid-type]
    """docs/15 D-1/D-26: with no configured rate, imputed cost defaults to
    0.0 rather than raising — a self-hosted model has no invoice by
    definition.
    """
    repository = PromptRepository(PROMPTS_ROOT)
    runner = PromptRunner(base_url=BASE_URL, prompt_repository=repository)
    assert runner._imputed_cost_rate == 0.0
    runner.close()
