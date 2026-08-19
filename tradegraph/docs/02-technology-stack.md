# 02 — Technology Stack & Rationale

> **Source:** Blueprint §3, §5, §6, §11, plus the owner stack decision of **2026-08-14**
> ([15](15-open-decisions.md)).
> **Status:** The stack table and stated purposes are from §3. Concrete implementations for the slots
> §3 left abstract are the owner decision and are marked ⚙. The "problem it solves" column is our
> architectural justification, tested against the governing principle below.

---

## The test every technology must pass

> **Every technology must solve a real architectural problem. Do not add technologies merely to
> increase the stack.** (Blueprint design principle)

Below, each stack entry is stated with its §3 purpose and then justified against that test. Four
entries — Ollama, MCP, Prometheus, Grafana — are **not in §3** and are marked ⚙. Each carries an
explicit justification against the principle, because that is the standard the specification sets for
additions.

---

## The chosen stack, in one line

```
Qwen3 + Ollama → Qwen3 Embeddings → Qdrant + BM25 → Qwen3 Reranker
  → LangChain → LangGraph → MCP
  → PostgreSQL → Redis → MinIO
  → LangSmith + OpenTelemetry + Prometheus + Grafana
  → Docker → GitHub Actions
```

Read left to right this is the request path: model serving, then indexing, then retrieval, then
orchestration, then the tool boundary, then state, then observation, then delivery.

---

## Full stack

