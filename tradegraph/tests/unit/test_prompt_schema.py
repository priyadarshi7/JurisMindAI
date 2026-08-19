"""Unit tests for src.prompts.schema (docs/17, D-25)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.prompts.schema import ModelRequirements, PromptDefinition


def _make_prompt(**overrides: object) -> PromptDefinition:
    defaults: dict[str, object] = {
        "name": "test_prompt",
        "version": 1,
        "description": "A test prompt.",
        "variables": ["question"],
        "prompt": "Answer: {question}",
    }
    defaults.update(overrides)
    return PromptDefinition.model_validate(defaults)


def test_render_fills_declared_variables() -> None:
    prompt = _make_prompt()
    assert prompt.render(question="why?") == "Answer: why?"


def test_render_rejects_missing_variable() -> None:
    prompt = _make_prompt()
    with pytest.raises(ValueError, match="missing required variables"):
        prompt.render()


def test_render_rejects_undeclared_variable() -> None:
    prompt = _make_prompt()
    with pytest.raises(ValueError, match="undeclared"):
        prompt.render(question="why?", extra="not declared")


def test_name_must_be_lower_snake_case() -> None:
    with pytest.raises(ValidationError):
        _make_prompt(name="NotSnakeCase")


def test_duplicate_variables_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_prompt(variables=["question", "question"])


def test_prompt_definition_is_frozen() -> None:
    prompt = _make_prompt()
    with pytest.raises(ValidationError):
        prompt.version = 2  # type: ignore[misc]


def test_model_requirements_temperature_bounds() -> None:
    with pytest.raises(ValidationError):
        ModelRequirements(temperature=3.0)


def test_model_requirements_defaults_to_deterministic() -> None:
    assert ModelRequirements().temperature == 0.0
