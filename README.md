# JurisMindAI

**Agentic Legal Research & Intelligence Platform** for Indian law — a
stateful research platform, not a query → retrieve → generate chatbot.
Given a fact pattern or legal question, it identifies the relevant
constitutional/statutory provisions and authorities, extracts and verifies
supporting evidence from the ingested corpus, checks for contradictions,
and produces a report where every claim is backed by a citation that
passed an explicit entailment check — a claim a citation can't support is
rewritten or dropped, never shipped unchecked. See [`docs/`](docs/README.md)
for the full architecture, technology rationale, and the resolved decision
log; this file is a setup guide, not a design doc.

## Prerequisites

- Python 3.11 or 3.12
- Node 20+ (for the frontend, `apps/web/`)
- Docker + Docker Compose
- A GPU-capable host is strongly recommended. Ollama and the reranker run
  on CPU too, but this project's own debugging history shows real jobs
  comfortably exceed generous CPU timeouts — see docs/12's caveat on
  measuring concurrency on representative hardware.

## Setup

```sh
# 1. Python environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Environment configuration — copy and fill in LOCAL values only.
#    Never commit .env (docs/11, docs/12 §12).
cp .env.example .env

# 3. Local data + model services
docker compose up -d postgres redis qdrant minio ollama reranker neo4j prometheus grafana

# 4. Pull the pinned Ollama models
ollama pull qwen3:4b
ollama pull qwen3-embedding:0.6b

# 5. Apply database migrations
alembic upgrade head

# 6. Run the API
uvicorn apps.api.main:app --reload
curl localhost:8000/health

# 7. Run the research worker (a separate process — research never runs
#    inline in an API request, see docs/06 D-16)
celery -A src.core.celery_app worker --queues=research
#    Windows note: add --pool=solo — Celery's default worker pools rely on
#    fork/prefork, which isn't available there.

# 8. Run the frontend
cd apps/web
npm install
npm run dev
```

If a request to Ollama returns an intermittent 500 on a memory-constrained
GPU, see `docker-compose.yml`'s `ollama` service comments — this is a real,
previously-debugged VRAM-pressure failure mode with both a configuration
mitigation and client-side retry already in place, not a new bug to
re-diagnose.

### Corpus

Retrieval only answers questions the ingested corpus actually covers.
Today that's the Constitution of India, Part III (Fundamental Rights,
Articles 12–35) — ingested via `src/rag/ingestion/india_code.py`'s
`ingest_constitution_part()`. There is no ingestion CLI yet; invoking it is
a one-off async call against a running Postgres/Qdrant/MinIO stack, not a
committed script. Expanding corpus coverage (further Constitution Parts,
Central Acts, curated judgments) is tracked as open work — a question
outside what's ingested will correctly come back `insufficient_evidence`
rather than a hallucinated answer, per docs/06's evidence-gating design.

## Development

```sh
ruff check . && ruff format --check .   # lint
mypy src apps                           # type check
pytest tests/unit -m unit               # unit tests (no services required)
pytest tests/integration -m integration # requires the docker-compose stack

cd apps/web
npm run build                           # tsc -b && vite build
npm run lint                            # oxlint
```

Same backend chain runs in CI — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Repository layout

Mirrors [docs/12-infrastructure-and-deployment.md](docs/12-infrastructure-and-deployment.md) §15,
plus two owner additions (`src/mcp/`, `ops/`) recorded in
[docs/15-open-decisions.md](docs/15-open-decisions.md).

```
apps/
  api/          FastAPI — control plane, not compute plane. Job creation,
                status/report retrieval, SSE progress streaming, deletion.
  web/          React + TypeScript — the research workspace UI.
  reranker/     LLM-based listwise reranker (reuses the Ollama chat model;
                see apps/reranker/main.py for why not a dedicated
                cross-encoder — docs/15 D-30).
src/
  graph/        The research pipeline: Planner -> Query Decomposer ->
                {retrieve -> extract -> verify -> detect contradictions}
                per sub-question -> Synthesizer -> Critic -> Citation
                Validator -> stored report. A linear chain today (docs/00
                MVP scope); the LangGraph cyclic "research again" loop is
                V2 work — see src/graph/pipeline.py's module docstring.
  rag/          Ingestion, chunking, embeddings, vector (Qdrant), bm25,
                hybrid retrieval, reranking, and the Neo4j citation graph
                (src/rag/graph/).
  quant/        Deterministic quant engine                 (V3, legacy)
  mcp/          MCP servers — quant first, retrieval excluded (D-29)
  prompts/      Versioned prompt repository — see below     (live)
  models/       Shared data models incl. run manifest       (live)
  cache/        Redis cache-layer helpers                   (V4)
  evaluation/   Benchmark dataset + evaluation harness       (V1 start, V5 complete)
  observability/  LangSmith + OTel + Prometheus wiring       (V1 start, V4 complete)
  core/         Settings, Celery app, cross-cutting config   (live)
migrations/     Alembic — live schema, including the legal-corpus tables
                (documents/court/citation metadata, legal_sections)
tests/          unit/ (no services) and integration/ (docker-compose)
docker/         Dockerfiles — api, worker, reranker
ops/            Prometheus config, Grafana dashboards, Ollama modelfiles
```

## Prompt versioning

Git is the production source of truth for prompts; LangSmith is for
experimentation and tracing only — the application never fetches a prompt
from a service at runtime
([docs/17](docs/17-ai-configuration-versioning.md), D-25).

Each of the eight graph nodes has a directory under `src/prompts/`, holding
immutable `vN.yaml` files:

```
src/prompts/
├── planner/v1.yaml
├── query_rewriter/v1.yaml
├── evidence_extractor/v1.yaml, v2.yaml, v3.yaml, v4.yaml
├── verifier/v1.yaml, v2.yaml, v3.yaml
├── contradiction/v1.yaml, v2.yaml
├── synthesizer/v1.yaml, v2.yaml
├── critic/v1.yaml, v2.yaml, v3.yaml
└── citation_validator/v1.yaml
```

`src/prompts/loader.py` validates every file's identity and declared
variables at process startup (`apps/api/main.py`'s lifespan) — an invalid
prompt file fails the deploy, not the first research job that reaches it. A
committed version is never edited in place; changing a prompt means adding
`vN+1.yaml` and going through the promotion path in docs/17 (edit →
evaluate against the benchmark → compare → commit). Most of the version
bumps above are the same class of fix, applied as it was found live for
each node in turn: a fixed `max_tokens` budget too small for real-world
input/output size, discovered via an actual job that truncated mid-output
rather than by static review.

## Architectural decisions

All implementation-level decisions this scaffold depends on are resolved
and logged in [docs/15-open-decisions.md](docs/15-open-decisions.md), each
marked 🔒 **locked** (architectural — a later change is a migration) or 🎛️
**tunable** (a versioned default expected to change under benchmark
evidence). Do not re-decide one of these inside application code — resolve
it there first.

## Known limitations

- **Corpus coverage** — see "Corpus" above; a question outside the
  ingested Constitution text correctly returns `insufficient_evidence`.
- **No authentication** — the frontend's account menu is a static,
  disclosed placeholder ("local demo profile"); there is no real user
  system, and every job is currently unscoped to a tenant.
- **Single-node, local-first services** — Postgres/Redis/Qdrant/Neo4j all
  run as single Docker Compose containers, matching this project's
  "simplest viable option first" discipline (D-30), not a
  production-scale deployment.
- **GPU memory headroom** — a 6GB-class GPU has very little slack once
  both Ollama models are resident; see the `ollama` service's
  `docker-compose.yml` comments for the mitigations already in place.
