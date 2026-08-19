# 11 — Security, Reliability & Financial Safety

> **Source:** Blueprint §12 (Security, Reliability & Financial Safety), §2, §4, §6, §20.
> **Status:** Specification-derived.

---

## The eleven requirements (§12)

| # | Requirement |
|---|---|
| 1 | Treat all retrieved documents and external text as **untrusted data**; never let them override system instructions |
| 2 | Keep **tool permissions narrow and explicit** |
| 3 | **Validate all external inputs and tool arguments** |
| 4 | Enforce **maximum iterations, tool calls, token budgets, and cost budgets** |
| 5 | Use **authentication and authorization** for research history and private documents |
| 6 | Apply **rate limiting and abuse controls** |
| 7 | Store **secrets only in managed secret/environment configuration** |
| 8 | **Audit major tool calls and state transitions** |
| 9 | **Expose evidence gaps and uncertainty** instead of forcing a conclusion |
| 10 | **Do not connect live brokerage execution** in the initial product |
| 11 | Clearly label research as **informational/decision-support output**, not guaranteed financial advice |

§12 also notes the original project specifically requires: untrusted-document handling, source
attribution, narrow tool permissions, iteration/cost limits, structured outputs, logging,
**separation of content from instructions**, human review for sensitive outputs, and explicit
uncertainty.

---

## 1. Untrusted content — the primary threat

❗ Requirement 1 is the highest-severity item in this document, and it is easy to violate accidentally.

TradeGraph ingests text from SEC EDGAR, investor-relations sites, transcripts, and (in V2) news, then
feeds that text to an LLM that has tools. Any of that text may contain instructions.

**The rule:** retrieved text is *data*, never *instruction*. This holds even for SEC filings —
authoritative provenance is not the same as trusted content.

Concrete obligations, drawn from §12 and §4:

| Where | Obligation |
|---|---|
| Ingestion | Mark parsed content as untrusted at the trust boundary ([04](04-ingestion-pipeline.md)) |
| Prompt construction | **Separation of content from instructions** — retrieved passages never occupy an instruction position |
| Tool invocation | Tool arguments are validated (requirement 3); never taken verbatim from document text |
| Synthesis | Claims derive from evidence, but instructions never do |

This connects to the guardrails in [06-agent-langgraph.md](06-agent-langgraph.md): narrow tool
permissions (requirement 2) bound the *blast radius* if requirement 1 is ever breached. The two
defences are layered deliberately.

---

## 2–3. Tool permissions and input validation

> Keep tool permissions **narrow and explicit**. Validate **all** external inputs and tool arguments.

Implementation consequences:

- Every graph node declares which tools it may call — an allowlist, not a denylist
- Tool arguments are typed and validated before execution (Pydantic; consistent with the §6
  structured-output guardrail)
- The quant tools take typed parameters (ticker, date range, window), never free-form expressions
- ✅ **Resolved 2026-08-14 ([D-4](15-open-decisions.md)):** the generic `external_tools` branch is
  removed. Every tool is explicitly named — `quant`, `market_data`, `SEC/XBRL`, `web/news` (opt-in
  only) — each with its own schema, permission, cost accounting, and provenance. No
  `external_tool()` catch-all exists to create an undefined permission surface.

### ❗ These requirements across the MCP boundary

MCP was adopted 2026-08-14 ([D-9](15-open-decisions.md)). It gives these two requirements a real
enforcement edge rather than a convention inside application code — but only if the boundary is built
correctly:

| Requirement | The mistake | What is actually required |
|---|---|---|
| Narrow, explicit tool permissions | Treating "the server exposes these tools" as the permission model | **Per-node allowlists must survive the boundary.** Server-level exposure is not node-level permission — the Planner and the Synthesizer do not get the same tools |
| Validate all tool arguments | Validating only in the MCP client | Validation runs **server-side as well**. A server that trusts its client is not a boundary, it is a function call with extra steps |

Also carried across: maximum tool calls per job (the counter must count MCP calls), audit rows in
PostgreSQL, and `research_id` propagation. See [14-mcp-assessment.md](14-mcp-assessment.md).

---

## 4. Budgets as a safety control

> Enforce maximum iterations, tool calls, token budgets, and cost budgets.

These appear in §6 as guardrails and here as security controls, because they are both. An agent with
a cycle in its graph and no budget is an unbounded-spend and unbounded-runtime hazard, whether the
cause is a bug, a pathological query, or an injection.

Enforced structurally via `iteration`, `token_budget`, `cost_budget` in the research state — see
[06-agent-langgraph.md](06-agent-langgraph.md).

✅ **Resolved 2026-08-14 ([D-21](15-open-decisions.md)), 🎛️ tunable:** max iterations **5**, max
tool calls **20**, max parallel branches **3**, max LLM calls **30**. With a self-hosted model, cost
is imputed rather than invoiced. On any limit: never fabricate, never continue indefinitely — return
*"Evidence insufficient within configured research budget."*

---

## 5–6. Authentication, authorization, rate limiting

> Use authentication and authorization for **research history and private documents**. Apply rate
> limiting and abuse controls.

The phrase *"private documents"* implies document-level access control, not merely user login.

❗ **If the system is multi-tenant, tenant isolation must reach into Qdrant filters and BM25 filters,
not only PostgreSQL rows.** A retrieval path that bypasses the tenant filter leaks documents
regardless of how well the API is secured. This is expensive to retrofit and cheap to design in.

✅ **Resolved 2026-08-14 ([D-11](15-open-decisions.md)): JWT + multi-tenant.**

