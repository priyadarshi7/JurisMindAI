# 12 — Infrastructure & Deployment

> **Source:** Blueprint §13 (Production Deployment), §14 (CI/CD & Environments), §15 (Final
> Repository Structure), §20.
> **Status:** Specification-derived.

---

## Production topology (§13)

```
Internet
  → Cloudflare / CDN
  → React Frontend
  → HTTPS
  → FastAPI API
       ├── PostgreSQL
       ├── Redis
       ├── Qdrant Cloud
       └── Research Worker → LangGraph → Object Storage
                │
                ├── Ollama          (Qwen3, Qwen3 Embedding)   ⚙
                ├── Reranker server (Qwen3 Reranker)           ⚙
                └── MCP servers     (quant · market-data)      ⚙
```

⚙ = owner addition of 2026-08-14, not in §13.

---

## Recommended first deployment split (§13)

| Component | Deployment |
|---|---|
| Frontend | Vercel or equivalent managed frontend platform |
| FastAPI | Docker container on Railway / Render / Fly.io / AWS-style container platform |
| **Research worker** | **Separate Docker container/service** |
| PostgreSQL | Managed PostgreSQL |
| Redis | Managed Redis |
| Qdrant | Qdrant Cloud |
| Object storage | **MinIO** — S3-compatible, self-hosted |
| CI/CD | GitHub Actions |
| ⚙ **Ollama** | GPU host, private network, co-located with the worker |
| ⚙ **Reranker server** | Container, likely GPU — see [D-30](15-open-decisions.md) |
| ⚙ **MCP servers** | ❗ Co-located with the research worker; never across a WAN |
| ⚙ **Prometheus + Grafana** | Containers or a managed metrics stack |

### The tension the self-hosted choices create with §13

❗ §13 says *"start with managed services"* and §20 says *"do not over-engineer infrastructure."* The
2026-08-14 decision moves the model layer and object storage **off** managed services, which is a
deliberate move in the other direction. That is a legitimate owner call — it buys zero per-token
cost, full version pinning, and a corpus that never leaves our infrastructure — but the trade is
real and should be named rather than smoothed over:

| Gained | Paid for with |
|---|---|
| No per-token cost; version pinned by us | A GPU host to provision, size, patch, and monitor |
| No document text leaves our infrastructure (§12 posture) | Ollama becomes a single point of failure for research *and* ingestion |
| MinIO gives one S3 API across all environments | An object store to operate, back up, and secure |

§13's managed-first principle still governs everything else: PostgreSQL, Redis, and Qdrant stay
managed, and **Kubernetes remains deliberately deferred**. Adding self-hosted model serving is not
licence to self-host the rest.

> Start with **managed services** and **Dockerized application/worker services**. **Kubernetes is
> deliberately deferred** until there is a demonstrated scaling requirement. (§13)

❗ §20: **"Do not over-engineer infrastructure. Docker + managed services first; scale only when
justified."**

The rationale: engineering effort in this project belongs in retrieval quality and evaluation, not in
cluster operations. Managed PostgreSQL, Redis, and Qdrant Cloud remove four operational surfaces
(backup, failover, upgrades, capacity) that contribute nothing to the Final Objective.

---

## Why the worker is a separate service

