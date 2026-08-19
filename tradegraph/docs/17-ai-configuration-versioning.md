# 17 — AI Configuration & Experiment Versioning

> **Source:** Owner decision, 2026-08-14. This document is **not** spec-derived — it is the chosen
> *mechanism* for satisfying requirements the specification does state:
> §9 (cache identity), §14 (versioned prompts and retrieval configs), §10 (prompt v1 vs v2 ablation,
> recorded experiments), §20 (*"do not optimize by intuition alone"*).
>
> **Closes:** [D-25](15-open-decisions.md) (prompt versioning scheme),
> [D-26](15-open-decisions.md) (per-call accounting storage).

---

## The core split

```
                    PROMPT
                      │
             ┌────────┴────────┐
             │                 │
             ▼                 ▼
            Git            LangSmith
             │                 │
       Source of truth     Experimentation
       Version control     Tracing
       Code review         Evaluation
       Deployment          Comparison
```

**Git is what production reads. LangSmith is where you look at what happened.**

Two systems, one direction of dependency: prompts flow *from* Git *into* LangSmith traces as
metadata. Nothing flows the other way at runtime.

### ❗ The anti-pattern this rules out

Do **not** store prompts in LangSmith and have the running application pull whichever prompt happens
to be there:

```
LangSmith → "store all prompts here" → production pulls at runtime     ❌
```

Three things break at once:

| Breaks | Why |
|---|---|
| **Reproducibility** | A report generated six months ago cannot be reproduced, because the prompt it used may have been edited since with no commit to point at |
| **Review** | A prompt change is a behaviour change. Outside Git it bypasses diff, review, and CI |
| **Availability** | An external service becomes a hard runtime dependency of the research loop |

The correct shape:

```
Git
 │
 │  Production source of truth
 ▼
Prompt v7
 │
 ├── Evaluation → LangSmith
 │
 └── Deployment
```

---

## Prompt files

Prompts live in `src/prompts/`, one directory per LLM-calling graph node (§9), with one file per
version:

```
src/prompts/
├── planner/
│   ├── v1.yaml
│   └── v2.yaml
├── query_rewriter/
│   └── v1.yaml
├── evidence_extractor/
│   └── v1.yaml
├── verifier/
│   └── v1.yaml
├── contradiction/
│   └── v1.yaml
├── synthesizer/
│   ├── v1.yaml
│   ├── v2.yaml
│   └── v3.yaml
├── critic/
│   └── v1.yaml
└── citation_validator/
    └── v1.yaml
```

The eight directories are fixed by §9 and correspond one-to-one with the graph nodes that call an
LLM ([06](06-agent-langgraph.md)). Adding a directory means adding a node.

### A prompt has a structured identity, not just a filename

`v1` / `v2` / `v3` as bare filenames is not enough — a version number with no name, no declared
inputs, and no model requirements cannot be logged, cached, or reproduced. Every prompt file carries
its own identity:

```yaml
name: research_synthesis
version: 3
description: Synthesizes financial evidence into a cited research answer

model_requirements:
  temperature: 0.1

variables:
  - question
  - evidence
  - sources

prompt: |
  ...
```

| Field | Why it exists |
|---|---|
| `name` | The stable identity across versions. This is what appears in traces and cache keys — `v3` alone is ambiguous across eight directories |
| `version` | Monotonic integer. Never edited in place — a change is a new file |
| `description` | What this prompt is for, so a diff six months later is legible |
| `model_requirements` | Generation settings are **part of the prompt's behaviour**, not a caller detail. §9 requires them in the LLM cache key; putting them here means the key cannot be assembled without them |
| `variables` | The declared input contract. Makes a missing or renamed variable a load-time validation error instead of a malformed prompt reaching the model |
| `prompt` | The template itself |

❗ **A prompt version is immutable once committed.** Editing `v2` in place silently invalidates every
LLM cache entry keyed to it, every LangSmith comparison that references it, and every stored report
that claims to have used it. Change means a new version file.

### The promotion path

```
Edit prompt (new version file)
   ↓
Git diff
   ↓
Run evaluation dataset
   ↓
Compare metrics
   ↓
Commit
```

Worked example:

```
research_prompt v1          research_prompt v2
      ↓                           ↓
Recall:       82%           Recall:       82%
Faithfulness: 89%           Faithfulness: 94%
```

Now the change is backed by evidence rather than by the impression that v2 reads better. This is the
operational form of §20's *"do not optimize by intuition alone"* and it is exactly the **prompt v1 vs
prompt v2** ablation §10 requires ([13](13-evaluation.md)).

---

## Version the whole AI configuration, not just the prompt

A prompt is one of at least eight variables that determine an answer. Versioning the prompt alone
means every experiment silently confounds the other seven.

```
AI Experiment
│
├── Prompt version
├── LLM model / version
├── Embedding model / version
├── Reranker version
├── Chunking configuration
├── Retrieval configuration
├── RRF parameters
└── Evaluation dataset version
```

### The run manifest

Every research job and every evaluation run records the complete configuration that produced it:

```
prompt_name:       research_synthesis
prompt_version:    3
llm_model:         qwen3
embedding_model:   qwen3-embedding-0.6b_v1
reranker:          qwen3-reranker-0.6b_v1
retriever_version: hybrid_v2
chunking_version:  section_aware_v1
benchmark_version: v1
```

This is the answer to *"why did the system say this?"* — the §12 audit requirement and the Final
Objective's *"why it concluded it"*, made concrete. When an answer looks wrong six months later, the
manifest reproduces the exact configuration that generated it.

