# 15 — Architectural Decisions

> **Source:** Gaps and forks identified in the two source documents, resolved by the owner across two
> sessions on **2026-08-14**.
> **Status:** ⚠ Nothing in this document is a specification requirement. Every entry below is either
> something the specification leaves unpinned or a fork it does not resolve — the specification itself
> is unchanged and remains authoritative for everything it *does* state. All 32 decisions are now
> 🟢 **Resolved**.

---

## How to use this document

**Do not re-litigate a resolved decision inside implementation code.** If an entry here conflicts
with something that seems easier to build, the entry wins; raise it here first if it needs to change.

| Status | Meaning |
|---|---|
| 🟢 Resolved | Decided. The resolution is binding for implementation. |
| 🔒 Locked | Resolved **and** architectural — changing it later means a migration, not a config edit. |
| 🎛️ Tunable | Resolved **as a versioned default** — expected to change under benchmark evidence, and every change is a tracked, cache-invalidating event. |

### ❗ The distinction that matters most in this document

> *"I would not say every one of these decisions is permanently immutable... The architecture is
> locked; the performance parameters are experimentally tunable."*

Two different kinds of "resolved" appear below, and treating them the same is a mistake:

| 🔒 Locked | 🎛️ Tunable |
|---|---|
| LLM provider, embedding model, vector DB, sparse retrieval engine, checkpointer backend, tool protocol, auth model, object storage, job queue | Chunk size/overlap, retrieval top-k, reranker top-N, model size per node, cache TTLs, guardrail limits, CI thresholds |
| Changing it means a migration: re-embed the corpus, re-index, rewrite the tenancy model | Changing it means shipping a new version and re-measuring against the frozen benchmark |
| Decided once, by architecture | Decided repeatedly, by evidence |
| A "should we switch to X" conversation | A "did the benchmark improve" conversation |

Every entry below is marked 🔒 or 🎛️ so this stays visible at the point of use, not just here.

---

## Resolution log

### 2026-08-14, session 1 — Stack decision (owner)

