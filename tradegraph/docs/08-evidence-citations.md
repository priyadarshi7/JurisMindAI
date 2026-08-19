# 08 — Evidence, Claims & Citations

> **Source:** Blueprint §8 (Evidence, Claims & Citation Architecture), §10, §17.
> **Status:** Specification-derived.

---

## The rule that shapes the subsystem

> **Do not generate citations after writing the report. Build the evidence chain first.** (§8)

This single rule is why evidence is a subsystem rather than a formatting step. Citations generated
*after* synthesis are reverse-engineered justifications: the model writes a claim from its own
parametric knowledge, then looks for a document that seems to support it. That produces citations
that are plausible, well-formatted, and unverifiable — the exact failure the §10 citation metrics
exist to catch.

---

## The evidence chain

```
Source  →  Passage / chunk  →  Evidence item  →  Claim  →  Citation  →  Synthesis
```

Read it forward. Each arrow is a **write-time** link, not an inference:

| Link | Created by | Doc |
|---|---|---|
| Source → Passage/chunk | Ingestion (section-aware chunking) | [04](04-ingestion-pipeline.md) |
| Passage → Evidence item | Evidence Extractor node | [05](05-rag-retrieval-pipeline.md), [06](06-agent-langgraph.md) |
| Evidence item → Claim | Synthesis, constrained to existing evidence | [06](06-agent-langgraph.md) |
| Claim → Citation | Citation construction from stored provenance | this doc |
| Citation → Synthesis | Report assembly | this doc |

Because the chain is built forward, the report is a *view over the evidence graph* rather than free
text with references attached.

---

## Required provenance per claim (§8)

> Every important claim should have **machine-readable provenance**.

| Field | Purpose |
|---|---|
| **Document ID** | Which document |
| **Source** | Which source produced that document (SEC / IR / transcript / news) |
| **Section** | Where in the document (e.g. Item 7 MD&A) |
| **Timestamp / version** | Which *version* of the document, and when |
| **Supporting passage** | The exact text that supports the claim |
| **Claim ID** | Stable identity for the claim itself |

"Machine-readable" is the operative word: this is a queryable structure in PostgreSQL, not a footnote
string. It is what makes the §10 metrics — citation correctness, citation completeness, claim-support
rate — computable at all, and what makes the §3 `audits` entity meaningful.

### Why version and section are in the list

- **Version** — filings get amended and restated. A citation to "the 10-K" without a version becomes
  wrong the moment a 10-K/A is filed. Longitudinal research (`datasource.txt` §3) depends on
  superseded versions remaining addressable.
- **Section** — determines citation granularity and is how a reader verifies the claim in seconds
  rather than by reading a 200-page filing.

---

## Citation validator (§8)

```
Generated claim
  → Retrieve cited evidence
  → Does evidence entail / support the claim?
       ├─ YES  →  accept
       └─ NO   →  rewrite / remove / flag
```

This is an **entailment gate**, and it is a graph node with authority to reject output — see
[06-agent-langgraph.md](06-agent-langgraph.md). It runs *after* the Critic and is the last node before
`FINAL`.

Three outcomes on failure, and the choice between them matters:

| Outcome | When | Effect on the report |
|---|---|---|
| **Rewrite** | The evidence supports a weaker or narrower version of the claim | Claim is restated to what the evidence actually shows |
| **Remove** | No evidence supports the claim | Claim is dropped |
| **Flag** | Support is ambiguous or partial | Claim ships marked as uncertain |

❗ §12 and §18: **expose evidence gaps and uncertainty instead of forcing a conclusion.** "Flag" is a
legitimate outcome, not a fallback for a broken validator.

✅ **Resolved 2026-08-14 ([D-23](15-open-decisions.md)): two-stage validation.**

```
Claim → Deterministic provenance check → LLM/NLI semantic support check
```

For V1, the **local Qwen model** ([D-1](15-open-decisions.md)) is the semantic judge — no separate
NLI model or hosted judge. Thresholds: strong support → **accept**; partial/ambiguous → **flag**;
unsupported → **rewrite/remove**.

---

## Contradiction detection

§6 places gap **and contradiction** detection in the research loop; §16 makes contradiction detection
a V5 deliverable alongside the evidence graph.

Contradictions differ from gaps:

| | Gap | Contradiction |
|---|---|---|
| Condition | Evidence is *missing* | Evidence *conflicts* |
| State field | `confidence` | `contradictions` |
| Loop behaviour | Research again to fill it | Research again to resolve it, or report the conflict |

❗ Per §2 and §12, a contradiction the system cannot resolve is **reported**, not silently resolved in
favour of one side. "What evidence supports and contradicts a particular investment hypothesis?" is a
listed example question — surfacing conflict is a product feature.

✅ **Resolved 2026-08-14 ([D-12](15-open-decisions.md)): both, in a fixed order.**

```
Numeric contradiction check (deterministic) → Qualitative contradiction check (LLM) → Contradiction record
```

❗ **Never silently average conflicting financial evidence.** The deterministic pass runs first — it
is cheap and catches the conflicts that matter most in financial documents; the LLM pass only
handles what the deterministic check structurally cannot.

---

## The claim/evidence graph

§1 places a **Claim/Evidence Graph** in the reasoning tier. §3 assigns `claims` and `evidence` to
**PostgreSQL**. §16 makes the evidence graph a V5 deliverable.

Minimum relational shape implied by the chain and the provenance fields:

```
documents ──< chunks ──< evidence_items ──< claim_evidence >── claims ──< citations
                                                                  │
                                                              reports
```

✅ **Resolved 2026-08-14 ([D-7](15-open-decisions.md)): PostgreSQL relational.** No Neo4j, no
separate graph database. §3's stack table already assigns these entities to PostgreSQL, and the
"graph" in §1 describes the data's shape, not a required storage engine.

---

## Evaluation (§10, §17)

| Metric | Question it answers |
|---|---|
| **Citation correctness** | Do the cited passages actually support the claims? |
| **Citation completeness** | Does every important claim carry a citation? |
| **Claim-support rate** | What fraction of claims are evidence-backed? |
| **Faithfulness** (RAG) | Is the answer grounded in the retrieved context? |

❗ §20: **"Do not generate unsupported citations. Validate claim-to-evidence support."**

These metrics are only computable because provenance is machine-readable and captured at write time.
That is the payoff for building the chain forward. Detail: [13-evaluation.md](13-evaluation.md).

---

## Phasing

| Phase | Evidence/citation deliverable |
|---|---|
| **MVP / V1** | Evidence extraction, forward-built chain, citation validation, cited report end-to-end |
| **V5** | Full evidence graph + contradiction detection + citation metric suite |

The MVP already requires citations (§18) — this subsystem cannot be deferred to V5 wholesale. Only
the *graph* and *contradiction detection* are V5.
