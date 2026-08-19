"""Unit tests for src.models.run_manifest (docs/17)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.run_manifest import RunManifest


def _make_manifest(**overrides: object) -> RunManifest:
    defaults: dict[str, object] = {
        "research_id": "research_8f92",
        "trace_id": "4bf92f3577b34da6",
        "prompt_name": "research_synthesis",
        "prompt_version": 3,
        "llm_model": "qwen3",
        "embedding_model": "qwen3-embedding-0.6b_v1",
        "reranker_model": "qwen3-reranker-0.6b_v1",
        "retrieval_config_version": "hybrid_v2",
        "chunking_config_version": "section_aware_v1",
        "benchmark_version": "v1",
    }
    defaults.update(overrides)
    return RunManifest.model_validate(defaults)


def test_manifest_is_frozen() -> None:
    manifest = _make_manifest()
    with pytest.raises(ValidationError):
        manifest.prompt_version = 4  # type: ignore[misc]


def test_cache_key_component_is_deterministic() -> None:
    a = _make_manifest()
    b = _make_manifest()
    assert a.cache_key_component() == b.cache_key_component()


def test_cache_key_component_excludes_identity_fields() -> None:
    """Two manifests differing only in research_id/trace_id/created_at must
    produce the same cache key — those fields identify the job, not the
    configuration that would make two LLM calls equivalent (docs/09).
    """
    a = _make_manifest(research_id="research_aaa", trace_id="trace_aaa")
    b = _make_manifest(research_id="research_bbb", trace_id="trace_bbb")
    assert a.cache_key_component() == b.cache_key_component()


def test_cache_key_component_changes_with_prompt_version() -> None:
    a = _make_manifest(prompt_version=1)
    b = _make_manifest(prompt_version=2)
    assert a.cache_key_component() != b.cache_key_component()


def test_cache_key_component_changes_with_embedding_model() -> None:
    """docs/09: an embedding-model change must invalidate the cache key."""
    a = _make_manifest(embedding_model="qwen3-embedding-0.6b_v1")
    b = _make_manifest(embedding_model="qwen3-embedding-0.6b_v2")
    assert a.cache_key_component() != b.cache_key_component()


def test_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate({"research_id": "research_8f92"})
