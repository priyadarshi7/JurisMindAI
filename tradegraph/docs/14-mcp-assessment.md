# 14 — MCP Architecture

> **Source:** MCP does not appear in either source document. Its adoption is an **owner decision,
> 2026-08-14**, which **reverses** the recommendation previously recorded here.
> **Status:** ⚠ Adopted, not spec-derived. The specification's tool-boundary constraints (§6, §12)
> continue to bind and are restated below.
>
> **Closes:** [D-9](15-open-decisions.md) and [D-29](15-open-decisions.md) — both resolved
> 2026-08-14.

---

## Standing of this decision

MCP (Model Context Protocol) appears nowhere in
`TradeGraph_Final_Production_Project_Blueprint.pdf` or `datasource.txt` — not in the §3 stack table,
the §6 workflow, the §7 quantitative engine, the §13 deployment split, the §15 repository structure,
or the §17 master checklist.

That absence is recorded so the addition stays traceable: **MCP is an owner-added technology, not a
specification requirement.** Everything else in this documentation set is marked against a `§`; this
is marked against a decision.

What the specification *does* fix at this layer is the contract, not the transport:

| Concern | Specified as | Source |
|---|---|---|
| Tool implementation | `src/tools/` (SEC / news / market / quant tools) and `src/quant/` | §15 |
| Tool binding | LangChain — "models, prompts, **tools**, retrievers, structured output" | §3 |
| Tool invocation | Called from a LangGraph node; structured result returned into graph state | §7 |
| Tool governance | "Explicit tool permissions"; "narrow and explicit"; "validate all external inputs and tool arguments" | §6, §12 |
| Tool evaluation | Tool-selection accuracy, unnecessary calls | §10 |

MCP replaces **how** a tool is reached. It changes none of the five rows above.

---

## What adoption buys

| Gain | Detail |
|---|---|
| **A real boundary, not a convention** | Tool permissions (§6, §12) become enforceable at a protocol edge instead of by discipline inside application code |
| **Reuse outside the graph** | The Quant Engine becomes callable by any MCP client — Claude Desktop, an IDE, a notebook — without importing TradeGraph |
| **Independent testability** | An MCP server can be exercised without instantiating the graph, which strengthens the §7 requirement that every quant function have known-answer tests |
| **A clean fit for what already exists** | §7's engine is already typed-in / typed-out, deterministic, and stateless. It wraps without redesign |

## What it costs, and how the design absorbs it

| Cost | Mitigation |
|---|---|
| A hop inside a latency-sensitive multi-iteration loop | ❗ **Co-locate every MCP server with the research worker** — same host or same private network. No WAN hop on the research path |
| A new availability dependency | Health-check servers at worker startup; a dead tool server must fail the job **loudly**, never degrade into an unsupported answer |
| Serialization overhead per call | Keep payloads structured and small. Retrieval results in particular should not round-trip full document text where an ID and span suffice |

---

## Scope — what goes behind MCP

✅ **Resolved 2026-08-14 ([D-29](15-open-decisions.md)).** Not everything goes behind MCP — the
boundary is drawn where the gain is real and the call volume is low.

| Server | Exposes | Rationale |
|---|---|---|
| **`quant`** *(server #1, built first)* | All nine §7 tools — `calculate_returns`, `calculate_volatility`, `calculate_sharpe`, `calculate_max_drawdown`, `calculate_beta`, `calculate_correlation`, `compare_assets`, `event_study`, `backtest_strategy` | Deterministic, stateless, typed, low call volume, high reuse value |
| **`market-data`** *(server #2, added only if warranted)* | Point-in-time OHLCV and macro series | Added as a **separate server** only if/when market-data tooling grows complex enough to justify it — not built preemptively. Gated on [D-6](15-open-decisions.md) |
| ~~`retrieval`~~ | — | ❗ **Deliberately excluded, decided, not merely deferred.** Retrieval is called on every research iteration; quant is occasional. Protocol overhead is not introduced where it buys nothing — the governing design principle applied directly |

### Transport — resolved

```
Development → stdio            (child process, lowest overhead, one client)
Production  → local / private HTTP   (health checks, independently deployable, container-friendly)
```

The server stays co-located/private in **both** environments — no WAN hop on the research path,
in development or production.

### Deliberately **not** behind MCP

| Component | Why it stays in-process |
|---|---|
| Graph nodes | They *are* the orchestrator, not tools it calls |
| Evidence extraction, verification, citation validation | LLM-calling reasoning steps operating on graph state, not external capabilities |
| Prompt loading | Git is the source of truth ([17](17-ai-configuration-versioning.md)); a prompt is not a tool |
| Cache and checkpoint access | Infrastructure the worker owns directly |

❗ Do not put reasoning behind MCP. MCP is the boundary for **capabilities the graph invokes**, not a
message bus between reasoning stages. §6's "structured outputs between nodes" guardrail is satisfied
by typed objects in graph state, not by a protocol.

---

## Topology

```
Research Worker (LangGraph)
  │
  │  LangChain tool interface  — unchanged for the graph
  │
  ├── MCP client
  │      ├── quant server        (co-located)
  │      ├── market-data server  (co-located)
  │      └── retrieval server    (co-located)
  │
  └── in-process: nodes, prompts, cache, checkpointer
```

The graph still sees LangChain tools. The MCP client sits **underneath** the LangChain tool
interface, which preserves the §6 framework split exactly as specified: LangChain provides the tool
abstraction inside nodes; LangGraph controls execution across them. A node does not know whether its
tool is local or protocol-mediated — and that is the property that keeps [D-29](15-open-decisions.md)
cheap to revise.

---

## ❗ Constraints that survive the protocol boundary

These are the failure modes of an MCP migration. Each is a specification requirement that a naive
wrapping quietly drops.

| Constraint | Source | What it requires of the MCP design |
|---|---|---|
| Tool permissions narrow and explicit | §6, §12 | **Per-node allowlists must survive the boundary.** "The server exposes these tools" is server-level, not node-level, and is not a substitute — the Planner and the Synthesizer do not get the same tools |
| Validate all external inputs and tool arguments | §12 | Validation runs **server-side as well as client-side**. A server that trusts its client has no boundary |
| Maximum tool calls per research job | §6 | The budget counter must count MCP calls. A counter that only sees in-process calls silently stops enforcing |
| Audit major tool calls and state transitions | §12 | Audit rows still land in PostgreSQL, with the same fields |
| Numerical truth is deterministic | §7, §20 | Unchanged. MCP is transport; it is **never** a source of numbers, and no LLM may sit inside a quant server |
| `research_id` / `trace_id` propagation | §11 | ❗ The id **must cross the protocol boundary**, or observability splits in two and the Final Objective's *"why it concluded it"* stops being answerable |

The last row is the one most easily lost and the most expensive to notice late. Every MCP call
carries the `research_id`, and every server emits spans under it ([10](10-observability.md)).

---

## Phasing

| Phase | MCP deliverable |
|---|---|
| **V2** | Tools defined behind the LangChain tool interface; MCP client wired, stdio transport for local development |
| **V3** | `quant` MCP server built, once the §7 tools exist and have known-answer tests; `market-data` server added only if warranted |
| **V4** | Servers deployed on local/private HTTP per the §13 topology; permissions, audit, budget counting, and trace propagation verified across the boundary |
| **V5** | No `retrieval` server — decided against, not merely deferred (see Scope, above) |

💡 **Recommendation on sequencing:** build the tools first, wrap them second. §7's engine must exist
and pass its known-answer tests before a protocol is put in front of it — otherwise a transport bug
and a calculation bug become indistinguishable.
