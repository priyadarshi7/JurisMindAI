"""Unit tests for src.graph.llm_client — HTTP mocked via respx. Live-model
behaviour (including the Qwen3 thinking-mode bug this client works around)
is covered in tests/integration/test_llm_client_live.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from pydantic import BaseModel

from src.graph.llm_client import LLMCallError, OllamaChatClient

BASE_URL = "http://localhost:11434"


class _Answer(BaseModel):
    text: str
    confident: bool


@pytest.fixture
def client() -> Iterator[OllamaChatClient]:
    with OllamaChatClient(base_url=BASE_URL, model="qwen3:4b") as c:
        yield c


def _ollama_response(content: dict[str, object], **extra: object) -> httpx.Response:
    body = {
        "model": "qwen3:4b",
        "message": {"role": "assistant", "content": json.dumps(content)},
        "prompt_eval_count": 10,
        "eval_count": 20,
        "total_duration": 500_000_000,  # ns
        **extra,
    }
    return httpx.Response(200, json=body)


@respx.mock
def test_generate_structured_parses_valid_response(client: OllamaChatClient) -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=_ollama_response({"text": "hello", "confident": True})
    )
    result, metrics = client.generate_structured(prompt="hi", schema=_Answer, temperature=0.0)

    assert result == _Answer(text="hello", confident=True)
    assert metrics.model == "qwen3:4b"
    assert metrics.input_tokens == 10
    assert metrics.output_tokens == 20
    assert metrics.latency_ms == 500.0


@respx.mock
def test_generate_structured_always_disables_thinking(client: OllamaChatClient) -> None:
    """Regression test for the live-discovered bug: Qwen3's default
    'thinking' mode can consume the whole token budget before any content
    is emitted. Every request must explicitly disable it.
    """
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=_ollama_response({"text": "hi", "confident": False})
    )
    client.generate_structured(prompt="hi", schema=_Answer, temperature=0.0, max_tokens=50)

    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["think"] is False


@respx.mock
def test_generate_structured_passes_schema_as_format(client: OllamaChatClient) -> None:
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=_ollama_response({"text": "hi", "confident": False})
    )
    client.generate_structured(prompt="hi", schema=_Answer, temperature=0.0)

    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["format"] == _Answer.model_json_schema()


@respx.mock
def test_empty_content_raises_llm_call_error(client: OllamaChatClient) -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {"role": "assistant", "content": ""},
                "prompt_eval_count": 5,
                "eval_count": 0,
                "total_duration": 100,
            },
        )
    )
    with pytest.raises(LLMCallError, match="no content"):
        client.generate_structured(prompt="hi", schema=_Answer, temperature=0.0)


@respx.mock
def test_invalid_json_matching_schema_raises_llm_call_error(client: OllamaChatClient) -> None:
    """Even under a grammar constraint, a required-field mismatch can slip
    through (e.g. wrong type) — must fail loudly, not hand a bad object
    downstream.
    """
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=_ollama_response({"text": "hi"})  # missing required "confident"
    )
    with pytest.raises(LLMCallError, match="does not match"):
        client.generate_structured(prompt="hi", schema=_Answer, temperature=0.0)


@respx.mock
def test_max_tokens_maps_to_num_predict(client: OllamaChatClient) -> None:
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=_ollama_response({"text": "hi", "confident": True})
    )
    client.generate_structured(prompt="hi", schema=_Answer, temperature=0.3, max_tokens=222)

    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["options"]["num_predict"] == 222
    assert sent_body["options"]["temperature"] == 0.3
