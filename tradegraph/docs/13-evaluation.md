# 13 — Evaluation & Experimentation

> **Source:** Blueprint §10 (Evaluation & Experimentation), §17, §20.
> **Status:** Specification-derived.

---

## The framing

> **Evaluation is a first-class subsystem, not a final demo step.** (§10)

❗ §20: **"Do not optimize by intuition alone. Run controlled experiments and record results."**
❗ §20: **"Do not hide retrieval quality. Benchmark it."**

Evaluation has its own directory in the repository (`src/evaluation/` with `benchmark/` and
`samples/`), its own CI stage (§14 evaluation smoke tests), and its own phase gate (V5).

---

## Metrics by area (§10)

| Area | Metrics / checks |
|---|---|
| **Retrieval** | Recall@K, Precision@K, MRR, nDCG |
| **RAG** | Context relevance, answer relevance, faithfulness |
| **Citations** | Citation correctness, citation completeness, claim-support rate |
| **Agent** | Tool-selection accuracy, unnecessary calls, research completeness, iteration count |
| **Quant** | Sharpe, drawdown, turnover, transaction costs, out-of-sample performance |
| **System** | Latency, token usage, cost, error rate, cache hit rate |

§17 adds **agent trajectory evaluation** — assessing the *path* the graph took, not only the final
answer.

### What each area actually tests

| Area | Question | Failure it catches |
|---|---|---|
| Retrieval | Did we find the right passages? | The corpus contains the answer but search misses it |
| RAG | Did we use what we found, and is the answer grounded? | Good retrieval, hallucinated synthesis |
| Citations | Do the citations hold up? | Plausible references that do not support their claims |
| Agent | Did the graph behave sensibly? | Right answer via a wasteful or lucky path |
| Quant | Are the strategy results honest? | In-sample overfitting presented as performance |
| System | Is it viable in production? | Correct but too slow or too expensive to run |

Note that Retrieval and RAG metrics are separate on purpose: high Recall@K with low faithfulness
means the retrieval layer is fine and the synthesis layer is not. Collapsing them into one score
hides which subsystem to fix.

---

## The benchmark dataset

> **Create a benchmark dataset before optimizing. Keep the benchmark fixed so architecture changes
> can be compared fairly.** (§10)

Two rules, both hard:

1. **Before optimizing** — building it after tuning means you have already fit to your own intuitions
2. **Kept fixed** — a moving benchmark makes every comparison meaningless

Lives in `src/evaluation/benchmark/` (§15).

### What it must contain

Implied by the metrics that consume it:

| Metric | Requires |
|---|---|
| Recall@K, Precision@K, MRR, nDCG | Questions + **gold relevant chunk labels** |
| Faithfulness, answer relevance | Questions + gold/reference answers |
| Citation correctness | Claim-level ground truth |
| Agent metrics | Expected tool usage / trajectory expectations |

The corpus it runs against is the controlled corpus from `datasource.txt` §4 — NVIDIA's structured
document set, replicated across a small benchmark set of companies. That controlled structure is
precisely what makes comparative questions labelable.

✅ **Resolved 2026-08-14 ([D-14](15-open-decisions.md)): authored in-house, manually verified.**
Starting size **50–100 questions**, spanning factual, comparative, temporal, multi-document,
financial-metric, and evidence/contradiction categories. ❗ Important questions are manually
verified — no LLM-generated benchmark becomes the sole ground truth.

✅ **Resolved 2026-08-14 ([D-18](15-open-decisions.md)): 10 companies** —
`AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, WMT`. 🎛️ Expand once V1 retrieval metrics are
stable.

---

## Core ablation experiments (§10)

Seven, each isolating one architectural claim:

| # | Ablation | What it proves or disproves |
|---|---|---|
| 1 | Dense retrieval vs BM25 vs hybrid retrieval | That hybrid is worth two indexes ([05](05-rag-retrieval-pipeline.md)) |
| 2 | Hybrid retrieval vs hybrid + reranker | That the cross-encoder earns its latency and cost |
| 3 | No metadata filtering vs metadata filtering | That filtering is why the right company/quarter is returned |
| 4 | No query rewriting vs query rewriting | That decomposition improves retrieval on compound questions |
| 5 | **Single-shot RAG vs iterative LangGraph research** | That the entire agentic layer earns its cost and latency |
| 6 | Prompt v1 vs prompt v2 | That prompt changes are measured, not assumed ([09](09-caching-and-prompts.md)) |
| 7 | No cache vs cache | That caching improves latency/cost **without changing answers** |

