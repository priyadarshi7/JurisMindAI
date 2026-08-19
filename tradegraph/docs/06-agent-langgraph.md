# 06 — Agent & LangGraph Architecture

> **Source:** Blueprint §6 (LangGraph Research Workflow), §3, §12.
> **Status:** Specification-derived.

---

## The framework split (§6)

> LangChain should live **inside graph nodes** for model, prompt, tool, retriever, loader, and
> structured-output components; **LangGraph controls how those components execute** as a stateful
> workflow. This separation is explicit in the source documentation.

| | LangChain | LangGraph |
|---|---|---|
| Role | Component library | Control flow |
| Scope | Inside one node | Across nodes |
| Answers | "How do I call the model and parse its output?" | "Which node runs next, with what state?" |

If graph routing appears inside a chain, or prompt/parser plumbing appears in an edge condition, the
split has been violated.

---

## Graph topology (§6)

```
START
  → Planner
  → Query Decomposer
  → Parallel Research
        ├─ Financial document retrieval
        ├─ News / document retrieval
        ├─ Market-data analysis
        └─ External tools
  → Evidence Extraction
  → Verification
  → Gap / contradiction detection
  → Evidence sufficient?
        ├─ NO  →  Research Again  →  Retrieval  →  Verification   ⟲
        └─ YES →  Synthesis
  → Critic
  → Citation Validator
  → FINAL
```

There is **exactly one conditional edge with a cycle** — the sufficiency gate. That single cycle is
the entire reason LangGraph is in the stack. A chain or DAG cannot express *"go get more evidence and
re-verify."*

---

## Research state (§6)

All sixteen fields, verbatim:

```
query               research_plan        sub_questions       retrieval_filters
retrieved_documents evidence             claims              quantitative_results
contradictions      citations            confidence          iteration
token_budget        cost_budget          draft               final_report
```

### What the field list encodes

| Group | Fields | Note |
|---|---|---|
| Input | `query` | |
| Plan | `research_plan`, `sub_questions`, `retrieval_filters` | Filters are state, so the *second* retrieval pass can search differently from the first |
| Raw findings | `retrieved_documents` | |
| Evidence chain | `evidence`, `claims`, `citations` | Mirrors the §8 chain: passage → evidence → claim → citation |
| Numerical | `quantitative_results` | Populated only by the Quant Engine, never by an LLM |
| Verification | `contradictions`, `confidence` | Drives the sufficiency gate |
| Control | `iteration`, `token_budget`, `cost_budget` | **Budgets are state, not config** |
| Output | `draft`, `final_report` | Critic operates on `draft`; only validated output becomes `final_report` |

❗ The control group is the important design detail. Because `iteration`, `token_budget`, and
`cost_budget` live *in state*, the graph reads and decrements them and the edge condition can enforce
termination **structurally**. Termination is not delegated to the model's judgement.

---

## Node responsibilities

| Node | Reads | Writes | Purpose |
|---|---|---|---|
| **Planner** | `query` | `research_plan` | Turns a goal into a research plan. Prevents undirected retrieval. |
| **Query Decomposer** | `research_plan` | `sub_questions`, `retrieval_filters` | Produces 3–5 sub-questions (§18) plus the metadata constraints for retrieval. |
| **Parallel Research** | `sub_questions`, `retrieval_filters` | `retrieved_documents`, `quantitative_results` | Fan-out across independent evidence sources — latency is the slowest branch, not the sum. |
| **Evidence Extraction** | `retrieved_documents` | `evidence` | Passages → structured evidence items with provenance. |
| **Verification** | `evidence` | — | Checks evidence actually supports what it is being used for. |
| **Gap / contradiction detection** | `evidence` | `contradictions`, `confidence` | Finds what is missing and what conflicts. |
| **Sufficiency gate** *(conditional edge)* | `confidence`, `contradictions`, `iteration`, budgets | routing | The loop decision, bounded by budgets. |
| **Research Again** | gap analysis | `retrieval_filters`, `iteration` | Re-enters retrieval with *revised* filters informed by the detected gap. |
| **Synthesis** | `evidence`, `claims`, `quantitative_results` | `draft` | Writes from the evidence chain, not from model memory. |
| **Critic** | `draft` | `draft` | Adversarial review of the draft. |
| **Citation Validator** | `claims`, `citations`, `evidence` | `final_report` | Entailment gate: accept / rewrite / remove / flag. |

### The Parallel Research branches

| Branch | Backed by | Doc |
|---|---|---|
| Financial document retrieval | SEC/filings RAG | [05](05-rag-retrieval-pipeline.md) |
| News / document retrieval | News RAG (V2+) | [05](05-rag-retrieval-pipeline.md), [03](03-data-sources.md) |
| Market-data analysis | Quant Engine — **deterministic** | [07](07-quant-engine.md) |
| ~~External tools~~ | **Removed** — see below | [D-4](15-open-decisions.md) |

✅ **Resolved 2026-08-14 ([D-4](15-open-decisions.md)):** the generic `external_tools` branch is
**removed**. It is replaced by explicitly named, individually permissioned tools —
`quant tools`, `market_data tools`, `SEC/XBRL tools`, and `web/news tools` (only when explicitly
enabled). There is no `external_tool()` catch-all. Every named tool carries its own schema,
permission, cost accounting, and provenance, which is the actual fix for the undefined
permission/cost/injection surface the open branch represented.

### ❗ The fan-out assumes concurrency it may not get

Parallel Research exists so that latency is **the slowest branch, not the sum of branches**. That
property is an assumption about the runtime, not a property of the graph.

