# 01 — System Architecture

> **Source:** Blueprint §1, §4–§9, §13.
> **Status:** Specification-derived. Tier labels and flow names are our organizing vocabulary; the
> components and their order are from the spec.

---

## The framing that determines everything else

> The final system is a **stateful research platform** rather than a query → retrieve → generate
> chatbot. (§1)

The specification calls out four consequences of that distinction: **explicit state**, **evidence
traceability**, **iterative research**, and **verification**. Nearly every structural decision below
follows from one of those four.

---

## 1. Six-tier architecture

```
┌─ Tier 1 · Client ────────────────────────────────────────────────────────┐
│  React + TypeScript + Tailwind                                           │
│  Research workspace · progress · evidence · charts                       │
└──────────────────────────────── HTTPS / SSE ─────────────────────────────┘
                                     │
┌─ Tier 2 · API ───────────────────────────────────────────────────────────┐
│  FastAPI  +  Auth  +  Rate Limits                                        │
│  Async API · streaming · job management                                  │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
┌─ Tier 3 · Data & model services ─────────────────────────────────────────┐
│  PostgreSQL        Redis         MinIO            Qdrant                 │
│  system of record  cache/queue   raw artifacts    vectors                │
│                                                                          │
│  Ollama → Qwen3 · Qwen3 Embedding        [Qwen3 Reranker — own server]   │
│  self-hosted model serving                                               │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
┌─ Tier 4 · Orchestration ─────────────────────────────────────────────────┐
│  Research Worker  →  LangGraph                                           │
│    Planner  →  Query Decomposer  →  Parallel Research                    │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                          LangChain tools ─ MCP client
                                     │
┌─ Tier 5 · Capability ────────────────────────────────────────────────────┐
│  SEC/Filings RAG │ News RAG │ Market Data │ Quant Tools                  │
│  Dense Retrieval + BM25  →  Reciprocal Rank Fusion  →  Reranker          │
│  MCP servers (co-located): quant · market-data · [retrieval]             │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
┌─ Tier 6 · Reasoning & verification ──────────────────────────────────────┐
│  Evidence Extraction → Claim/Evidence Graph → Verification               │
│  → Gap Detection → (Research Again ⟲  OR  Synthesis)                     │
│  → Critic → Citation Validator → Final Report                            │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                        PostgreSQL → API → Research Dashboard
```

The source architecture separates UI, API, LangGraph orchestration, LLM/RAG, tools,
PostgreSQL/Qdrant/Redis data services, and observability (§1).

Two elements above are **owner additions of 2026-08-14**, not in §1
([15](15-open-decisions.md)): self-hosted model serving in Tier 3, and the MCP boundary between
Tiers 4 and 5. Both are placements of things §1 implies but does not locate — §3's "provider
abstraction" needs a runtime, and §6's "explicit tool permissions" need an edge to be enforced at.
See [02](02-technology-stack.md) and [14](14-mcp-assessment.md).

❗ Note where Ollama sits: in the **data-and-model services tier**, alongside PostgreSQL and Qdrant.
It is infrastructure the worker depends on at runtime, with the same availability requirements —
not a library the worker contains.

---

## 2. Load-bearing architectural properties

### 2.1 Asynchronous by construction

The API **never runs research inline**. A request creates a *research job*; a separate **Research
Worker** process executes the LangGraph workflow; results stream back over SSE and land in
PostgreSQL.