### Where each component's version comes from

| Component | Version source | Changes invalidate |
|---|---|---|
| Prompt | The `version` field in its YAML file | LLM cache ([09](09-caching-and-prompts.md)) |
| LLM model | Ollama model tag + digest | LLM cache |
| Embedding model | Pinned Ollama model tag | **Embeddings cache and the entire Qdrant collection** — a re-embedding event ([04](04-ingestion-pipeline.md)) |
| Reranker | Pinned model tag | Retrieval cache |
| Chunking config | Versioned config file | Requires **re-chunking and re-indexing** the corpus |
| Retrieval config | Versioned config file (top-k, RRF params, rerank top-N, compression) | Retrieval cache ([05](05-rag-retrieval-pipeline.md)) |
| Benchmark dataset | Version tag on the frozen dataset | Nothing — but it makes cross-run metric comparison invalid ([13](13-evaluation.md)) |

Note the two expensive rows. Embedding-model and chunking changes are not cache invalidations, they
are **corpus rebuilds**. Treat them as migrations, not config edits.

---

## The experiment record

Every benchmark run — not only formal ablations — persists a record of this shape:

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

§20 requires that experiments be *recorded*, and §10 requires seven ablations whose results must
remain comparable over the project's life. Both are impossible if a run's configuration cannot be
named after the fact.

An experiment record contains, at minimum:

- the full run manifest above
- the benchmark dataset version it ran against
- every metric from the relevant §10 area
- cost and latency
- the git commit SHA

❗ **A result without a configuration is not a result.** Do not accept a metric into the record
without its manifest — it cannot be compared against anything, which makes it worse than no metric,
because it looks like one.

✅ **Resolved 2026-08-14 ([D-32](15-open-decisions.md)): Git + LangSmith + PostgreSQL**, each holding
what only it should — Git the experiment/benchmark configuration and result summary, LangSmith the
individual runs/traces/datasets, PostgreSQL the durable `experiment_id` → metrics record. See
[15-open-decisions.md](15-open-decisions.md) for the full `EXP-0042`-style worked example.

---

## Per-call LLM accounting

§9 requires recording **model, prompt version, generation settings, token usage, latency, and cost**
for every important LLM call. **Resolution (D-26): record in both LangSmith and PostgreSQL.**

| System | Holds | Why it must be this one |
|---|---|---|
| **LangSmith** | The full trace — inputs, outputs, prompt version, node sequence | Debugging a specific bad answer. Nothing else shows the reasoning path |
| **PostgreSQL** | Durable per-call rows: model, prompt version, settings, tokens, latency, cost, `research_id` | §6 **budget enforcement must not depend on an external service being reachable**, and cost attribution must survive vendor retention limits |
| **Prometheus** | Aggregates — token rate, cost rate, latency histograms, cache hit rate | §10 system metrics and alerting. See [10](10-observability.md) |

The three are not redundant: one debugs a single job, one enforces a budget and survives, one
watches the fleet.

### ❗ Cost accounting with a self-hosted model

Qwen3 runs on our own hardware ([02](02-technology-stack.md)), so there is no per-token invoice —
but §6 makes `cost_budget` a **state field the graph enforces**, and §10 lists cost as a system
metric. Both still apply.

Resolution: record **two** figures per call.

| Figure | Definition | Used for |
|---|---|---|
| **Imputed cost** | `tokens × a configured rate per model` | §6 `cost_budget` enforcement; §10 cost metrics; cross-model comparison in ablations |
| **Real resource cost** | Wall-clock latency and GPU/CPU seconds | Capacity planning; the actual operating constraint |

The configured rate is itself part of the run manifest — otherwise cost numbers from two different
periods are not comparable. Keeping imputed cost means the budget guardrail stays meaningful and an
ablation against a hosted model later remains a like-for-like comparison.

---

## How this satisfies the specification

| Requirement | Source | Satisfied by |
|---|---|---|
| Include model / prompt / retrieval versions in cache identity | §9, §20 | Every component above carries an addressable version; the run manifest assembles them |
| Version prompts and retrieval configs so experiments do not silently alter production | §14 | Git as source of truth; immutable version files; promotion through evaluation |
| Prompt v1 vs prompt v2 ablation | §10 | Two version files coexist; both runnable against the frozen benchmark |
| Record experiment results | §20 | The experiment record |
| Prompt/version visibility in traces | §11 | `prompt_name` + `prompt_version` on every LangSmith run |
| Per-call model/prompt/settings/tokens/latency/cost | §9 | Per-call accounting, above |
| Audit what the system did and why | §12 | The run manifest persisted on the report row |

---

## Phasing

| Phase | Deliverable |
|---|---|
| **Phase 0** | Prompt file format fixed; loader validates `name`/`version`/`variables` at startup |
| **V1** | Prompts as versioned YAML from day one; embedding, chunking, and retrieval config versions pinned and recorded |
| **V2** | Run manifest attached to every research job and persisted with the report |
| **V4** | Per-call accounting in PostgreSQL + LangSmith; imputed cost drives `cost_budget`; Prometheus aggregates |
| **V5** | Experiment records for all seven ablations ([13](13-evaluation.md)) |

Note this pulls versioning **earlier than §16's V4 placement**. §16 schedules "prompt versioning" in
V4, but §10 requires the benchmark to exist *before optimizing*, and an unversioned V1 prompt cannot
be compared against anything later. The file format costs nothing in V1 and is expensive to
retrofit — adopt it at Phase 0 and let V4 add the accounting and cache-key machinery on top.
