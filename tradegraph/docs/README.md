# TradeGraph — Documentation

**Agentic Financial Research & Intelligence Platform**

This folder is the working specification and implementation plan for TradeGraph. It is derived
entirely from the two source documents listed below; nothing here invents requirements.

---

## Source documents (authoritative)

| File | Contents |
|---|---|
| [`TradeGraph_Final_Production_Project_Blueprint.pdf`](TradeGraph_Final_Production_Project_Blueprint.pdf) | Final Production Blueprint, §1–§20 |
| [`datasource.txt`](datasource.txt) | Final RAG Data Sources (§3) and Example Corpus (§4) |

Every derived document below cites the blueprint section it comes from. Where a document adds
something the specification does not state, it is explicitly marked.

---

## Reading conventions

| Marker | Meaning |
|---|---|
| *(unmarked)* | Stated in the specification. A `§` reference points to the source section. |
| ⚠ **DECISION** | Historical marker — a decision not yet resolved. None remain: all 32 in [15-open-decisions.md](15-open-decisions.md) are resolved as of 2026-08-14. |
| 💡 **RECOMMENDATION** | A proposal recorded before its decision was resolved. Superseded by the ✅ resolution where one exists. |
| ❗ **RULE** | A non-negotiable engineering rule from blueprint §20 or §12. |
| ⚙ | An **owner decision**, not in the specification. Dated, and logged in [15](15-open-decisions.md). |
| ✅ | A decision that has been resolved. The resolution and date are recorded inline. |
| 🔒 **Locked** | A resolved decision that is architectural — changing it later means a migration (re-embed the corpus, re-index, rewrite the tenancy model), not a config edit. |
| 🎛️ **Tunable** | A resolved decision shipped as a **versioned default** — expected to change under benchmark evidence, with every change tracked and cache-invalidating. |

**Owner decisions do not become specification.** They are marked ⚙ wherever they appear, so the line
between "the blueprint requires this" and "we chose this" stays visible for the life of the project.
Four technologies in the current stack are owner additions: **Ollama, MCP, Prometheus, Grafana**.

**Locked is not the same as tunable.** The architecture (provider, embedding model, vector DB, sparse
engine, checkpointer, tool protocol, auth model) is 🔒 locked. The performance parameters (chunk size,
retrieval top-k, model size per node, cache TTLs, guardrail limits) are 🎛️ tunable and are *supposed*
to keep changing under evidence for the life of the project — see the summary table at the end of
[15-open-decisions.md](15-open-decisions.md).

---

## Document index

### Understand the system

| # | Document | What it covers |
|---|---|---|
| 00 | [Overview & Product Scope](00-overview.md) | Purpose, final decisions, product boundary, MVP, non-negotiable rules |
| 01 | [System Architecture](01-system-architecture.md) | Six-tier architecture, nine subsystems, four data flows |
| 02 | [Technology Stack & Rationale](02-technology-stack.md) | Every technology and the problem it solves |

### Subsystem specifications

| # | Document | What it covers |
|---|---|---|
| 03 | [Data Sources & Corpus](03-data-sources.md) | Sources, phasing, example corpus, document metadata schema |
| 04 | [Ingestion Pipeline](04-ingestion-pipeline.md) | Adapters → storage → parse → dedup → chunk → index |
| 05 | [RAG & Retrieval Pipeline](05-rag-retrieval-pipeline.md) | Hybrid retrieval, RRF, reranking, compression |
| 06 | [Agent & LangGraph Architecture](06-agent-langgraph.md) | Research state, graph topology, the research loop, guardrails |
| 07 | [Quantitative Analysis Engine](07-quant-engine.md) | Deterministic tools, event studies, backtesting rules |
| 08 | [Evidence, Claims & Citations](08-evidence-citations.md) | The evidence chain, provenance, citation validation |
| 09 | [Caching & Prompt Engineering](09-caching-and-prompts.md) | Four Redis cache layers, versioned prompt repository |
| 10 | [Observability](10-observability.md) | LangSmith vs OpenTelemetry, trace propagation |
| 11 | [Security, Reliability & Financial Safety](11-security-and-safety.md) | Untrusted data, budgets, auth, product safety |
| 12 | [Infrastructure & Deployment](12-infrastructure-and-deployment.md) | Deployment split, CI/CD, environments, repo structure |
| 13 | [Evaluation & Experimentation](13-evaluation.md) | Metrics, benchmark dataset, ablation matrix |
| 14 | [MCP Architecture](14-mcp-assessment.md) ⚙ | Server scope, topology, and the constraints that cross the boundary |
| 17 | [AI Configuration & Experiment Versioning](17-ai-configuration-versioning.md) ⚙ | Git vs LangSmith, prompt file format, run manifests, experiment records |

### Plan the work

| # | Document | What it covers |
|---|---|---|
| 15 | [Open Architectural Decisions](15-open-decisions.md) | D-1 … D-32, each with options, impact, and deadline phase; resolution log |
| 16 | [Implementation Plan & Master Checklist](16-implementation-plan.md) | MVP → V1 → V5, with the full execution checklist |

---

## Where to start

- **New to the project?** Read [00](00-overview.md) → [01](01-system-architecture.md) → [02](02-technology-stack.md).
- **About to build something?** Read [16](16-implementation-plan.md) for the phase you are in, then the
  subsystem doc it references.
- **Blocked on a choice?** Check [15](15-open-decisions.md) before inventing an answer.
- **Wondering what was decided and when?** The resolution log at the top of
  [15](15-open-decisions.md).

---

## Current stack

```
Qwen3 + Ollama → Qwen3 Embeddings → Qdrant + BM25 → Qwen3 Reranker
  → LangChain → LangGraph → MCP
  → PostgreSQL → Redis → MinIO
  → LangSmith + OpenTelemetry + Prometheus + Grafana
  → Docker → GitHub Actions
```

Chosen 2026-08-14. Every entry is justified against the governing design principle in
[02](02-technology-stack.md).

---

## The one-sentence summary

TradeGraph is a **stateful research platform, not a query → retrieve → generate chatbot**
(blueprint §1) — it decomposes a financial question, retrieves evidence with hybrid search,
computes numbers with deterministic tools, detects gaps and contradictions, researches again when
evidence is insufficient, and produces a report whose every important claim traces back to a
specific passage in a specific document.