With Qwen3 served locally by Ollama ([D-1](15-open-decisions.md)), model serving has bounded
parallelism. If the branches' LLM calls queue behind a single instance, the fan-out degrades to
sequential execution and the architectural benefit disappears — while the graph still *looks*
parallel in the code.

Measure this early, with Prometheus on Ollama saturation ([10](10-observability.md)), and size the
serving topology to the fan-out width. Tracked as [D-30](15-open-decisions.md).

---

## Guardrails (§6)

Six, all mandatory:

| Guardrail | Enforced by |
|---|---|
| **Maximum research iterations** | `iteration` in state; checked at the sufficiency gate |
| **Maximum tool calls per research job** | Counter in state or worker-level middleware |
| **Token and cost budgets** | `token_budget`, `cost_budget` in state; decremented per LLM call |
| **Structured outputs between nodes** | Typed objects (Pydantic), never prose handoffs |
| **Explicit tool permissions** | Per-node tool allowlists; §12 requires them narrow and explicit |
| **Human review path** | ✅ LangGraph interrupt + checkpoint — [D-5](15-open-decisions.md) |

### On structured outputs between nodes

This is architecturally load-bearing. Nodes exchange **typed objects, not prose**. Free-text handoffs
between agent stages are where multi-agent systems silently corrupt: a downstream node
mis-parses an upstream node's phrasing and the error propagates invisibly to the report. Typed
contracts make that a validation failure instead of a wrong answer.

❗ **This guardrail costs more with a self-hosted model.** Qwen3 on Ollama
([D-1](15-open-decisions.md)) is weaker at strict schema adherence than the frontier hosted models
this pattern is usually demonstrated with. Constrained decoding (grammar / JSON-schema-constrained
generation) or validate-and-retry is therefore **required**, not a refinement — and retries consume
`token_budget`, so the budget sizing in [D-21](15-open-decisions.md) must account for them.

A node that "usually" returns valid structured output is a node that fails unpredictably in
production.

### On the tool boundary

Tool calls from graph nodes go through the LangChain tool interface, with **MCP underneath** it for
the servers listed in [14-mcp-assessment.md](14-mcp-assessment.md). A node does not know whether its
tool is in-process or protocol-mediated — which is what keeps the §6 framework split intact and makes
[D-29](15-open-decisions.md) cheap to revise.

❗ Three guardrails in this table must explicitly survive that boundary: **per-node tool permissions**
(server-level exposure is not node-level permission), **maximum tool calls per job** (the counter
must count MCP calls), and **tool-argument validation** (which runs server-side as well as
client-side). See [14](14-mcp-assessment.md).

### On explicit stopping criteria

§17 lists *"Explicit stopping criteria"* as a separate checklist item from the guardrails. The gate
must have a defined answer for every exit path:

- evidence sufficient → Synthesis
- iteration limit reached → Synthesis **with declared insufficiency**
- token/cost budget exhausted → Synthesis **with declared insufficiency**

❗ Per §12 and §18: the system must **expose evidence gaps and uncertainty instead of forcing a
conclusion**. Hitting a budget limit is not permission to answer confidently — it is a fact that must
appear in the report.

✅ **Resolved 2026-08-14 ([D-21](15-open-decisions.md)), 🎛️ tunable initial limits:**

| Guardrail | Value |
|---|---|
| Max research iterations | 5 |
| Max tool calls | 20 |
| Max parallel branches | 3 |
| Max LLM calls | 30 |
| Max context tokens | Model-dependent |

With a self-hosted model, "cost" is composite — estimated compute cost + token usage + wall-clock
time, since there is no per-call invoice. On hitting any limit: **do not fabricate, do not continue
indefinitely** — return *"Evidence insufficient within configured research budget."*

---

## Persistence and checkpoints

§3 lists **checkpoints** as a reason LangGraph is in the stack, and §17 requires **persistent research
state**.

**Why:** a research job is multi-minute and multi-LLM-call. Without checkpoints, a worker restart
mid-graph loses all prior work and all money spent on it. With checkpoints, the job resumes from the
last completed node.

✅ **Resolved 2026-08-14 ([D-10](15-open-decisions.md)): PostgreSQL.** §17's "persistent research
state" means durable, and Redis stays scoped to transient state (§9). The same checkpoint mechanism
also backs the human-review interrupt ([D-5](15-open-decisions.md)) — no second persistence layer for
a paused job.

---

## Agent discipline

❗ §20: **"Do not create agents without a reason. Use explicit graph state and controlled tools."**

This is **not** a swarm-of-agents design. There is one graph, one state object, and a fixed set of
nodes with declared tool permissions. Adding an "agent" is only justified when it corresponds to a
node with distinct state transitions and its own tool permissions — not because a task feels like it
deserves a persona.

---

## Observability

Every node execution, tool call, and LLM call is traced. §11 requires the `research_id` / `trace_id`
to flow `API → worker → graph → tools → final report`.

Agent-specific evaluation metrics (§10):

- tool-selection accuracy
- unnecessary calls
- research completeness
- iteration count

Plus **agent trajectory evaluation** (§17) — assessing the *path* the graph took, not only the final
answer. Detail: [13-evaluation.md](13-evaluation.md).

---

## The ablation that justifies this whole subsystem

§10 requires: **single-shot RAG vs iterative LangGraph research.**

If the iterative loop does not beat single-shot RAG on the frozen benchmark, the agentic layer is not
earning its cost or latency — and the governing design principle says it should not exist. This
experiment is the honest test of the architecture.