| Layer | Technology | §3 stated purpose | The problem it solves |
|---|---|---|---|
| Language | **Python** | LLM, RAG, evaluation, data and quantitative ecosystem | The only ecosystem where the LLM/RAG stack *and* the quant stack (Polars/Pandas/NumPy) are both native. Avoids a two-language split across the system's two truth sources. |
| Frontend | **React + TypeScript + Tailwind** | Research workspace, progress, evidence, charts | Research output is not a chat bubble — it is a document with evidence panels, charts, and live progress. TypeScript because evidence/claim/citation payloads are deeply nested and must not be traversed untyped. |
| API | **FastAPI** | Async API, auth, streaming, job management | Native async + SSE for long-running jobs. Pydantic gives request/response validation *and* the structured-output contracts §6 requires between nodes. |
| LLM framework | **LangChain** | Models, prompts, tools, retrievers, structured output | Component abstraction so graph nodes are not hand-rolling provider APIs, retriever plumbing, and output parsing. Lives *inside* nodes — see the split below. |
| Agent workflow | **LangGraph** | State, branching, loops, checkpoints, controlled orchestration | The research loop is **cyclic and stateful**. A chain or DAG cannot express "evidence insufficient → research again." Checkpoints let a multi-minute job survive worker failure. |
| LLM | **Qwen3**, behind the §3 provider abstraction | Keep model layer replaceable | §3 deliberately names no provider, because model quality and price move faster than the architecture. **The abstraction is retained** — Qwen3 is the configured implementation, not a hardcoded dependency — so the §10 ablation matrix can still swap in a hosted model for comparison. ✅ [D-1](15-open-decisions.md). |
| ⚙ Model serving | **Ollama** | *(not in §3)* | Something must serve a self-hosted model, and §3's "provider abstraction" describes an interface, not a runtime. Ollama supplies model pull/pin/version management and an OpenAI-compatible endpoint, so the provider abstraction has a concrete backend without bespoke inference plumbing. Passes the principle: without it, the D-1 choice has no implementation. ⚠ [D-30](15-open-decisions.md). |
| Embeddings | **Qwen3 Embedding** (self-hosted via Ollama) | Dense semantic retrieval | Semantic recall over paraphrased financial language ("margin compression" ↔ "gross margin declined"). Self-hosting removes per-call cost and pins the version to us — which matters because §9 invalidates the embeddings cache and forces a full re-embed on any model change. ❗ Pin the output dimension before creating the Qdrant collection. ✅ [D-2](15-open-decisions.md). |
| Vector DB | **Qdrant** | Vector search **+ metadata filtering** | The filtering half is the real reason. Retrieval must be constrained by company / ticker / period / doc-type **at query time**; post-filtering a top-k destroys recall for exactly the questions this product exists to answer. |
| Sparse retrieval | **BM25** | Exact names, tickers, identifiers, financial terminology | Embeddings blur exact tokens, and finance is made of them: `NVDA`, `Item 7A`, `non-GAAP`, `ASC 606`. Complements dense recall rather than competing with it. ⚠ See [D-3](15-open-decisions.md). |
| Reranker | **Qwen3 Reranker** *(fills §3's "BGE / equivalent" slot)* | Second-stage relevance ranking | Bi-encoders score query and passage independently, so the top of the list is noisy. This reranker scores query and passage **jointly**, giving far higher precision — affordable only over a bounded Top-N candidate set, which is why the pipeline produces one. Keeping the reranker in the same model family as the embedder keeps one vendor surface and one licence to track. ❗ Ollama has no rerank endpoint — see [D-30](15-open-decisions.md). |
| RDBMS | **PostgreSQL** | Users, jobs, documents, claims, evidence, reports, **audits** | The system of record for provenance. The claim/evidence graph is relational. The listed `audits` entity means the DB is expected to answer *"why did the system say this?"* long after the job finished. |
| Cache/queue | **Redis** | Caching, rate limits, background jobs, transient state | Four distinct roles: the four §9 cache layers, the §12 API rate limiter, the job queue feeding the research worker, and transient job state. ⚠ See [D-8](15-open-decisions.md). |
| Raw storage | **MinIO** (S3-compatible) | Original filings, PDFs, processed artifacts | Immutable originals make parsing re-derivable and provenance verifiable; large binaries do not belong in PostgreSQL. MinIO keeps one S3 API across local, staging, and production, so no code path differs by environment — and it keeps the corpus on our own infrastructure, consistent with local model serving. |
| ⚙ Tool boundary | **MCP** | *(not in §3)* | §6 and §12 require narrow, explicit tool permissions and validated tool arguments; §3 offers no boundary at which to enforce them, so today they are enforced by convention inside application code. MCP makes the tool edge an actual process boundary, and makes the §7 engine reusable outside TradeGraph. It sits **underneath** the LangChain tool interface, so the §6 framework split is untouched. ✅ [D-9](15-open-decisions.md) · detail [14](14-mcp-assessment.md). |
| Quant | **Polars/Pandas + NumPy** | Returns, volatility, event studies, backtesting | Deterministic, unit-testable numerics — the numerical source of truth mandated by §7 and §20. |
| AI observability | **LangSmith** | LLM/graph traces | Why the *agent* behaved as it did: node sequence, prompt version, tool selection, loop count. |
| App observability | **OpenTelemetry** | Application traces | Vendor-neutral instrumentation for the API, worker, and data hops. Emits both traces and metrics; **stores neither**. |
| ⚙ Metrics store | **Prometheus** | *(not in §3)* | OTel is an instrumentation SDK, not a backend — the §10 System metrics (latency, tokens, cost, error rate, cache hit rate) have nowhere to live and nothing to query them. Prometheus supplies the time-series store, query language, and alerting the metric list implies. Passes the principle: without it §10's system metrics are emitted and discarded. ⚠ [D-31](15-open-decisions.md). |
| ⚙ Dashboards | **Grafana** | *(not in §3)* | Prometheus stores and queries; it does not present. §10 requires system behaviour to be *observable*, and the Final Objective requires explaining "how the production system behaves under real workloads" — which needs a surface a human reads. ⚠ [D-31](15-open-decisions.md). |
| Containers | **Docker** | Reproducible builds and deployment | API and worker are separate services with different scaling and failure profiles. Identical images across development → staging → production (§20). |
| CI/CD | **GitHub Actions** | Test, lint, build, scan, deploy | Enforces the §14 gate chain — including **evaluation smoke tests** — before anything reaches an environment. |

---

## The LangChain / LangGraph split

This is the most commonly botched part of a LangChain + LangGraph build, and §6 is explicit about it:

> LangChain should live **inside graph nodes** for model, prompt, tool, retriever, loader, and
> structured-output components; LangGraph controls **how those components execute** as a stateful
> workflow.

| | LangChain | LangGraph |
|---|---|---|
| Role | Component library | Control flow |
| Provides | Models, prompts, tools, retrievers, loaders, structured output | State, branching, loops, checkpoints |
| Scope | Inside a single node | Across nodes |
| Answers | "How do I call the model and parse its output?" | "Which node runs next, and with what state?" |

Neither owns the other's job. If graph routing logic starts appearing inside a LangChain chain, or if
prompt/parser plumbing starts appearing in edge conditions, the split has been violated.

---

## Why four observability tools and not one

§11 mandates two. The stack decision adds two more. They divide along **two independent axes** —
*which layer* is being observed, and *whether the signal is a trace or a metric* — and no tool covers
both cells of both axes.

|  | AI / agent layer | Application / infra layer |
|---|---|---|
| **Traces** (one execution, in detail) | **LangSmith** | **OpenTelemetry** |
| **Metrics** (aggregate, over time) | *(fed via OTel)* → **Prometheus** → **Grafana** | **Prometheus** → **Grafana** |

- *"Why did the agent choose the wrong tool on iteration 3?"* → **LangSmith**
- *"Why did p99 latency triple at 14:00?"* → **OpenTelemetry** traces, found via a **Grafana** alert
- *"Is our cache hit rate trending down this week?"* → **Prometheus/Grafana** — no trace answers this

❗ The distinction that justifies the addition: **a trace explains one request; it cannot tell you a
rate is degrading.** §10 lists latency, token usage, cost, error rate, and cache hit rate as tracked
System metrics — all of them aggregates over time. LangSmith and OTel alone produce those numbers and
then drop them.

OpenTelemetry is the **instrumentation**; Prometheus is the **store**; Grafana is the **surface**.
They are one pipeline, not three competing tools.

The `research_id` / `trace_id` (§11) is what lets you cross between the layers. Detail:
[10-observability.md](10-observability.md).

---

## What local-first serving changes

Choosing Qwen3 on Ollama over a hosted API is not a drop-in substitution. Four consequences
propagate through the architecture:

| Consequence | Where it lands |
|---|---|
| **No per-token invoice** — but §6 makes `cost_budget` an enforced state field and §10 lists cost as a metric | Cost becomes an **imputed** figure (tokens × configured rate) recorded alongside real wall-clock and compute time → [17](17-ai-configuration-versioning.md) |
| **Weaker strict structured output** — §6 mandates typed handoffs between every node | Constrained decoding or validate-and-retry becomes required, not a nicety → [06](06-agent-langgraph.md) |
| **Bounded serving concurrency** — §6's Parallel Research fan-out assumes branches run concurrently | If LLM calls serialize behind one Ollama instance, fan-out latency becomes the *sum* of branches, not the max → ⚠ [D-30](15-open-decisions.md) |
| **No document text leaves our infrastructure** | A material improvement to the §12 posture: the untrusted-content threat surface stays internal, and private documents never transit a third party → [11](11-security-and-safety.md) |

The third is the one to measure early. The fourth is a genuine gain the specification did not ask for
but clearly benefits from.

---

## Explicitly excluded technologies

| Technology | Status | Reason |
|---|---|---|
| **Chroma** | Not required (§5) | Qdrant is the primary vector store for the final production architecture. Chroma may be used **only** as a temporary local prototype if it accelerates an experiment. |
| **Kubernetes** | Deliberately deferred (§13) | Until there is a *demonstrated* scaling requirement. Engineering effort belongs in retrieval quality and evaluation, not cluster operations. §20: "Do not over-engineer infrastructure." |
| **Graph database** | Not in the stack | §3 assigns `claims` and `evidence` to PostgreSQL. The "claim/evidence graph" of §8 is a conceptual graph, not necessarily a graph store. ⚠ See [D-7](15-open-decisions.md). |
| **LangSmith as a runtime prompt store** | Ruled out 2026-08-14 | Git is the production source of truth for prompts. Pulling prompts from a service at runtime breaks reproducibility, bypasses review, and makes an external system a dependency of the research loop → [17](17-ai-configuration-versioning.md). |

*(MCP was previously listed here as excluded. It was adopted on 2026-08-14 — see
[14](14-mcp-assessment.md).)*

---

## Every stack entry, resolved (2026-08-14)

All 32 decisions in [15-open-decisions.md](15-open-decisions.md) are now 🟢 resolved. The entries
below were unpinned when this document was first written; they are not anymore.

| Entry | Resolved to | 🔒/🎛️ |
|---|---|---|
| LLM provider abstraction | Qwen3 via Ollama, per-node model tiering | 🔒 provider / 🎛️ size — [D-1](15-open-decisions.md) |
| Embedding model | Self-hosted Qwen3-Embedding-0.6B | 🔒 — [D-2](15-open-decisions.md) |
| BM25 | **Qdrant native sparse vectors** | 🔒 — [D-3](15-open-decisions.md) |
| Redis queue | **Celery + Redis** | 🔒 — [D-8](15-open-decisions.md) |
| LangGraph checkpointer | **PostgreSQL** | 🔒 — [D-10](15-open-decisions.md) |
| Market-data provider & store | Adapter-based free provider; PostgreSQL + MinIO/Parquet; raw-plus-adjustment-metadata policy | 🔒 contract / 🎛️ vendor — [D-6](15-open-decisions.md) |
| Reranker | Qwen3-Reranker, own serving path (not Ollama) | 🔒 — [D-30](15-open-decisions.md) |
| Object storage | MinIO | 🔒 |
| MCP servers | `quant` first; retrieval deliberately excluded; stdio (dev) / local HTTP (prod) | 🔒 — [D-29](15-open-decisions.md) |
| Prometheus/Grafana | Metric families and label discipline fixed | 🔒 labels / 🎛️ dashboards — [D-31](15-open-decisions.md) |
| Ollama model sizing | Smaller models for extraction/rewrite nodes, stronger for verify/critic/synthesize/validate | 🎛️ pending hardware benchmark — [D-30](15-open-decisions.md) |
| Auth / tenancy | JWT + multi-tenant, filters enforced in PostgreSQL **and** Qdrant **and** sparse retrieval | 🔒 — [D-11](15-open-decisions.md) |

See [15-open-decisions.md](15-open-decisions.md) for the full resolution text and the 🔒-locked vs
🎛️-tunable distinction that governs how each of these may change later.