```
User → Tenant → Research / Documents / Reports
```

Every private resource carries a `tenant_id`. ❗ Enforcement is not optional at any single layer — it
must hold simultaneously in **PostgreSQL filters + Qdrant filters + sparse-retrieval filters**.
Securing PostgreSQL rows while leaving retrieval unfiltered leaks private documents through the
search path regardless of API-level protection.

Rate limiting is a Redis responsibility (§3: "caching, rate limits, background jobs, transient
state") and lives at the API tier.

---

## 7. Secrets

> Store secrets **only** in managed secret/environment configuration.

- No secrets in the repository, in Docker images, or in committed config
- `.env.example` (§15) documents required variables **without values**
- Provider API keys, database URLs, Qdrant credentials, LangSmith keys, MinIO access keys all come
  from the platform's managed configuration
- CI/CD (§14) includes a **dependency/security scan** stage; secret scanning belongs there

💡 Self-hosting the model layer ([D-1](15-open-decisions.md)) removes one class of secret entirely —
there is no LLM provider API key to leak. LangSmith's key remains, and MinIO credentials are new.

---

## ⚙ What local model serving changes for the security posture

Not a §12 requirement, but a material consequence of the 2026-08-14 decision worth recording, because
it strengthens the posture in one direction and weakens it in another.

| Direction | Effect |
|---|---|
| ✅ **Data residency** | No document text, no query, and no private uploaded document leaves our infrastructure. §12 requires authorization for *private documents*; with a hosted model those documents' contents transit a third party on every call. They no longer do |
| ✅ **Fewer credentials** | No provider API key to rotate, scope, or leak |
| ⚠ **A new attack surface** | Ollama, the reranker server, and the MCP servers are now services we operate. They must be on a **private network**, never internet-exposed, and included in the dependency/security scan |
| ⚠ **Model provenance** | A pulled model tag is a supply-chain artifact. Pin tags by digest in the `ops/` modelfiles ([12](12-infrastructure-and-deployment.md)); an unpinned tag is both a reproducibility problem and a trust problem |

❗ The untrusted-content rule is **unchanged**. A locally served model is not a more trustworthy
reader of a hostile filing — §12's separation of retrieved content from instructions applies exactly
as before.

---

## 8. Audit

> Audit major tool calls and state transitions.

Distinct from tracing — durable, in PostgreSQL (`audits` is a listed entity in §3). See the audit
section of [10-observability.md](10-observability.md).

---

## 9. Uncertainty is a required output

> **Expose evidence gaps and uncertainty instead of forcing a conclusion.**

This is a safety requirement, not a UX preference. It is reinforced in three other places:

- §18 MVP success criterion: *"The system should recognize insufficient evidence instead of blindly
  answering."*
- §8: the citation validator may **flag** rather than accept or remove
- §6: stopping criteria must distinguish "sufficient evidence" from "budget exhausted"

❗ Hitting an iteration or budget limit is **not** permission to answer confidently. It is a fact that
must appear in the report.

---

## 10–11. Financial safety and product boundary

| Rule | Source |
|---|---|
| No live brokerage execution in the initial product | §12 |
| No autonomous trade execution | §2 |
| No guaranteed returns | §2 |
| No masquerading as a personalized investment adviser | §2 |
| Label output as informational / decision-support, not guaranteed financial advice | §12 |
| Backtests are analysis, not prediction; disclose assumptions and historical-data limits | §2, §7, §20 |

The product framing from the blueprint front matter — *"Financial Research & Decision-Support
Platform — not an autonomous trading bot"* — is a safety boundary as much as a scope statement.

See [07-quant-engine.md](07-quant-engine.md) for the backtesting disclosure requirements.

---

## Human review path

§6 lists a **human review path for high-impact or ambiguous outputs** among the guardrails, and §12
notes the original project requires *human review for sensitive outputs*.

✅ **Resolved 2026-08-14 ([D-5](15-open-decisions.md)): LangGraph interrupt + checkpoint.**

```
Research → Verification → Needs Human Review?
    ├── NO  → Continue
    └── YES → INTERRUPT → UI → Approve / Reject / Request Research → Resume
```

Trigger: low confidence, unresolved contradiction, citation validation failure, high-impact
quant/research output, or a backtest result requiring review. Built on the same checkpoint mechanism
as [D-10](15-open-decisions.md) — no second persistence layer for a paused job. 🎛️ Exact confidence
thresholds are tuned once real reports exist to calibrate against.

---

## Reliability

Not a separate §12 list, but implied throughout:

| Property | Mechanism | Source |
|---|---|---|
| Jobs survive worker restart | LangGraph checkpoints | §3, §17, [D-10](15-open-decisions.md) |
| API stays up when research fails | Separate worker process | §4, §13 |
| Ingestion is safely re-runnable | Idempotent ingestion via `content_hash` | §4 |
| Failed ingestion is diagnosable | Ingestion status + parser error records | §4 |
| Production changes are gated | dev → staging → production | §14, §20 |
| Config changes cannot silently alter behaviour | Versioned prompts and retrieval configs | §14, §9 |

---

## Phasing

| Phase | Security deliverable |
|---|---|
| **V1** | Untrusted-content handling and content/instruction separation from day one — this cannot be retrofitted safely |
| **V2** | Narrow tool permissions, tool-argument validation, budget enforcement |
| **V4** | Auth, authorization, rate limiting, secrets management, audit log, output labelling |
| **V5** | Human review path |

❗ Requirement 1 is a V1 obligation even though most of §12 lands in V4. The moment retrieved text
reaches an LLM prompt, the threat exists.
