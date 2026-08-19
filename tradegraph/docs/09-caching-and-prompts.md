# 09 — Caching & Prompt Engineering

> **Source:** Blueprint §9 (Caching & Prompt Engineering), §14, §20.
> **Status:** Specification-derived.

---

## Redis cache layers (§9)

Four layers, each with an explicit key basis and invalidation rule.

| Cache | Key basis | Rule |
|---|---|---|
| **Embeddings** | text + embedding model/version | Invalidate when embedding model changes |
| **Retrieval** | query + filters + retrieval config/version | Invalidate when retrieval configuration changes |
| **LLM** | model + prompt version + input + generation settings | Never reuse stale results across incompatible versions |
| **Job state** | `research_job_id` | Transient workflow state only |

---

## The cache identity rule

❗ §20: **"Do not cache blindly. Include model/prompt/retrieval versions in cache identity."**

This is the single most important line in §9. Every key basis above contains a **version component**,
and the reason is the same in each case:

| Cache | What goes wrong without the version |
|---|---|
| Embeddings | Vectors from two different models mix in one collection; similarity becomes meaningless |
| Retrieval | A config change (new reranker, new top-k) silently serves results computed under the old config — and the §10 ablations measure nothing |
| LLM | A prompt v2 experiment returns prompt v1 answers; the experiment is invalid and you cannot tell |

The connection to §14 is direct: *"Retrieval configurations and prompts should be versioned so
experiments do not silently alter production behavior."* Versioning and cache identity are the same
mechanism viewed from two angles.

### Per-cache notes

- **Embeddings cache** — keyed on the *text*, so identical chunks across document versions and
  identical query strings both hit. Its invalidation event (embedding model change) is also a
  re-embedding event for the whole corpus; see [04-ingestion-pipeline.md](04-ingestion-pipeline.md).
- **Retrieval cache** — must include **filters**, not just the query. The same query text under
  different metadata constraints is a different retrieval.
- **LLM cache** — includes *generation settings* (temperature and friends), because a temperature
  change makes prior outputs non-representative.
- **Job state** — explicitly **transient workflow state only**. It is not the system of record. The
  durable research state lives in PostgreSQL (§3, §17) and in the LangGraph checkpointer
  ([D-10](15-open-decisions.md)).

✅ **Resolved 2026-08-14 ([D-24](15-open-decisions.md)), 🎛️ tunable:**

| Cache | TTL |
|---|---|
| Embeddings | 30 days |
| Retrieval | 24 hours |
| LLM | 24 hours |
| Job state | No TTL while active |

TTL is a **secondary** staleness/memory control — version-based invalidation (§20) remains the
primary correctness mechanism. Immutable historical filings can safely support longer retention than
these defaults where measured useful.

---

## Prompt repository (§9)

Prompts are versioned files on disk under `src/prompts/`, one directory per role:

```
prompts/
  planner/
  query_rewriter/
  evidence_extractor/
  verifier/
  contradiction/
  synthesizer/
  critic/
  citation_validator/
```

Note the mapping to graph nodes ([06-agent-langgraph.md](06-agent-langgraph.md)) — every node that
calls an LLM has a directory here, and every directory here corresponds to a node. That
correspondence is worth preserving as the graph evolves.

**Why a repository rather than inline strings:**

- Prompt version is part of LLM cache identity (§9) and must therefore be addressable
- §10 requires a **prompt v1 vs prompt v2** ablation — impossible if prompts are edited in place
- §14 requires prompts be versioned so experiments do not silently alter production
- LangSmith provides "prompt/version visibility" (§11), which needs a version to display

### ✅ Versioning scheme — resolved 2026-08-14 (D-25)

**Git is the production source of truth; LangSmith is for experimentation and tracing only.**

One file per version, `src/prompts/<node>/vN.yaml`, each carrying a structured identity — `name`,
`version`, `description`, `model_requirements`, `variables`, `prompt` — so a prompt can be logged,
cached, and reproduced by name rather than by path.

❗ **A committed prompt version is immutable.** Editing `v2` in place silently invalidates every LLM
cache entry keyed to it, every recorded comparison referencing it, and every stored report claiming
to have used it.

❗ **The application never fetches a prompt from LangSmith at runtime.** That would put a behaviour
change outside Git diff, review, and CI, and make an old report irreproducible.

