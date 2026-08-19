# 10 — Observability

> **Source:** Blueprint §11 (LangSmith + OpenTelemetry), §3, §10. **Prometheus + Grafana** are an
> owner addition of 2026-08-14 ([15](15-open-decisions.md)).
> **Status:** Specification-derived, except the metrics layer, marked ⚙.

---

## The two axes

§11 mandates LangSmith and OpenTelemetry. The stack decision adds Prometheus and Grafana. The four
divide along two independent axes, and no tool covers both cells of both.

|  | **AI / agent layer** | **Application / infra layer** |
|---|---|---|
| **Traces** — one execution, in detail | LangSmith | OpenTelemetry |
| **Metrics** — aggregates over time | *(exported via OTel)* → ⚙ Prometheus → ⚙ Grafana | ⚙ Prometheus → ⚙ Grafana |

> **LangSmith is the AI/agent observability layer; OpenTelemetry is the broader
> application/infrastructure tracing layer.** (§11)

### Why the layer split (§11)

| LangSmith — AI/agent layer | OpenTelemetry — application/infra layer |
|---|---|
| LLM traces | API traces |
| LangChain/LangGraph execution | Worker traces |
| Prompt/version visibility | DB/Redis latency |
| Tool calls | Infrastructure health |
| RAG/evaluation runs | Cross-service trace propagation |
| Agent debugging | Production failure analysis |

### Why the trace/metric split

❗ **A trace explains one request. It cannot tell you a rate is degrading.** §10 lists latency, token
usage, cost, error rate, and cache hit rate as tracked System metrics — every one an aggregate over
time. Without a metrics store those numbers are emitted per-request and discarded.

OpenTelemetry is the **instrumentation**, Prometheus the **store and query engine**, Grafana the
**surface a human reads**. One pipeline, three roles — not three competing tools.

### The distinction in practice

| Question | Answered by |
|---|---|
| Why did the agent pick the wrong tool on iteration 3? | LangSmith |
| Why did this job loop five times before terminating? | LangSmith |
| Which prompt version produced this bad synthesis? | LangSmith |
| Why did p99 API latency triple at 14:00? | OpenTelemetry traces |
| Is Qdrant or PostgreSQL the slow hop in retrieval? | OpenTelemetry traces |
| Did the research worker OOM or did the job legitimately fail? | OpenTelemetry traces |
| Has cache hit rate trended down since Tuesday? | Prometheus / Grafana |
| Are we saturating Ollama and serializing the research fan-out? | Prometheus / Grafana |
| What did this month's research actually cost? | Prometheus (rate) + PostgreSQL (attribution) |

An LLM-only tracing setup cannot tell you that a slow research job was slow because Redis was
degraded. An infra-only setup cannot tell you the job was slow because the planner produced eight
sub-questions instead of four. A trace-only setup cannot tell you anything is *trending*. All three
failure classes are routine here.

---

## Trace propagation (§11)

> Every research request should carry a **`research_id` / `trace_id`** through
> **API → worker → graph → tools → final report.**

```
FastAPI mints research_id / trace_id
  → attached to the job record in PostgreSQL
  → carried on the queue message
  → Research Worker adopts it as the root span
  → each LangGraph node = a span
  → each tool call = a child span
       └── ❗ MCP calls carry the id across the protocol boundary; servers emit spans under it
  → each LLM call = a LangSmith run tagged with the same id
  → persisted on the final report, alongside the run manifest (17)
```

❗ The MCP row is the one an adoption most easily drops. A tool server that does not receive and
re-emit the `research_id` splits observability in two, and the Final Objective's *"why it concluded
it"* stops being answerable for anything the tool touched. See [14](14-mcp-assessment.md).

This propagation is what lets you **cross between the two systems**. A LangSmith trace showing a bad
agent decision and an OpenTelemetry trace showing a Redis timeout at the same moment are only
connectable if they share an identifier.

It is also what makes a *stored report* debuggable months later: the report row carries the id that
retrieves the full execution history.

✅ **Resolved 2026-08-14 ([D-27](15-open-decisions.md)): two IDs, correlated in both systems.**

```
research_id = research_8f92...      (business/product identifier — stable, user-facing)
trace_id    = 4bf92f3577b34da6...   (OpenTelemetry execution identifier — per-execution)
```

A retried job keeps its `research_id` and gets a new `trace_id`.

---

## What LangSmith covers

| Concern | Detail |
|---|---|
| LLM traces | Every call, with model, prompt version, generation settings, tokens, latency, cost (§9) |
| LangChain/LangGraph execution | Node sequence, state transitions, loop iterations |
| Prompt/version visibility | Which prompt version ran — requires the versioned repository ([09](09-caching-and-prompts.md)) |
| Tool calls | Which tools were selected, with what arguments, and what they returned |
| RAG/evaluation runs | Benchmark runs and ablation experiments ([13](13-evaluation.md)) |
| Agent debugging | Trajectory inspection for the §10 agent metrics |

Note the last two: LangSmith is not only a production tool here, it is where **evaluation runs** are
recorded. That links this document to [13-evaluation.md](13-evaluation.md).

---

## What OpenTelemetry covers

