# 00 — Overview & Product Scope

> **Source:** Blueprint Purpose, §2, §18, §19, §20, Final Objective.
> **Status:** Specification-derived.

---

## Purpose

Build a **production-deployed financial research system** that investigates market questions using
financial documents, market data, hybrid retrieval, quantitative tools, iterative agentic research,
evidence tracing, and citation-backed synthesis.

---

## Final decisions (blueprint front matter)

These are settled. They are not open for re-litigation during implementation.

| Dimension | Final decision | Source |
|---|---|---|
| Product | Financial Research & Decision-Support Platform — **not an autonomous trading bot** | §front matter |
| Primary workflow | Goal → plan → research → retrieve → evaluate → research again if needed → synthesize → verify | §front matter |
| Primary vector DB | Qdrant | §front matter |
| Agent orchestration | LangGraph | §front matter |
| LLM/RAG framework | LangChain | §front matter |
| Observability | LangSmith + OpenTelemetry | §front matter |
| Deployment | Docker + managed cloud services / container platform | §front matter |
| **LLM** | **Qwen3**, served by **Ollama**, behind the §3 provider abstraction | Owner, 2026-08-14 |
| **Embeddings** | **Qwen3 Embedding**, self-hosted | Owner, 2026-08-14 |
| **Reranker** | **Qwen3 Reranker** *(fills §3's "BGE / equivalent" slot)* | Owner, 2026-08-14 |
| **Tool boundary** | **MCP**, beneath the LangChain tool interface | Owner, 2026-08-14 |
| **Object storage** | **MinIO** | Owner, 2026-08-14 |
| **Metrics** | **Prometheus + Grafana**, alongside the mandated LangSmith + OTel | Owner, 2026-08-14 |
| **Prompt/config versioning** | **Git is the source of truth**; LangSmith is for experimentation only | Owner, 2026-08-14 |

The full stack, with the problem each technology solves, is in
[02-technology-stack.md](02-technology-stack.md). **All 32 implementation-level decisions are now
resolved** — logged in [15-open-decisions.md](15-open-decisions.md), which also distinguishes what is
🔒 **architecturally locked** (a later change means a migration) from what is 🎛️ **benchmark-tunable**
(a versioned default expected to keep moving under evidence — chunk size, retrieval top-k, model size
per node, cache TTLs, guardrail limits). The blueprint's own architecture was never in question; this
closes the implementation-level ambiguity that would otherwise surface mid-build.

### Governing design principle

> **Every technology must solve a real architectural problem. Do not add technologies merely to
> increase the stack.**

This principle is the tie-breaker for every "should we also add X?" question. See
[02-technology-stack.md](02-technology-stack.md), where every stack entry is justified against it —
including the four owner additions (Ollama, MCP, Prometheus, Grafana), which are held to the same
standard precisely because they are not in the specification.

---

## Core use case (§2)

A user asks a complex financial research question. TradeGraph:

1. decomposes it,
2. retrieves relevant evidence,
3. performs quantitative analysis where required,
4. detects evidence gaps or contradictions,
5. researches further when necessary,
6. produces a traceable report.

## Example questions (§2)

- Why did NVIDIA outperform the S&P 500 after its latest earnings event?
- What were the major drivers of Apple's margin changes across recent filings?
- How did a company's earnings surprises historically relate to short-term market reaction?
- Compare the fundamental and market-risk profiles of two companies.
- What evidence supports and contradicts a particular investment hypothesis?

Note what these have in common: each requires **multiple sources**, **more than one retrieval step**,
and most require **deterministic numbers alongside retrieved text**. A single-shot RAG system cannot
answer any of them well. That is the justification for the entire agentic layer.

---

## Product boundary (§2)

### ✅ Do

Research · retrieve · calculate · compare · explain · cite · expose uncertainty · support
reproducible analysis.

### ❌ Do not

- Present guaranteed returns
- Autonomously execute trades
- Masquerade as a personalized investment adviser

### Backtesting caveat

Backtesting is an **analytical capability**, not a prediction engine. It must include:

- out-of-sample evaluation
- transaction costs
- slippage assumptions
- explicit warnings about historical-data limitations

Full rules in [07-quant-engine.md](07-quant-engine.md).

---

## MVP definition (§18)

> **Do not build the entire platform first. The first useful release should be small and demonstrable.**

```
User question
  → Planner creates 3–5 subquestions
  → Financial document corpus
  → Hybrid retrieval
  → Reranking
  → Evidence extraction
  → Verification
  → Cited report
```

### MVP success criterion

Given a financial research question, TradeGraph produces a useful report whose important claims can
be traced to retrieved evidence and whose quantitative statements come from deterministic
calculations. **The system should recognize insufficient evidence instead of blindly answering.**

> That final clause is the real acceptance test. A system that always produces an answer has not
> passed it.

---

## Non-negotiable engineering rules (§20)

❗ These are checked at every phase gate. See the standing-rules section of
[16-implementation-plan.md](16-implementation-plan.md).

| Rule | Meaning |
|---|---|
| **Do not make the LLM the calculator** | Numerical truth comes from deterministic tools |
| **Do not trust retrieved text** | Documents are untrusted data |
| **Do not hide retrieval quality** | Benchmark it |
| **Do not create agents without a reason** | Use explicit graph state and controlled tools |
| **Do not generate unsupported citations** | Validate claim-to-evidence support |
| **Do not cache blindly** | Include model/prompt/retrieval versions in cache identity |
| **Do not deploy straight to production** | Use development → staging → production |
| **Do not over-engineer infrastructure** | Docker + managed services first; scale only when justified |
| **Do not treat backtests as predictions** | Use proper validation and disclose assumptions |
| **Do not optimize by intuition alone** | Run controlled experiments and record results |

---

## Final objective

> Build a system that can explain **not only what it concluded, but why it concluded it, which
> evidence supports it, how the numbers were calculated, what evidence contradicts it, how the
> system performed on benchmarks, and how the production system behaves under real workloads.**

Every unusual architectural choice in this project traces back to one clause of that sentence:

| Clause of the objective | Architectural consequence |
|---|---|
| "which evidence supports it" | Forward-built evidence chain ([08](08-evidence-citations.md)); hybrid retrieval so evidence is findable by both name and meaning ([05](05-rag-retrieval-pipeline.md)) |
| "how the numbers were calculated" | Deterministic quant engine, LLM never calculates ([07](07-quant-engine.md)) |
| "what evidence contradicts it" | Contradiction detection as a graph node ([06](06-agent-langgraph.md)) |
| "how the system performed on benchmarks" | Evaluation as a first-class subsystem with a frozen benchmark ([13](13-evaluation.md)) |
| "how the production system behaves" | LangSmith + OpenTelemetry for traces, Prometheus + Grafana for aggregates ([10](10-observability.md)) |
| "why it concluded it" | Explicit graph state, persisted and traceable, with the full AI-configuration run manifest ([06](06-agent-langgraph.md), [17](17-ai-configuration-versioning.md)) |

---

## Portfolio positioning (§19)

**TradeGraph — Agentic Financial Research & Intelligence Platform**

- Built a LangGraph-based financial research workflow that decomposes complex market questions,
  performs multi-source hybrid RAG, invokes quantitative analysis tools, verifies evidence, and
  iteratively researches before generating citation-backed reports.
- Implemented dense + BM25 hybrid retrieval with metadata filtering and reranking over financial
  documents using Qdrant, with PostgreSQL for provenance and Redis for caching/background jobs.
- Added evidence/claim tracing, citation validation, contradiction detection, prompt versioning,
  LangSmith/OpenTelemetry observability, and benchmark-driven evaluation for retrieval, agent,
  citation, latency, and cost performance.
- Deployed a Dockerized FastAPI + React production system with managed PostgreSQL, Redis, Qdrant,
  object storage, CI/CD, authentication, rate limiting, streaming, and asynchronous research workers.