This scheme is adopted at **Phase 0**, earlier than §16's V4 placement — the file format costs
nothing up front and cannot be retrofitted onto V1 experiments run without it.

Full specification, including the `model_requirements` rationale and the promotion path:
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

## Versioning is wider than prompts

The prompt is one of eight variables that determine an answer. Versioning it alone means every
experiment confounds the other seven:

```
Prompt version · LLM model/version · Embedding model/version · Reranker version
Chunking configuration · Retrieval configuration · RRF parameters · Evaluation dataset version
```

Every research job and evaluation run records the complete set as a **run manifest**. Two of these
are not cache invalidations but **corpus rebuilds** — a change to the embedding model or the chunking
configuration requires re-indexing, and should be treated as a migration.

Detail: [17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

## Per-call accounting (§9)

> Record **model, prompt version, temperature/generation settings, token usage, latency, and cost**
> for every important LLM call.

| Recorded field | Consumed by |
|---|---|
| Model | §10 system metrics; provider ablations; cost attribution |
| Prompt version | §10 prompt ablation; LangSmith; cache identity |
| Temperature / generation settings | Reproducibility; cache identity |
| Token usage | §6 `token_budget` enforcement; §10 system metrics |
| Latency | §10 system metrics; §11 traces |
| Cost | §6 `cost_budget` enforcement; §10 system metrics |

This record is what makes two things in §6 possible at all: the **token budget** and the **cost
budget** guardrails. A budget that is not measured cannot be enforced.

It is also the raw material for the §10 system metrics — latency, token usage, cost, error rate,
cache hit rate — and for cost tracking in the V4 checklist (§17).

### ✅ Where records land — resolved 2026-08-14 (D-26)

All three, because they have different consumers and none substitutes for another:

| Store | Holds | Why it must be this one |
|---|---|---|
| **LangSmith** | Full trace — inputs, outputs, prompt version, node sequence | Debugging one specific bad answer |
| **PostgreSQL** | Durable per-call rows keyed by `research_id` | ❗ §6 budget enforcement **must not depend on an external service being reachable**, and cost attribution must outlive vendor retention limits |
| **Prometheus** | Aggregates — token rate, cost rate, latency histograms, cache hit rate | §10 System metrics and alerting ([10](10-observability.md)) |

### ❗ Cost with a self-hosted model

Qwen3 runs on our own hardware ([02](02-technology-stack.md)), so there is no per-token invoice — yet
§6 makes `cost_budget` a state field the graph enforces and §10 lists cost as a metric. Both still
apply.

Record **two** figures per call:

| Figure | Definition | Used for |
|---|---|---|
| **Imputed cost** | `tokens × a configured rate per model` | §6 budget enforcement; §10 cost metrics; like-for-like comparison against a hosted model in an ablation |
| **Real resource cost** | Wall-clock latency, GPU/CPU seconds | Capacity planning — the actual operating constraint |

The configured rate is itself part of the run manifest; without it, cost figures from two periods are
not comparable. See [17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

## Cache hit rate is a tracked metric

§10 lists **cache hit rate** under System metrics, and §17 lists it in the Evaluation checklist.
§10 also requires a **no cache vs cache** ablation.

That ablation is the honest test of this whole subsystem: caching must demonstrably improve latency
and cost *without* changing answer quality. If cache hits change results, the cache identity is
wrong.

---

## Phasing

| Phase | Caching/prompt deliverable |
|---|---|
| **Phase 0** | ✅ Prompt file format fixed; loader validates `name`/`version`/`variables` at startup |
| V1–V3 | Prompts as versioned YAML **from day one**; embedding, chunking, and retrieval config versions pinned and recorded |
| **V4** | All four Redis cache layers, per-call accounting in PostgreSQL + LangSmith, Prometheus aggregates, cost tracking on imputed cost |
| **V5** | No-cache-vs-cache and prompt-v1-vs-v2 ablations run and recorded |

Blueprint §16 places "Redis caching + prompt versioning" in V4. **The versioning half moves earlier**
by the 2026-08-14 decision: §10 requires a benchmark before optimizing, and a V1 prompt with no
version cannot be compared against anything later. The caching machinery stays in V4.