This appears in §13 as a deployment line and in §4 as an architectural requirement ("separate
ingestion workers from user-facing API processes"). It is the same principle in both places.

| | API | Research worker |
|---|---|---|
| Workload | Short, request-scoped | Multi-minute, multi-LLM-call |
| Scales with | Concurrent users | Concurrent research jobs |
| Failure impact | No new jobs accepted | Jobs queue; API unaffected |
| Resource profile | I/O bound | LLM-latency and CPU bound |

Sharing a process would couple HTTP timeouts to research depth and put the two on one scaling axis.

✅ **Resolved 2026-08-14 ([D-16](15-open-decisions.md)): separate workers.**

```
FastAPI
  ├── Ingestion Worker   (CPU, embedding generation, batch)
  └── Research Worker    (LLM, latency-sensitive, interactive, agent execution)
```

Different resource profiles and schedules — sharing an autoscaling group couples them for no gain.

---

## CI/CD pipeline (§14)

```
git push
  → GitHub Actions
  → Unit tests
  → Integration tests
  → Lint / format
  → Type checks
  → Evaluation smoke tests
  → Dependency / security scan
  → Docker build
  → Deploy
```

### The stage that makes this project different

**Evaluation smoke tests inside CI.** Retrieval quality is treated as a **build gate**, not a research
activity. A change that degrades Recall@K on the benchmark should fail the pipeline the same way a
broken unit test does.

This is the operational expression of §20's *"Do not hide retrieval quality. Benchmark it."*

✅ **Resolved 2026-08-14 ([D-28](15-open-decisions.md)), 🎛️ tunable:** every PR runs a **fixed
20-question subset**. Build fails on >5% regression in Recall@K, MRR, or citation correctness, or on
a test failure. Full benchmark runs nightly / on release.

---

## Environments (§14, §20)

> Use separate **development**, **staging**, and **production** environments.

❗ §20: **"Do not deploy straight to production. Use development → staging → production."**

| Environment | Purpose | Data |
|---|---|---|
| Development | Local iteration | Local Docker Compose stack; small corpus |
| Staging | Pre-production verification | Managed services mirroring production; benchmark corpus |
| Production | Real workloads | Managed services |

### Versioned configuration

> **Retrieval configurations and prompts should be versioned so experiments do not silently alter
> production behavior.** (§14)

This is enforced through cache identity — see [09-caching-and-prompts.md](09-caching-and-prompts.md).
Versioning and cache keys are the same mechanism from two angles.

---

## Local development stack

Not specified explicitly, but implied by the managed-service list. Docker Compose providing:

| Service | Local stand-in for |
|---|---|
| PostgreSQL | Managed PostgreSQL |
| Redis | Managed Redis |
| Qdrant | Qdrant Cloud |
| MinIO | **Production MinIO — same software, not a stand-in** |
| Ollama | Production Ollama — same software |
| Reranker server | Production reranker server |
| Prometheus + Grafana | Production metrics stack |

Note that Chroma is explicitly **not** a substitute for Qdrant in any environment beyond a temporary
local experiment (§5) — run real Qdrant locally.

💡 A quiet benefit of the 2026-08-14 stack: **most of the local stack is the production software, not
an emulation of it.** MinIO, Ollama, and the reranker are the same components locally and in
production, which removes a class of environment-specific bug that S3-vs-MinIO or
hosted-API-vs-local-model splits would introduce. Only PostgreSQL, Redis, and Qdrant differ, and only
in who operates them.

⚠ **Practical caveat:** the local stack now needs a GPU to be representative. On a CPU-only machine,
expect materially different latency — so any latency measurement taken locally is not evidence about
production, and [D-30](15-open-decisions.md) must be settled on real hardware.

---

## Repository structure (§15)

```
tradegraph/
  apps/
    api/                  # FastAPI
    web/                  # React + TypeScript
  src/
    graph/                # LangGraph state / nodes / edges
    agents/               # agent policies
    tools/                # SEC / news / market / quant tools
    rag/
      ingestion/
      chunking/
      embeddings/
      vector/
      bm25/
      hybrid/
      reranking/
      citations/
    quant/
    mcp/                  # ⚙ MCP servers — quant, market-data, [retrieval]
    prompts/              # versioned YAML, one dir per LLM-calling node
    models/
    cache/
    evaluation/
      benchmark/
      samples/
    observability/
    data/
  migrations/
  tests/
  docker/
  ops/                    # ⚙ Prometheus config, Grafana dashboards, Ollama modelfiles
  .github/workflows/
  .env.example
  pyproject.toml
  README.md
```

§15 notes this extends the source project's recommended organization of apps, graph, agents, tools,
RAG, models, evaluation, observability, data, tests, Docker, and environment configuration.

⚙ **Two directories are additions of 2026-08-14**, not in §15: `src/mcp/` and `ops/`. Both follow
from adopted technology that §15 predates.

- `src/mcp/` is kept **separate from `src/tools/` and `src/quant/`** on purpose: the servers are
  transport, the tools are capability. Mixing them makes [D-29](15-open-decisions.md) — which tools
  sit behind the protocol — expensive to revise.
- `ops/` holds infrastructure configuration that is neither application code nor Docker build
  context: Prometheus scrape config, Grafana dashboard JSON, Ollama modelfiles pinning model tags
  and generation defaults. ❗ Modelfiles belong in version control — a model tag is part of the run
  manifest ([17](17-ai-configuration-versioning.md)), and an unpinned tag makes every past result
  irreproducible.

### Reading the structure

The directory layout mirrors the architecture, and a few correspondences are worth noticing:

| Directory | Corresponds to | Doc |
|---|---|---|
| `src/graph/` | The LangGraph workflow — state, nodes, edges | [06](06-agent-langgraph.md) |
| `src/rag/` subdirectories | Each stage of the retrieval pipeline, in order | [04](04-ingestion-pipeline.md), [05](05-rag-retrieval-pipeline.md) |
| `src/rag/citations/` | Evidence chain and citation validation | [08](08-evidence-citations.md) |
| `src/prompts/` | One directory per LLM-calling graph node; versioned YAML | [09](09-caching-and-prompts.md), [17](17-ai-configuration-versioning.md) |
| `src/quant/` | The deterministic engine | [07](07-quant-engine.md) |
| `src/mcp/` ⚙ | MCP servers — transport, not capability | [14](14-mcp-assessment.md) |
| `src/evaluation/benchmark/` | The frozen benchmark dataset | [13](13-evaluation.md) |
| `src/observability/` | LangSmith + OTel + Prometheus wiring | [10](10-observability.md) |
| `ops/` ⚙ | Prometheus config, Grafana dashboards, Ollama modelfiles | [10](10-observability.md), [12](12-infrastructure-and-deployment.md) |
| `migrations/` | PostgreSQL schema — documents, claims, evidence, audits, **per-call accounting** | [08](08-evidence-citations.md), [09](09-caching-and-prompts.md) |

Note that `rag/` has a subdirectory per pipeline stage (`hybrid/`, `reranking/`, `citations/` are
separate from `vector/` and `bm25/`). That separation is deliberate: it keeps fusion, reranking, and
citation logic independently testable and independently ablatable, which is what §10 requires.

---

## Secrets and configuration

- `.env.example` documents every required variable **with no values** (§15, §12)
- Real values come from managed secret/environment configuration only (§12)
- Dependency/security scanning runs in CI (§14)

---

## Phasing

| Phase | Infrastructure deliverable |
|---|---|
| **Phase 0** | Repo structure, Docker Compose local stack (**including Ollama with pinned model tags**), CI skeleton, three environments defined |
| **V1–V3** | Services run locally and in development; reranker serving path settled ([D-30](15-open-decisions.md)); MCP servers appear in V3 alongside the quant tools |
| **V4** | Full production deployment per the §13 split, plus Ollama, reranker, MCP servers, Prometheus + Grafana; staging gates production |
| **V5** | Unchanged infrastructure; the phase is measurement, not scaling |

§16 places production deployment in V4. Note that Kubernetes appears in **no** phase — it enters only
if a scaling requirement is demonstrated (§13). ❗ The self-hosted model layer is *not* a
demonstrated scaling requirement; resist the pull from "we now run GPUs" to "we now need an
orchestrator."
