"""Smoke tests for src.core.config (Phase 0 scaffold)."""

from __future__ import annotations

from src.core.config import (
    CacheTTLSettings,
    Environment,
    GuardrailSettings,
    ModelTierSettings,
    Settings,
    get_cache_ttl_settings,
    get_guardrail_settings,
    get_settings,
)


def test_settings_defaults_to_development() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.is_production is False


def test_settings_production_flag() -> None:
    settings = Settings(_env_file=None, environment=Environment.PRODUCTION)  # type: ignore[call-arg]
    assert settings.is_production is True


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_guardrail_defaults_match_d21() -> None:
    """docs/15 D-21: max iterations 5, tool calls 20, branches 3, LLM calls 30."""
    guardrails: GuardrailSettings = get_guardrail_settings()
    assert guardrails.max_research_iterations == 5
    assert guardrails.max_tool_calls_per_job == 20
    assert guardrails.max_parallel_research_branches == 3
    assert guardrails.max_llm_calls_per_job == 30


def test_cache_ttl_defaults_match_d24() -> None:
    """docs/15 D-24: embeddings 30d, retrieval 24h, LLM 24h."""
    ttls: CacheTTLSettings = get_cache_ttl_settings()
    assert ttls.embeddings_days == 30
    assert ttls.retrieval_hours == 24
    assert ttls.llm_hours == 24


def test_model_tier_settings_requires_all_seven_nodes(monkeypatch) -> None:
    """docs/15 D-1: every one of the seven LLM-calling nodes must have an
    explicit model tier — there is no implicit default.
    """
    for var in (
        "OLLAMA_MODEL_PLANNER",
        "OLLAMA_MODEL_QUERY_REWRITER",
        "OLLAMA_MODEL_EVIDENCE_EXTRACTOR",
        "OLLAMA_MODEL_VERIFIER",
        "OLLAMA_MODEL_CRITIC",
        "OLLAMA_MODEL_SYNTHESIZER",
        "OLLAMA_MODEL_CITATION_VALIDATOR",
    ):
        monkeypatch.setenv(var, "tradegraph-tier-fast")

    tiers = ModelTierSettings()
    assert tiers.planner == "tradegraph-tier-fast"
    assert tiers.citation_validator == "tradegraph-tier-fast"
