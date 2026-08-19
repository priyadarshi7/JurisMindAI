"""Run manifest (docs/17-ai-configuration-versioning.md).

Every research job and every evaluation run must record the complete AI
configuration that produced it — eight variables, not just the prompt
version, or every experiment silently confounds the other seven. This is
what makes "why did the system say this?" answerable months later, and what
makes a benchmark run comparable to another one.

A run manifest with a missing field is worse than no manifest: a partial
record looks reproducible without being reproducible. `RunManifest` is
frozen (immutable) once built, and every field is required — there is no
default that would let a caller construct one without deciding the value.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class RunManifest(BaseModel):
    """The full AI configuration behind one research job or evaluation run.

    Field-for-field mirror of the docs/17 example:

        prompt_name:       research_synthesis
        prompt_version:    3
        llm_model:         qwen3
        embedding_model:   qwen3-embedding-0.6b_v1
        reranker:          qwen3-reranker-0.6b_v1
        retriever_version: hybrid_v2
        chunking_version:  section_aware_v1
        benchmark_version: v1
    """

    model_config = ConfigDict(frozen=True)

    # Identity of the request this manifest belongs to.
    research_id: str
    trace_id: str

    # The eight versioned variables (docs/17).
    prompt_name: str
    prompt_version: int
    llm_model: str
    embedding_model: str
    reranker_model: str
    retrieval_config_version: str
    chunking_config_version: str
    benchmark_version: str | None = None
    # RRF parameters are part of the retrieval config version above, not a
    # separate field — keeping them out of the retrieval config would defeat
    # the point of versioning it (docs/05, docs/09 cache-identity rule).

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    git_commit_sha: str | None = None

    def cache_key_component(self) -> str:
        """Deterministic string suitable for inclusion in an LLM/retrieval
        cache key (docs/09 — "include model/prompt/retrieval versions in
        cache identity"). Deliberately excludes research_id/trace_id and
        created_at: two calls with identical configuration must hash to the
        same cache key regardless of which job made them.
        """
        return "|".join(
            [
                f"prompt={self.prompt_name}:{self.prompt_version}",
                f"llm={self.llm_model}",
                f"embedding={self.embedding_model}",
                f"reranker={self.reranker_model}",
                f"retrieval={self.retrieval_config_version}",
                f"chunking={self.chunking_config_version}",
            ]
        )


class PerCallLLMRecord(BaseModel):
    """One row of per-call LLM accounting (docs/09, D-26).

    Written to PostgreSQL (durable, budget enforcement) and referenced by a
    LangSmith run (debugging) — see docs/17. `imputed_cost` exists because a
    self-hosted model has no per-token invoice (D-1, D-26): cost is
    estimated from token counts and a configured rate recorded alongside the
    manifest, not read off a bill.
    """

    model_config = ConfigDict(frozen=True)

    research_id: str
    trace_id: str
    node: str
    model: str
    prompt_name: str
    prompt_version: int
    temperature: float
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    imputed_cost: float = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentRecord(BaseModel):
    """One benchmark/ablation run (docs/17, docs/13, D-32).

    Stored across three systems per D-32: this shape is the PostgreSQL row
    and the Git-committed result-summary file; LangSmith holds the
    underlying traces referenced by `research_id`s that fed the aggregate
    metrics here.
    """

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    manifest: RunManifest
    dataset_version: str
    metrics: dict[str, float]
    cost_total: float = Field(ge=0)
    latency_p50_ms: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)
    git_commit_sha: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