Chose the concrete stack and a configuration-versioning architecture. Resolved
[D-1](#d-1--llm-provider-and-per-node-model-policy), [D-2](#d-2--embedding-model--self-hosted-vs-api),
[D-9](#d-9--mcp-adoption), [D-25](#d-25--prompt-versioning-scheme),
[D-26](#d-26--where-per-call-llm-accounting-is-stored). Opened
[D-29](#d-29--mcp-server-scope-and-transport)–[D-32](#d-32--experiment-record-storage). Recorded in
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md) and
[14-mcp-assessment.md](14-mcp-assessment.md).

### 2026-08-14, session 2 — Full resolution (owner)

Every remaining decision resolved in one pass: **D-3 through D-24, D-27 through D-32**, plus
concrete detail added to the session-1 resolutions (per-node model tiering for D-1, hardware-gated
model sizing for D-30, dev/prod transport split for D-29). This closes the decision register —
**32 of 32 resolved.** The full text of each resolution is below; this log records only that the
session happened and what changed the *architecture* rather than a *parameter*:

| Newly locked (🔒) | Newly tunable (🎛️) |
|---|---|
| BM25 → Qdrant native sparse | Chunk size/overlap/table handling (D-19) |
| Checkpointer → PostgreSQL (D-10) | Retrieval top-k, RRF, rerank top-N (D-20) |
| Job queue → Celery + Redis (D-8) | Guardrail limits — iterations, tool calls, tokens (D-21) |
| Auth → JWT + multi-tenant, filters reach Qdrant/BM25 (D-11) | Cache TTLs (D-24) |
| Evidence graph → PostgreSQL relational (D-7) | Benchmark company count — starts at 10 (D-18) |
| Market-data adjustment policy: raw + metadata, never silently mixed (D-6) | Per-node Qwen3 model size (D-30, pending hardware benchmark) |
| MCP transport: stdio (dev) / local HTTP (prod) (D-29) | CI smoke thresholds — 20 questions, 5% regression gate (D-28) |
| "External tools" branch removed; replaced by named tools (D-4) | Numeric guardrails, quant annualization conventions (D-21, D-22) |

---

## Decisions

### D-1 · LLM provider and per-node model policy
🟢 Resolved · 🔒 **Locked:** provider = local Qwen3 via Ollama · 🎛️ **Tunable:** which size per node
· **Docs:** [02](02-technology-stack.md), [06](06-agent-langgraph.md)

**Resolution:** Local **Qwen3**, served by **Ollama**, behind an `LLMProvider` abstraction — the
abstraction stays real, not decorative, so a hosted model can still be swapped in for an ablation.

**Per-node tiering** — not one model everywhere:

| Node | Tier | Why |
|---|---|---|
| Planner | Smaller/faster | Structured, bounded task — decompose a goal into a plan |
| Query Rewriter | Smaller/faster | Same shape: transform, don't reason deeply |
| Evidence Extractor | Smaller/faster | Extraction against retrieved text, not open synthesis |
| Verifier | Stronger | Judges whether evidence actually supports usage |
| Critic | Stronger | Adversarial review — the point is to catch what a weak model would miss |
| Synthesizer | Stronger | Writes the report; quality here is the product |
| Citation Validator | Stronger | Entailment judgement gates what ships — [D-23](#d-23--entailment-judgement-for-citation-validation) |

Exact sizes and quantization are pinned in [D-30](#d-30--ollama-serving-topology-and-per-node-model-sizing)
after hardware benchmarking — this decision fixes the *policy* (tier by node importance), not the
*number*.

**Consequences carried forward:**
- ❗ No per-token invoice, but `cost_budget` is still an enforced state field (§6). Cost is recorded
  as **imputed** (tokens × configured rate) — [17](17-ai-configuration-versioning.md).
- Local models are weaker at strict structured output (§6 mandates typed node handoffs) →
  constrained decoding or validate-and-retry is required, not optional.
- No document text leaves the infrastructure — strengthens the §12 posture.

---

### D-2 · Embedding model — self-hosted vs API
🟢 Resolved · 🔒 **Locked:** self-hosted, this model family · 🎛️ **Tunable:** which size variant

**Resolution:** Self-hosted **Qwen3-Embedding-0.6B** to start.

```
EmbeddingProvider
      ↓
Qwen3-Embedding-0.6B
      ↓
Qdrant
```

Larger Qwen3 embedding variants are benchmarked later — that comparison is cheap to run because the
provider sits behind an abstraction, but **switching the active model is not cheap to ship**: it
invalidates every vector and the whole embeddings cache (§9), forcing a full re-embed. This is why
the variant choice is 🎛️ tunable in principle but 🔒 locked in practice once the corpus is built —
treat any change as a migration.

❗ **Pin the output dimension before creating the Qdrant collection.** The model supports Matryoshka
truncation, so dimension is a *choice*. The pinned model tag and dimension are part of the run
manifest — [17](17-ai-configuration-versioning.md).

---

### D-3 · BM25 implementation
🟢 Resolved 🔒 **Locked** · **Docs:** [04](04-ingestion-pipeline.md), [05](05-rag-retrieval-pipeline.md)

**Resolution: Qdrant native sparse-vector retrieval.** Not `rank_bm25`, not a separate OpenSearch /
Elasticsearch deployment.

```
                Metadata Filter
                      │
                ┌─────┴─────┐
                ▼           ▼
              Dense       Sparse / BM25
              Qdrant       Qdrant
                └─────┬─────┘
                      ▼
                     RRF
```

The **same canonical metadata filter** is applied to both arms — one datastore, one filter language,
so filter parity is structural rather than a thing to maintain by discipline. This directly satisfies
the §5 correctness constraint: divergent filter semantics between dense and sparse arms is a silent
bug that RRF hides.

Reopen only if benchmark results show sparse-vector quality is materially inadequate — that is the
one condition under which OpenSearch/Elasticsearch gets reconsidered.

---

### D-4 · The "External tools" branch
🟢 Resolved 🔒 **Locked** · **Docs:** [06](06-agent-langgraph.md), [11](11-security-and-safety.md)

**Resolution: remove the generic `external_tools` branch.** Replace it with explicitly named,
individually permissioned tools:

```
quant tools
market_data tools
SEC/XBRL tools
web/news tools   — only when explicitly enabled
```

No `external_tool()` catch-all, ever. Every named tool gets an explicit schema, explicit permission,
explicit cost accounting, and explicit provenance — which is the actual fix for the security-relevant
gap the original spec review flagged: an undefined branch is an undefined permission, cost, and
injection surface. Naming the tools closes all three at once.

---

### D-5 · Human review path — trigger and mechanism
🟢 Resolved 🔒 **Locked** (mechanism) / 🎛️ **Tunable** (thresholds) · **Docs:** [06](06-agent-langgraph.md), [11](11-security-and-safety.md)

**Resolution:** LangGraph **interrupt + checkpoint**, not a separate workflow engine.

**Trigger** — any one of:

```
LOW CONFIDENCE
OR UNRESOLVED CONTRADICTION
OR CITATION VALIDATION FAILURE
OR HIGH-IMPACT QUANT/RESEARCH OUTPUT
OR BACKTEST RESULT REQUIRING REVIEW
```

**Flow:**

```
Research → Verification → Needs Human Review?
    ├── NO  → Continue
    └── YES → INTERRUPT → UI → Approve / Reject / Request Research → Resume
```

Built on the same checkpoint mechanism as [D-10](#d-10--langgraph-checkpointer-backend) — no
second persistence layer for paused jobs. 🎛️ The specific confidence threshold and what counts as
"high-impact" are tunable parameters, set initially by judgement and revised once real reports exist
to calibrate against.

---

### D-6 · Market-data provider, storage, and adjustment policy
🟢 Resolved 🔒 **Locked** (contract) / 🎛️ **Tunable** (provider, thresholds) · **Docs:** [03](03-data-sources.md), [07](07-quant-engine.md)

**⚠ This was the largest gap in the source documents. It is now fully specified.**

**Provider** — behind an adapter, not a hard dependency:

```
MarketDataProvider
       │
       └── FreeProvider
```

**Storage** — split by access pattern:

```
Provider → Validation → PostgreSQL (canonical structured) + MinIO/Parquet (bulk/historical)
```

**🔒 Point-in-time correctness** — every record carries `timestamp`, `observed_at`, `effective_at`,
`source`. Backtests may only use information available **at the simulated timestamp** — this is the
structural defence against look-ahead bias that §7 requires.

**🔒 Corporate actions** — store **raw/unadjusted data plus adjustment metadata**. Every calculation
explicitly selects `raw` or `adjusted`. ❗ **Never silently mix them** — this is the single most common
source of a wrong Sharpe ratio in practice.

**🔒 Missing data** — fail loudly for required calculations. Optional analysis may explicitly report
missing observations, but never interpolate silently into a number that reaches a report.

**🎛️ Benchmark and risk-free rate** — default **S&P 500 / SPY** as the equity benchmark; a US
Treasury-based series for the risk-free rate, with the **exact series identifier recorded in the run
manifest** so a Sharpe ratio computed today is reproducible against the same rate a year from now.

The governing rule: **source, adjustment policy, and point-in-time behaviour are recorded, never
hidden.** That is what §7's no-look-ahead and no-survivorship-bias requirements actually depend on.

---

### D-7 · Evidence graph representation
🟢 Resolved 🔒 **Locked** · **Docs:** [08](08-evidence-citations.md)

**Resolution: PostgreSQL relational tables.** No Neo4j, no separate graph database.

```
documents ──< chunks ──< evidence_items ──< claim_evidence >── claims ──< citations
                                                                  │
                                                              reports
```

`claims`, `evidence`, `citations`, `documents`, `chunks`, `reports`, related by foreign key. The
"graph" in §1's Claim/Evidence Graph describes the **shape of the data**, not a required storage
engine — and §3 already assigns these entities to PostgreSQL.

---

### D-8 · Job queue mechanism
🟢 Resolved 🔒 **Locked** · **Docs:** [02](02-technology-stack.md), [12](12-infrastructure-and-deployment.md)

**Resolution: Celery + Redis.**

```
FastAPI → Redis → Celery Worker → LangGraph
```

Chosen for a mature Python ecosystem, built-in retries, task visibility, worker separation, and
native scheduled/background-job support — all needed and none worth building by hand.

**LangGraph checkpoints stay in PostgreSQL** ([D-10](#d-10--langgraph-checkpointer-backend)), not
Redis:

```
Redis/Celery   → job transport (transient)
PostgreSQL     → durable graph state
```

---

### D-9 · MCP adoption
🟢 Resolved 🔒 **Locked** · **Docs:** [14](14-mcp-assessment.md)

**Resolution: adopt MCP**, sitting underneath the LangChain tool interface:

```
LangGraph → LangChain Tool interface → MCP Client → MCP Server → Actual tool
```

The graph must not care whether a tool is local or MCP-mediated — that indifference is what keeps
[D-29](#d-29--mcp-server-scope-and-transport) cheap to revise. Full reasoning, scope, and the six
specification constraints that must survive the protocol boundary:
[14-mcp-assessment.md](14-mcp-assessment.md).

---

### D-10 · LangGraph checkpointer backend
🟢 Resolved 🔒 **Locked** · **Docs:** [06](06-agent-langgraph.md)

**Resolution: PostgreSQL.**

```
LangGraph → PostgreSQL Checkpointer
```

Redis stays scoped to transient state (§9). A research job must survive a worker restart, a process
crash, a deployment, a retry, or a human-review interruption ([D-5](#d-5--human-review-path--trigger-and-mechanism)) —
"persistent research state" (§17) means durable, and only PostgreSQL is durable here.

---

### D-11 · Authentication and tenancy model
🟢 Resolved 🔒 **Locked** · **Docs:** [11](11-security-and-safety.md)

**Resolution: JWT + multi-tenant.**

```
User → Tenant → Research / Documents / Reports
```

Every private resource carries a `tenant_id`. ❗ **Enforcement is not optional at any one layer** —
it must hold at all three simultaneously:

```
PostgreSQL filter  +  Qdrant filter  +  Sparse-retrieval filter
```

Securing PostgreSQL rows while leaving retrieval unfiltered leaks private documents through the
search path regardless of how well the API is locked down. This was flagged as expensive-to-retrofit
in the original decision review — it is now decided precisely so it can be designed in from V1, even
though full auth ships later.

---

### D-12 · Contradiction detection method
🟢 Resolved 🔒 **Locked** (method) / 🎛️ **Tunable** (thresholds) · **Docs:** [08](08-evidence-citations.md)

**Resolution: both**, in a fixed order — never LLM judgement alone for numbers.

```
Numeric contradiction check (same company/metric/period, different values)
      → deterministic comparison
                ↓
Qualitative contradiction check (Claim A vs Claim B)
      → LLM judgment
                ↓
        Contradiction record
```

❗ **Never silently average conflicting financial evidence.** The deterministic pass runs first
because it is cheap and catches the conflicts that matter most in financial documents; the LLM pass
only handles what the deterministic check structurally cannot.

---

### D-13 · News source licensing
🟢 Resolved 🔒 **Locked** · **Docs:** [03](03-data-sources.md)

**Resolution: no arbitrary full-text news ingestion for V1/V2.**

Ingest freely: SEC filings, company IR materials, public filings. For news specifically, store only:

```
metadata + headline + source URL + permitted excerpt (where the licence explicitly allows it)
```

Full text is stored **only** where a source's licence or terms explicitly permit it. This keeps the
architecture independent of questionable scraping and unblocks V2 news ingestion without a
per-source legal review turning into a hard dependency.

---

### D-14 · Benchmark ground truth authorship
🟢 Resolved 🔒 **Locked** (process) / 🎛️ **Tunable** (question count, over time) · **Docs:** [13](13-evaluation.md)

**Resolution: authored in-house, manually verified.**

Starting size: **50–100 questions**, spanning factual, comparative, temporal, multi-document,
financial-metric, and evidence/contradiction categories.

| Metric family | Ground truth required |
|---|---|
| Retrieval (Recall@K, MRR, nDCG) | Gold relevant chunks |
| Generation (faithfulness, answer relevance) | Gold/reference answers |

❗ Important questions are **manually verified** — no LLM-generated benchmark becomes the sole source
of ground truth for the numbers the project reports its own success against.

---

### D-15 · Missing source document
🟢 Resolved 🔒 **Locked** · **Docs:** [README](README.md)

**Resolution:** `TradeGraph_Final_Production_Project_Blueprint.pdf` **is** the current authoritative
specification. The referenced-but-absent "ResearchGraph" source is treated as historical context
only, not a binding document to chase down.

**Action:** keep the authoritative docs where they are (`docs/`), and remove the meaningless broken
`filecite` citation markers from any generated text — they point at nothing in this repository and
should not be treated as evidence of missing content.

---

### D-16 · Worker topology — ingestion vs research
🟢 Resolved 🔒 **Locked** · **Docs:** [01](01-system-architecture.md), [12](12-infrastructure-and-deployment.md)

**Resolution: separate workers.**

```
FastAPI
  ├── Ingestion Worker   (CPU, embedding generation, batch)
  └── Research Worker    (LLM, latency-sensitive, interactive, agent execution)
```

Different workloads, different scaling axes, different failure domains — sharing an autoscaling
group would couple them for no benefit.

---

### D-17 · Macro data summarized into RAG
🟢 Resolved 🔒 **Locked** (default) · **Docs:** [03](03-data-sources.md)

**Resolution: no, by default.** Macro data (rates, CPI, GDP) stays in the quantitative/data layer.
Convert it into retrievable RAG text **only** when a benchmark question demonstrates that textual
macro context is actually needed — this avoids turning every numerical dataset into unnecessary
retrieval surface area.

---

### D-18 · Size of the benchmark company set
🟢 Resolved 🎛️ **Tunable** (expand later) · **Docs:** [03](03-data-sources.md), [13](13-evaluation.md)

**Resolution: start with 10 companies.**

```
AAPL · MSFT · NVDA · AMZN · GOOGL · META · TSLA · JPM · V · WMT
```

Ten is enough to exercise company filtering, comparative research, cross-sector terminology, and
cross-company queries without front-loading the full labeling cost before retrieval is even proven.
Expand once V1 retrieval metrics are stable.

---

### D-19 · Chunking parameters
🟢 Resolved 🎛️ **Tunable** — a versioned V1 baseline, not a final answer · **Docs:** [04](04-ingestion-pipeline.md)

**V1 baseline:**

| Parameter | Value |
|---|---|
| Chunk size | 700 tokens |
| Overlap | 100 tokens |
| Mode | Section-aware |

**Preserved boundaries:** document · section · subsection · page · table.

**Tables get special handling — never destroyed by ordinary text chunking.** Represent them as
structured, table-aware chunks carrying:

```
table title · headers · rows · source page · section
```

Financial filings are dense with tables; a naively chunked table is unusable as evidence and
uncitable, which directly undermines the §8 citation chain this project is built around. Then
benchmark chunk size, overlap, and table strategy against the frozen benchmark — this baseline is a
starting point to beat, not a resolution to defend.

---

### D-20 · Retrieval configuration values
🟢 Resolved 🎛️ **Tunable** — versioned V1 defaults · **Docs:** [05](05-rag-retrieval-pipeline.md)

**V1 baseline:**

| Parameter | Value |
|---|---|
| Dense top-K | 30 |
| Sparse (BM25) top-K | 30 |
| Fusion | Standard RRF |
| Candidate set | ~30–50 unique chunks |
| Reranker top-N | 7 |
| Final context | 5–7 passages |

Empirical tuning against the frozen benchmark is mandatory (§20 — no optimization by intuition), and
runs through the seven ablations, starting with dense vs BM25 vs hybrid vs hybrid+reranker. The
retrieval config **version** is part of the retrieval cache key (§9), so every change here is a
tracked, cache-invalidating event by design — that is what makes 🎛️ tunable safe rather than reckless.

---

### D-21 · Numeric / agent guardrail limits
🟢 Resolved 🎛️ **Tunable** — recalibrate once real usage exists · **Docs:** [06](06-agent-langgraph.md), [11](11-security-and-safety.md)

**Initial limits:**

| Guardrail | Value |
|---|---|
| Max research iterations | 5 |
| Max tool calls | 20 |
| Max parallel branches | 3 |
| Max LLM calls | 30 |
| Max context tokens | Model-dependent |

With a self-hosted model, "cost" is composite: **estimated compute cost + token usage + wall-clock
time** — there is no invoice to read a dollar figure off of ([17](17-ai-configuration-versioning.md)).

❗ On hitting any limit:

```
DO NOT fabricate. DO NOT continue indefinitely.
Return: "Evidence insufficient within configured research budget."
```

This is the concrete implementation of §12/§18's *"expose evidence gaps and uncertainty instead of
forcing a conclusion."*

---

### D-22 · Quant tool contracts
🟢 Resolved 🔒 **Locked** (contract shape, missing-data policy) / 🎛️ **Tunable** (benchmark series) · **Docs:** [07](07-quant-engine.md)

**Resolution:** all nine tools get **strict Pydantic schemas** —
`calculate_returns`, `calculate_volatility`, `calculate_sharpe`, `calculate_max_drawdown`,
`calculate_beta`, `calculate_correlation`, `compare_assets`, `event_study`, `backtest_strategy`.

**🔒 Missing data:** fail loudly. Never silently forward-fill financial data into a reported
calculation ([D-6](#d-6--market-data-provider-storage-and-adjustment-policy) sets the same rule at
the data layer; this is the same rule at the tool layer).

**🔒 Annualization:** explicit and fixed — daily → 252 trading days, weekly → 52, monthly → 12. No
tool infers a convention from its input.

**🎛️ Benchmark and risk-free rate:** default S&P 500 for comparison; the risk-free series is
explicitly supplied by the market-data layer ([D-6](#d-6--market-data-provider-storage-and-adjustment-policy)) —
**no hard-coded mystery constant** sitting inside a Sharpe calculation.

---

### D-23 · Entailment judgement for citation validation
🟢 Resolved 🔒 **Locked** (method) / 🎛️ **Tunable** (thresholds) · **Docs:** [08](08-evidence-citations.md)

**Resolution: two-stage validation.**

```
Claim → Deterministic provenance check → LLM/NLI semantic support check
```

For V1, the **local Qwen model** ([D-1](#d-1--llm-provider-and-per-node-model-policy)) is the
semantic judge — no separate NLI model or hosted judge dependency.

```
Strong support     → ACCEPT
Partial/ambiguous  → FLAG
Unsupported        → REWRITE / REMOVE
```

❗ An unsupported claim never becomes a confident final claim. This is the entailment gate §8 requires,
with a concrete mechanism attached.

---

### D-24 · Cache TTLs
🟢 Resolved 🎛️ **Tunable** — secondary to version-based invalidation · **Docs:** [09](09-caching-and-prompts.md)

**Resolution:**

| Cache | TTL | Primary invalidation |
|---|---|---|
| Embeddings | 30 days | Version change (§9) |
| Retrieval | 24 hours | Config change (§9) |
| LLM | 24 hours | Prompt + model + input change (§9) |
| Job state | No TTL while active | Job completion |

Immutable historical filings can safely support longer retention than these defaults where measured
useful. ❗ **TTL is a secondary staleness/memory control — version-based invalidation (§20) remains
the primary correctness mechanism.** A TTL bug causes slightly stale results; a missing version in a
cache key causes silently wrong ones.

---

### D-25 · Prompt versioning scheme
🟢 Resolved (session 1) 🔒 **Locked** · **Docs:** [09](09-caching-and-prompts.md), [17](17-ai-configuration-versioning.md)

**Resolution: Git is the production source of truth; LangSmith is for experimentation and tracing
only.**

```
src/prompts/
├── planner/            ├── contradiction/
├── query_rewriter/     ├── synthesizer/
├── evidence_extractor/ ├── critic/
└── verifier/           └── citation_validator/
```

Each prompt version is an **immutable** file (`v1.yaml`, `v2.yaml`, `v3.yaml`) — the application never
silently fetches the "latest" prompt from LangSmith at runtime. Full format:
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

### D-26 · Where per-call LLM accounting is stored
🟢 Resolved (session 1) 🔒 **Locked** · **Docs:** [09](09-caching-and-prompts.md), [10](10-observability.md), [17](17-ai-configuration-versioning.md)

**Resolution: all three** — LangSmith (AI traces), PostgreSQL (durable per-call records, budget
enforcement), Prometheus (aggregate metrics).

Recorded per call: `research_id`, `node`, `model`, `prompt_version`, `input_tokens`, `output_tokens`,
`latency`, `estimated_cost`, `timestamp`.

---

### D-27 · `research_id` vs `trace_id`
🟢 Resolved 🔒 **Locked** · **Docs:** [10](10-observability.md)

**Resolution: two IDs**, correlated in both systems.

```
research_id = research_8f92...          (business/product identifier — stable, user-facing)
trace_id    = 4bf92f3577b34da6...       (OpenTelemetry execution identifier — per-execution)
```

A retried job keeps its `research_id` and gets a new `trace_id` — the report stays addressable by one
stable value while each execution attempt is independently traceable.

---

### D-28 · CI evaluation smoke-test subset and thresholds
🟢 Resolved 🎛️ **Tunable** — thresholds and subset revisited as the suite matures · **Docs:** [12](12-infrastructure-and-deployment.md), [13](13-evaluation.md)

**Resolution:** every PR runs a **fixed 20-question subset** of the frozen benchmark, covering
retrieval, citation validation, and basic RAG answer quality.

**Build fails if:**

```
Recall@K drops > 5%  OR  MRR drops > 5%  OR  citation correctness drops > 5%  OR  tests fail
```

The full benchmark runs nightly / on release. This converts §20's *"do not hide retrieval quality"*
from a principle into an enforced CI gate rather than a report someone reads later.

---

### D-29 · MCP server scope and transport
🟢 Resolved 🔒 **Locked** · **Docs:** [14](14-mcp-assessment.md)

**Resolution:**

**Server #1 — Quant MCP Server**, exposing `calculate_returns`, `calculate_volatility`,
`calculate_sharpe`, `calculate_drawdown`, `calculate_beta`, `calculate_correlation`, `event_study`,
`backtest`.

**Server #2 — Market-data MCP**, added as a **separate server** only if/when market-data tooling
grows complex enough to warrant it — not built preemptively.

**❗ Retrieval stays off MCP initially.** Retrieval is the hot path (called every research iteration);
quant is an occasional call. Protocol overhead is not introduced where it buys nothing — this is the
governing design principle applied directly.

**Transport:**

```
Development → stdio
Production  → local / private HTTP    (health checks, independently deployable, container-friendly)
```

The server stays co-located/private in both cases — no WAN hop on the research path, in either
environment.

---

### D-30 · Ollama serving topology and per-node model sizing
🟢 Resolved 🎛️ **Tunable** — final sizes pinned after hardware benchmarking · **Docs:** [02](02-technology-stack.md), [06](06-agent-langgraph.md)

```
Research Worker → Ollama → Qwen3
```

**Start with one Ollama instance.** ❗ **Benchmark concurrency before introducing replicas** — this is
the check that validates or invalidates the §6 Parallel Research fan-out's core assumption that
branch latency is the max, not the sum, of the branches.

**Model strategy** — per the D-1 tiering, not uniform: simple extraction/rewrite nodes get a smaller
Qwen3; synthesis and critique get a stronger one. Quantization is chosen per model for the available
VRAM/RAM, benchmarked rather than assumed.

**❗ Critical: Qwen3-Reranker is NOT served through Ollama** — Ollama has no rerank endpoint. It gets
its own inference service:

```
Reranker Service → Qwen3-Reranker
```

Candidate runtimes: vLLM / TEI / a small FastAPI wrapper. Benchmark the simplest viable option first
rather than defaulting to the most capable one.

---

### D-31 · Prometheus / Grafana metric set and alerting
🟢 Resolved 🔒 **Locked** (label discipline) / 🎛️ **Tunable** (thresholds, dashboards) · **Docs:** [10](10-observability.md)

**Core metrics:**

| Family | Metrics |
|---|---|
| API | `request_count`, `request_latency`, `error_rate` |
| RAG | `retrieval_latency`, `reranker_latency`, `cache_hit_rate` |
| LLM | `llm_latency`, `input_tokens`, `output_tokens`, `estimated_cost` |
| Workers | `queue_depth`, `job_duration`, `job_failures` |
| Ollama | `model_latency`, `concurrency`, `queue/saturation` |
| MCP | `tool_latency`, `tool_errors`, `server_health` |

**🔒 Label discipline:** low-cardinality only — `service`, `endpoint`, `model`, `node`, `tool`,
`status`. ❗ **`research_id` is never a Prometheus label** — it belongs in traces and PostgreSQL.

---

### D-32 · Experiment record storage
🟢 Resolved 🔒 **Locked** · **Docs:** [17](17-ai-configuration-versioning.md), [13](13-evaluation.md)

**Resolution: Git + LangSmith + PostgreSQL**, each holding what only it should:

| Store | Holds |
|---|---|
| **Git** | Experiment configuration, benchmark configuration, result summary |
| **LangSmith** | Individual LLM/agent runs, traces, datasets, evaluations |
| **PostgreSQL** | Durable experiment metadata: `experiment_id`, `config_version`, `model_version`, `prompt_version`, `retrieval_version`, `dataset_version`, metrics, timestamp |

```
EXP-0042

Prompt:     synthesizer_v3
Embedding:  qwen3-embedding-0.6b_v1
Reranker:   qwen3-reranker-0.6b_v1
Retrieval:  hybrid_v2

Recall@10:          0.91
MRR:                0.87
Faithfulness:       0.94
Citation accuracy:  0.96
```

This is what makes an experiment reproducible years later — the same discipline as [D-26](#d-26--where-per-call-llm-accounting-is-stored),
applied to experiment runs instead of individual LLM calls.

---

## The final stack, at a glance

| Layer | Choice | | Layer | Choice |
|---|---|---|---|---|
| LLM | Qwen3 + Ollama | | Object storage | MinIO |
| Embeddings | Qwen3-Embedding-0.6B | | Frontend | React + TypeScript + Tailwind |
| Vector DB | Qdrant | | Observability (traces) | LangSmith + OpenTelemetry |
| Sparse / BM25 | Qdrant native sparse | | Metrics | Prometheus |
| Fusion | RRF, hybrid dense+sparse | | Dashboards | Grafana |
| Reranker | Qwen3-Reranker (own server) | | CI/CD | GitHub Actions |
| RAG framework | LangChain | | Containers | Docker |
| Agent orchestration | LangGraph | | Auth | JWT + multi-tenant |
| Tool protocol | MCP (quant first; **not** hot RAG path) | | Evidence graph | PostgreSQL relational |
| API | FastAPI | | Prompt source of truth | Git |
| Database | PostgreSQL | | Prompt experimentation | LangSmith |
| Checkpoints | PostgreSQL | | Experiment records | Git + PostgreSQL + LangSmith |
| Cache | Redis | | | |
| Queue | Celery + Redis | | | |

The blueprint's own architecture — Qdrant, LangChain, LangGraph, LangSmith + OTel, PostgreSQL, Redis,
Docker, the six-tier production workflow — was never in question. Everything above closes the
**implementation-level** ambiguity that would otherwise surface mid-build. With all 32 decisions
resolved, **no architectural ambiguity remains for implementation** — only the 🎛️ tunable parameters
above, which are supposed to keep moving under benchmark evidence for the life of the project.