| Concern | Detail |
|---|---|
| API traces | Request lifecycle, auth, rate limiting, job creation, SSE streams |
| Worker traces | Job pickup, graph execution wall time, retries, failures |
| DB/Redis latency | PostgreSQL queries, Redis cache operations, queue depth |
| Infrastructure health | Container health, resource pressure |
| Cross-service trace propagation | API → worker → data services → **MCP servers** ([14](14-mcp-assessment.md)) |
| Production failure analysis | Error rates and their origin |

---

## ⚙ What Prometheus and Grafana cover

> Owner addition, 2026-08-14. Not in §11. Justified by §10's System metric list, which has no store
> or query surface otherwise.

| Metric family | Source | Why it is tracked |
|---|---|---|
| Latency histograms — API, job end-to-end, per-node, per-tool | OTel export | §10 System metrics |
| Token usage rate | Per-call accounting ([09](09-caching-and-prompts.md)) | §10; feeds §6 budget sizing |
| Cost rate *(imputed)* | Per-call accounting | §10; see [17](17-ai-configuration-versioning.md) on imputed cost |
| Error rate | OTel export | §10 |
| Cache hit rate, per layer | Redis instrumentation | §10 lists it, and §17 requires the no-cache-vs-cache ablation ([13](13-evaluation.md)) |
| **Ollama saturation** — queue depth, tokens/sec, model residency | Ollama + worker instrumentation | ⚠ Load-bearing: if serving serializes, §6's Parallel Research fan-out silently loses its concurrency ([D-30](15-open-decisions.md)) |
| **MCP server health and call latency** | MCP client instrumentation | Adopting MCP made tool availability a runtime dependency ([14](14-mcp-assessment.md)) |
| Queue depth, worker utilisation | Worker instrumentation | Capacity and scaling decisions (§13) |

Grafana presents these as dashboards. This is the concrete answer to the Final Objective's *"how the
production system behaves under real workloads"* — a clause no trace viewer alone can satisfy.

❗ **Cardinality discipline.** `research_id` is unbounded and must **never** be a Prometheus label. It
belongs in traces and PostgreSQL rows. Labels stay low-cardinality: node name, tool name, model,
cache layer, status.

✅ **Resolved 2026-08-14 ([D-31](15-open-decisions.md)), 🔒 label discipline / 🎛️ dashboards:**

| Family | Metrics |
|---|---|
| API | `request_count`, `request_latency`, `error_rate` |
| RAG | `retrieval_latency`, `reranker_latency`, `cache_hit_rate` |
| LLM | `llm_latency`, `input_tokens`, `output_tokens`, `estimated_cost` |
| Workers | `queue_depth`, `job_duration`, `job_failures` |
| Ollama | `model_latency`, `concurrency`, `queue/saturation` |
| MCP | `tool_latency`, `tool_errors`, `server_health` |

Labels: `service`, `endpoint`, `model`, `node`, `tool`, `status` — nothing higher-cardinality.

### Three stores, three jobs

| Store | Grain | Question |
|---|---|---|
| LangSmith | One LLM call / one graph run | "What did the agent do here?" |
| PostgreSQL | One row per call, per job, per audit event | "What did the system do, on whose behalf, and what did it cost?" |
| Prometheus | Aggregated series | "How is the fleet behaving over time?" |

Not redundant: one debugs a job, one is durable and legally answerable, one watches trends. Detail in
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

## Audit trail (§12)

Distinct from tracing, and required separately:

> **Audit major tool calls and state transitions.** (§12)

| | Traces | Audit log |
|---|---|---|
| Purpose | Debugging and performance | Accountability and reproducibility |
| Lifetime | Short retention, vendor-hosted | Durable, in PostgreSQL (§3 lists `audits`) |
| Question | "Why was this slow / wrong?" | "What exactly did the system do, and on whose behalf?" |

Traces may expire; the audit trail must survive, because it is what supports the Final Objective's
requirement to explain *why* a conclusion was reached long after the fact.

---

## The metrics observability feeds (§10)

**System area:**

- Latency
- Token usage
- Cost
- Error rate
- Cache hit rate

**Agent area:**

- Tool-selection accuracy
- Unnecessary calls
- Research completeness
- Iteration count

The agent metrics are derived from LangSmith traces; the system metrics from OpenTelemetry
instrumentation and the per-call accounting records of [09](09-caching-and-prompts.md), aggregated in
Prometheus and presented in Grafana.

---

## Phasing

| Phase | Observability deliverable |
|---|---|
| V1–V3 | Basic logging; per-call accounting begun; ⚙ Prometheus scraping Ollama early, since [D-30](15-open-decisions.md) is measured, not reasoned about |
| **V4** | LangSmith + OpenTelemetry fully wired; ⚙ Prometheus + Grafana with the §10 System metrics; `research_id`/`trace_id` propagated end to end **including across MCP servers**; audit log |
| **V5** | Evaluation and ablation runs recorded in LangSmith; experiment records durable ([D-32](15-open-decisions.md)) |

§16 places "LangSmith + OTel" in V4, alongside caching, prompt versioning, auth, and rate limits —
the production-hardening phase. 💡 Pull *Ollama* metrics earlier: the fan-out concurrency question is
a V2 design risk and cannot be settled without measurement.
