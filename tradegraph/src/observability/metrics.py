"""Prometheus metric definitions (docs/10, docs/15 D-31).

Every metric object lives here, exactly once, and every other module
imports from this file rather than calling `Counter(...)`/`Histogram(...)`
itself. `prometheus_client`'s default registry raises on a duplicate metric
name — centralizing definitions is what makes that structurally impossible
instead of a discipline someone has to remember, the same reasoning
`HybridRetriever` uses for filter parity (see its module docstring).

D-31's label discipline: low-cardinality only (`service`, `endpoint`,
`model`, `node`, `call_type`, `status`, `queue`, `stage`) — never
`research_id` as a label; that belongs in traces and PostgreSQL.

Three independent processes read this module: the API (uvicorn), the
research worker (Celery), and the reranker service. Each owns its own
process-local Prometheus registry and its own `/metrics` endpoint —
Prometheus's scrape-added `job`/`instance` labels are what disambiguate
"which process" for a metric name shared across more than one of them
(e.g. `ollama_model_latency_seconds`, emitted by both the worker and the
reranker), not an explicit `service` label on every single metric.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# -- API (docs/15 D-31 "API" family) ----------------------------------------
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["service", "endpoint", "method", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request handling time",
    ["service", "endpoint", "method"],
)

# -- RAG (docs/15 D-31 "RAG" family) -----------------------------------------
# cache_hit_rate is deliberately not defined: src/cache/ has no
# implementation yet (V4 work) — a metric with no real producer would be a
# fabricated zero forever, not an honest gap.
RETRIEVAL_LATENCY = Histogram(
    "retrieval_latency_seconds",
    "HybridRetriever.search() wall time, dense+sparse+fusion+rerank",
    ["stage"],
)
RERANKER_LATENCY = Histogram(
    "reranker_latency_seconds",
    "Reranker service /rerank handler wall time",
)

# -- LLM (docs/15 D-31 "LLM" family) — emitted once per PromptRunner.run() --
LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "One graph-node LLM call, as reported by Ollama (prompt_eval + eval)",
    ["node", "model"],
)
LLM_INPUT_TOKENS = Counter(
    "llm_input_tokens_total", "Prompt tokens consumed per graph node", ["node", "model"]
)
LLM_OUTPUT_TOKENS = Counter(
    "llm_output_tokens_total", "Completion tokens produced per graph node", ["node", "model"]
)
LLM_ESTIMATED_COST = Counter(
    "llm_estimated_cost_total",
    "Imputed cost (docs/15 D-26 — no real invoice for a self-hosted model)",
    ["node", "model"],
)

# -- Ollama (docs/15 D-31 "Ollama" family) — the raw HTTP call, independent
# of which higher-level caller made it (a graph node via PromptRunner, or
# the reranker's own listwise scoring) ---------------------------------------
OLLAMA_INFLIGHT = Gauge(
    "ollama_inflight_requests",
    "In-flight requests to Ollama right now (D-30 concurrency check)",
    ["call_type"],
)
OLLAMA_MODEL_LATENCY = Histogram(
    "ollama_model_latency_seconds",
    "Wall time of one Ollama HTTP call (chat or embed)",
    ["call_type", "model"],
)

# -- Workers (docs/15 D-31 "Workers" family) --------------------------------
WORKER_JOB_DURATION = Histogram(
    "worker_job_duration_seconds", "run_research() wall time per job", ["queue"]
)
WORKER_JOB_FAILURES = Counter(
    "worker_job_failures_total", "Jobs that raised out of run_research()", ["queue"]
)
WORKER_QUEUE_DEPTH = Gauge(
    "worker_queue_depth", "Pending (unacked) tasks on a Celery/Redis queue", ["queue"]
)


def render_latest() -> tuple[bytes, str]:
    """Body + content-type for a `/metrics` route. Not multiprocess-aware —
    every process in this stack (uvicorn without `--workers`, Celery
    `--pool=solo`, the reranker's single uvicorn process) is single-process,
    so the default global registry is correct and `multiprocess` mode
    (which needs `PROMETHEUS_MULTIPROC_DIR` wired through every worker)
    would be unused complexity, not a correctness fix.
    """
    return generate_latest(), CONTENT_TYPE_LATEST
