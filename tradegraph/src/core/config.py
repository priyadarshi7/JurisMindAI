"""Application configuration.

Loads from environment variables / a local `.env` file only — real values
never live in this repository (docs/11-security-and-safety.md, docs/12 §12).
`.env.example` is the canonical list of every variable this module reads;
keep the two in sync.

Three environments are required by docs/12 (§14, §20): development, staging,
production. `Settings.environment` is the single source of truth for which
one is active.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class ModelTierSettings(BaseSettings):
    """Per-node Qwen3 model tiering (docs/15 D-1) — sizes pinned per D-30."""

    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_MODEL_", extra="ignore", env_ignore_empty=True
    )

    planner: str = Field(...)
    query_rewriter: str = Field(...)
    evidence_extractor: str = Field(...)
    verifier: str = Field(...)
    critic: str = Field(...)
    synthesizer: str = Field(...)
    citation_validator: str = Field(...)


class GuardrailSettings(BaseSettings):
    """Numeric agent guardrails — tunable defaults (docs/15 D-21)."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    max_research_iterations: int = Field(default=5, alias="MAX_RESEARCH_ITERATIONS")
    max_tool_calls_per_job: int = Field(default=20, alias="MAX_TOOL_CALLS_PER_JOB")
    max_parallel_research_branches: int = Field(default=3, alias="MAX_PARALLEL_RESEARCH_BRANCHES")
    max_llm_calls_per_job: int = Field(default=30, alias="MAX_LLM_CALLS_PER_JOB")


class CacheTTLSettings(BaseSettings):
    """Cache TTLs — secondary to version-based invalidation (docs/15 D-24)."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    embeddings_days: int = Field(default=30, alias="CACHE_TTL_EMBEDDINGS_DAYS")
    retrieval_hours: int = Field(default=24, alias="CACHE_TTL_RETRIEVAL_HOURS")
    llm_hours: int = Field(default=24, alias="CACHE_TTL_LLM_HOURS")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    environment: Environment = Environment.DEVELOPMENT

    # -- API --------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allowed_origins: str = ""

    # -- Auth (D-11) --------------------------------------------------------
    jwt_secret_key: str = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # -- PostgreSQL (D-7, D-10) -----------------------------------------------
    database_url: PostgresDsn | None = None

    # -- Redis (D-8) ----------------------------------------------------------
    celery_broker_url: RedisDsn | None = None
    celery_result_backend: RedisDsn | None = None

    # -- Qdrant (D-3) -----------------------------------------------------------
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = Field(default=None, repr=False)
    qdrant_collection_name: str = "tradegraph_documents"

    # -- Neo4j citation knowledge graph (NyayaGraph pivot) ---------------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="tradegraph123", repr=False)

    # -- Object storage -----------------------------------------------------
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)
    s3_region: str = "us-east-1"
    s3_bucket_raw_documents: str = "tradegraph-raw-documents"
    s3_bucket_market_data: str = "tradegraph-market-data"

    # -- Ollama (D-1, D-2, D-30) ----------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "qwen3-embedding-0.6b"
    ollama_embedding_dimension: int = 1024
    # Single uniform chat model the V1 linear pipeline (src/graph/pipeline.py)
    # calls for every node. `ModelTierSettings` below already models real
    # per-node tiering, but nothing wires it into the pipeline yet — that's
    # V2/V3 work; until then this is the one knob that exists.
    ollama_chat_model: str = "qwen3:4b"

    # -- Reranker (D-30 — own serving path, not Ollama) ------------------------
    reranker_base_url: str = "http://localhost:8081"
    reranker_model: str = "qwen3-reranker-0.6b"

    # -- MCP (D-9, D-29) --------------------------------------------------------
    mcp_transport: str = "stdio"  # stdio (dev) | http (prod) — D-29
    mcp_quant_server_url: str | None = None
    mcp_market_data_server_url: str | None = None

    # -- LangSmith (D-25 — experimentation/tracing only, never a config source)
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = Field(default=None, repr=False)
    langchain_project: str = "tradegraph"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # -- OpenTelemetry --------------------------------------------------------
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "tradegraph"

    # -- Prometheus (D-31) -------------------------------------------------------
    prometheus_metrics_port: int = 9464

    # -- Cost imputation (D-1, D-26 — no per-token invoice, self-hosted model)
    imputed_cost_rate_per_1k_tokens: float = 0.0

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — read once per process."""
    return Settings()


@lru_cache
def get_model_tier_settings() -> ModelTierSettings:
    return ModelTierSettings()


@lru_cache
def get_guardrail_settings() -> GuardrailSettings:
    return GuardrailSettings()


@lru_cache
def get_cache_ttl_settings() -> CacheTTLSettings:
    return CacheTTLSettings()