The spec requires this in two places: §4 ("Separate ingestion workers from user-facing API
processes") and §13 (the research worker gets its own container/service).

**Why it exists:** agentic research is multi-minute, multi-LLM-call, and retry-prone. Running it in
an HTTP handler would couple request timeouts to research depth and would make the API's failure
domain identical to the agent's. Separating them means a crashed research job does not take down the
API, and the two can scale independently — the API scales with *users*, the worker scales with
*concurrent research jobs*.

### 2.2 State is a first-class artifact, not a conversation

§6 defines an explicit `ResearchState` with sixteen named fields. The workflow is a graph over that
state, not a message history. Iteration counters and budgets live *in state*, which is how
termination is enforced structurally rather than by hoping the model stops.

### 2.3 Two truth sources, deliberately separated

| Source of truth | Domain | Trust posture |
|---|---|---|
| Retrieved documents | Qualitative claims | **Untrusted data** (§12) |
| Quant Engine | All numbers | Deterministic, unit-tested |

❗ §7 and §20: *"Do not make the LLM the calculator."* The agent **chooses** a calculation; it never
**performs** one.

### 2.4 Verification is a stage, not a prompt instruction

Gap detection, contradiction detection, the critic, and the citation validator are **separate graph
nodes that can reject work** and route the graph back to retrieval. Verification implemented as
"please be accurate" inside a synthesis prompt would satisfy none of the §10 citation metrics.

### 2.5 Provenance is captured at write time, never reconstructed

❗ §8: *"Do not generate citations after writing the report. Build the evidence chain first."*
Provenance flows forward from ingestion (§4 metadata) through retrieval to evidence items to claims.
It is never inferred backwards from generated text.

---

## 3. Major subsystems

Nine subsystems, each with a distinct failure domain and its own reason to exist.

| # | Subsystem | Spec § | Owns | Detail doc |
|---|---|---|---|---|
| 1 | Frontend / Research Workspace | §1, §3 | Progress, evidence display, charts, SSE consumption | — |
| 2 | API Layer | §1, §3, §12 | Auth, rate limits, job management, streaming | — |
| 3 | Ingestion Pipeline | §4 | Corpus acquisition, parsing, versioning, indexing | [04](04-ingestion-pipeline.md) |
| 4 | Retrieval Subsystem | §5 | Hybrid search, fusion, reranking, compression | [05](05-rag-retrieval-pipeline.md) |
| 5 | Agent Orchestration | §6 | Graph state, node execution, research loop, guardrails | [06](06-agent-langgraph.md) |
| 6 | Quantitative Analysis Engine | §7 | All numerical truth | [07](07-quant-engine.md) |
| 7 | Evidence, Claims & Citations | §8 | Provenance chain, citation validation | [08](08-evidence-citations.md) |
| 8 | Caching & Prompt Management | §9 | Cache identity, prompt versioning, LLM call accounting | [09](09-caching-and-prompts.md) |
| 9 | Evaluation & Observability | §10, §11 | Benchmarks, metrics, traces | [13](13-evaluation.md), [10](10-observability.md) |

### 3.1 Frontend / Research Workspace

React + TypeScript + Tailwind. Renders **progress, evidence, and charts** (§3), consuming **SSE**
(§1). Streaming is architecturally required, not cosmetic: a research job produces intermediate
observable state — plan, sub-questions, evidence found, iteration count — that is useless if revealed
only at the end. TypeScript is required because evidence/claim/citation payloads are deeply
structured and must not be traversed untyped.

### 3.2 API Layer

FastAPI providing async API, auth, streaming, and **job management** (§3). It is a **control plane**,
not a compute plane: create job, stream job, read job/report/evidence, manage documents.

It owns:
- Authentication and authorization for research history and private documents (§12)
- Rate limiting and abuse controls (§12)
- Minting the `research_id` / `trace_id` that propagates through the whole system (§11)

### 3.3–3.9

Each has its own document; see the table above.

---

## 4. Data flows

### Flow A — Ingestion (offline, worker-driven)

```
SEC filings / earnings material / permitted news / market data
  → Source adapters
  → Raw object storage                    (immutable original: PDF / HTML / XBRL)
  → Parser + cleaner
  → Deduplication + document versioning   ← content_hash gate; enforces idempotency
  → Metadata extraction
  → Section-aware chunking
  → Embedding generation
  → Qdrant (vectors)  +  BM25 index (lexical)  +  PostgreSQL (metadata / provenance)
```

Two details carry weight:

- **The content hash is the idempotency key.** §4: "identical content must not be embedded twice."
- **Object storage holds the untouched original**, so any parse can be re-derived and audited without
  re-fetching from the source — which may have changed or become unavailable.

Full detail: [04-ingestion-pipeline.md](04-ingestion-pipeline.md).

### Flow B — Research (online, per job)

```
User question
  → FastAPI: authn/authz → rate limit → create research job (PostgreSQL) → return job id
  → SSE stream opens
  → Research Worker picks up job → LangGraph invoked with initial ResearchState
  → Planner            → research_plan
  → Query Decomposer   → sub_questions + retrieval_filters
  → Parallel Research (fan-out)
       ├─ Financial document retrieval (SEC / filings RAG)
       ├─ News / document retrieval
       ├─ Market-data analysis (quant tools, deterministic)
       └─ External tools
  → retrieved_documents
  → Evidence Extraction          → evidence[]
  → Verification
  → Gap / contradiction detection → contradictions[], confidence
  → Evidence sufficient?
       ├─ NO  → Research Again → Retrieval → Verification    ⟲ bounded by iteration/token/cost budget
       └─ YES → Synthesis → draft
  → Critic
  → Citation Validator            (claim-to-evidence entailment)
  → final_report
  → PostgreSQL → API → Research Dashboard
```

Full detail: [06-agent-langgraph.md](06-agent-langgraph.md).

### Flow C — Numerical (deterministic)

```
LangGraph tool call
  → Quant Engine
  → Market-data store
  → Deterministic calculation
  → Structured result
  → ResearchState.quantitative_results
```

Every number in a final report descends from Flow C. **None descends from an LLM call in Flow B.**

Full detail: [07-quant-engine.md](07-quant-engine.md).

### Flow D — Observability

```
research_id / trace_id minted at API
  → worker
  → graph nodes
  → tool calls  ─ including across the MCP boundary
  → stored final report + run manifest

  ⟂ traces   → LangSmith (AI layer) · OpenTelemetry (app layer)
  ⟂ metrics  → OpenTelemetry → Prometheus → Grafana
```

§11 requires this propagation so a production failure or a suspect number can be traced end to end,
and so a LangSmith agent trace can be correlated with an OpenTelemetry infrastructure trace.

The metrics branch is an owner addition: traces explain a single execution, but §10's System
metrics — latency, tokens, cost, error rate, cache hit rate — are aggregates over time and need a
store. See [10-observability.md](10-observability.md).

---

## 5. Process topology

| Process | Runs | Scales with | Failure impact |
|---|---|---|---|
| Frontend (static/edge) | Vercel or equivalent | Users | UI unavailable; jobs continue |
| FastAPI API | Container | Concurrent users / requests | No new jobs; running jobs continue |
| Research worker | Separate container | Concurrent research jobs | Jobs queue; API stays up |
| Ingestion worker | Separate from API (§4) | Corpus size / refresh rate | Corpus goes stale; research continues |
| ⚙ Ollama | GPU host | Concurrent LLM/embedding calls | ❗ **Research and ingestion both stop** |
| ⚙ Reranker server | Container (likely GPU) | Retrieval throughput | Retrieval precision degrades or the job fails |
| ⚙ MCP servers | Co-located with the research worker | Tool call volume | ❗ Affected tools unavailable; jobs must fail loudly |

✅ **Resolved 2026-08-14 ([D-16](15-open-decisions.md)): separate deployables.** Different resource
profiles (embedding throughput vs LLM latency) and schedules (batch vs on-demand) — sharing an
autoscaling group would couple them for no gain.

❗ **Self-hosting adds a new critical path.** Ollama is the first component in this table whose
failure stops *both* research and ingestion — a coupling the hosted-API alternative did not have.
Health checks, capacity sizing, and loud failure are therefore not optional
([D-30](15-open-decisions.md)).