### Ablation 5 is the honest test of the architecture

If iterative LangGraph research does not beat single-shot RAG on the frozen benchmark, the agentic
layer is not earning its cost — and the governing design principle ("every technology must solve a
real architectural problem") says it should not exist in that form.

Running this experiment and reporting the result truthfully is the difference between a system that
is measured and one that is merely elaborate.

### Ablation 7 has a correctness implication

Caching must improve latency and cost **without changing answer quality**. If cache-on and cache-off
produce different results on the benchmark, the **cache identity is wrong** — a key is missing a
model, prompt, or retrieval config version. See [09](09-caching-and-prompts.md).

---

## Where evaluation runs

| Context | Scope | Source |
|---|---|---|
| **CI** — evaluation smoke tests | A fast subset, as a build gate | §14 |
| **Development** | Full benchmark, on demand | §10 |
| **LangSmith** | RAG/evaluation runs recorded and inspectable | §11 |

✅ **Resolved 2026-08-14 ([D-28](15-open-decisions.md)), 🎛️ tunable:** every PR runs a **fixed
20-question subset** covering retrieval, citation validation, and basic RAG answer quality. Build
fails if Recall@K, MRR, or citation correctness drops **more than 5%**, or tests fail outright. The
full benchmark runs nightly / on release.

---

## Recording results

§20's rule — *"Run controlled experiments and record results"* — requires that each experiment run
persists:

- the configuration under test (retrieval config version, prompt version, model)
- the benchmark version (which must be fixed, but should still be identified)
- every metric from the relevant area
- cost and latency

This is the same accounting described in [09-caching-and-prompts.md](09-caching-and-prompts.md), and
it is why prompts and retrieval configs are versioned (§14). An experiment whose configuration cannot
be named cannot be reproduced.

### The experiment record

The 2026-08-14 configuration-versioning decision makes this concrete. Every run — not only formal
ablations — persists a record of this shape:

```
Experiment #42

LLM:               Qwen3
Prompt:            synthesis_v7
Embedding:         qwen3-embedding-0.6b_v1
Reranker:          qwen3-reranker-0.6b_v1
Chunk size:        700
Top-K retrieval:   30
Top-K rerank:      7

Faithfulness:      94.2%
Citation accuracy: 96.1%
MRR:               0.87
```

❗ **A metric without its configuration is not a result.** It cannot be compared against anything,
which makes it worse than no metric — because it looks like one.

Eight variables determine an answer here, not one. Versioning only the prompt means every experiment
silently confounds the other seven. Full specification, including which changes are cache
invalidations and which are corpus rebuilds:
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

✅ **Resolved 2026-08-14 ([D-32](15-open-decisions.md)): Git + LangSmith + PostgreSQL** — Git holds
the experiment/benchmark configuration and result summary, LangSmith the individual runs and traces,
PostgreSQL the durable `experiment_id` → metrics record. Same three-store pattern as per-call LLM
accounting ([D-26](15-open-decisions.md)), applied to experiment runs.

### ❗ A note on cost metrics with a self-hosted model

§10 lists **cost** as a System metric, and ablations compare configurations partly on it. Qwen3 runs
on our own hardware, so there is no invoice — cost is recorded as an **imputed** figure
(tokens × a configured rate) alongside real wall-clock and compute time.

The configured rate is part of the run manifest. Without it, cost numbers from two periods are not
comparable, and the whole point of a frozen benchmark is comparability.

---

## Phasing

| Phase | Evaluation deliverable |
|---|---|
| **V1** | Begin the benchmark dataset; retrieval metrics harness (Recall@K, Precision@K, MRR, nDCG) |
| **V2** | Agent metrics: tool-selection accuracy, unnecessary calls, completeness, iteration count |
| **V3** | Quant metrics |
| **V4** | System metrics — latency, tokens, cost, error rate, cache hit rate; evaluation smoke tests in CI |
| **V5** | Full benchmark suite complete; **all seven ablations run and recorded** |

§16's V5 exit criterion is *"measurable retrieval/agent/quant improvements"* — improvements
demonstrated by controlled experiment, not asserted.

❗ Note the tension the spec resolves deliberately: the benchmark must exist **before optimizing**
(§10), which means V1 starts it even though V5 completes it. Do not defer the benchmark to V5.
