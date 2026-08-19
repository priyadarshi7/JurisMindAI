# 04 — Ingestion Pipeline

> **Source:** Blueprint §4 (Production Data & Ingestion Pipeline); `datasource.txt` §4.
> **Status:** Specification-derived.

---

## Pipeline

```
SEC filings / earnings material / permitted financial-news sources / market data
  → Source adapters
  → Raw object storage
  → Parser + cleaner
  → Deduplication + document versioning
  → Metadata extraction
  → Section-aware chunking
  → Embedding generation
  → Qdrant  +  BM25 index  +  PostgreSQL metadata
```

---

## Stage by stage

### 1. Source adapters

One adapter per source family, each responsible for fetching and for stamping `source` and
`source_url`. Sources and their phases are in [03-data-sources.md](03-data-sources.md).

Adapters are the **trust boundary**. Everything past this point is untrusted content (§4, §12).

### 2. Raw object storage

The **untouched original** — PDF, HTML, XBRL — is written to S3-compatible object storage *before*
any parsing.

**Why:** parsing is lossy and parser behaviour changes over time. Keeping the original means any
parse can be re-derived and audited without re-fetching from a source that may have changed,
rate-limited us, or disappeared. It is also what makes provenance verifiable rather than merely
asserted.

### 3. Parser + cleaner

Extracts text and structure. Financial documents are structurally heterogeneous — HTML filings, PDF
presentations, transcript formats — so the parser is per-document-type.

❗ Parser output is **untrusted data**. It must never be concatenated into a system prompt position.

Parser errors are recorded, not swallowed (see *Ingestion telemetry* below).

### 4. Deduplication + document versioning

Two mechanisms, often confused:

| Mechanism | Key | Question it answers |
|---|---|---|
| **Deduplication** | `content_hash` | "Have we already ingested exactly this content?" |
| **Versioning** | `document_id` + `version` | "Is this a new revision of a document we know?" |

❗ **Idempotent ingestion: identical content must not be embedded twice** (§4). The content hash is
the gate. Re-running ingestion over the same corpus must be a no-op — this is what makes ingestion
safely retryable and re-runnable in CI.

❗ **Version every source document and preserve provenance** (§4). Amended filings, restated
financials, and re-issued transcripts are normal in this domain, and the "Historical documents"
source role in `datasource.txt` §3 exists specifically to support **longitudinal research** — which
requires that superseded versions remain retrievable, not overwritten.

### 5. Metadata extraction

Populates the full schema. See the combined field reference in
[03-data-sources.md](03-data-sources.md).

```
document_id, company, ticker, document_type, filing_date, fiscal_year,
quarter, section, source, source_url, version, content_hash
```

Plus the ingestion timestamp (`datasource.txt` §4).

This metadata is what makes **metadata filtering** possible in retrieval (§5) — the mechanism that
prevents the worst failure mode in filings RAG: retrieving the right passage from the *wrong company
or wrong quarter*.

### 6. Section-aware chunking

Chunking respects document structure rather than cutting at fixed character offsets.

**Why:** 10-K/10-Q section structure is semantically meaningful. "Item 1A Risk Factors" and "Item 7
MD&A" answer different classes of question, and a chunk that straddles the boundary between them is
worse than either half. `section` is also a first-class citation field in §8, so chunk boundaries
determine citation granularity.

✅ **Resolved 2026-08-14 ([D-19](15-open-decisions.md)), 🎛️ tunable V1 baseline:**

| Parameter | Value |
|---|---|
| Chunk size | 700 tokens |
| Overlap | 100 tokens |
| Boundaries preserved | document · section · subsection · page · table |

❗ **Tables never go through ordinary text chunking.** They are represented as structured, table-aware
chunks carrying table title, headers, rows, source page, and section — a naively chunked table is
unusable as evidence and uncitable, which directly undermines the §8 citation chain. This baseline is
a starting point to measure from and beat, not a final answer.

### 7. Embedding generation

Dense vectors for semantic retrieval. The embedding **model and version are recorded** (§4) because:

- §9 invalidates the embeddings cache when the embedding model changes
- a model change requires re-embedding the corpus, and you must be able to tell which chunks are stale

✅ **Resolved 2026-08-14 ([D-2](15-open-decisions.md))** — **self-hosted Qwen3 Embedding, served by
Ollama.** No per-call cost, version pinned by us.

❗ **Pin the output dimension before creating the Qdrant collection.** Qwen3 Embedding supports
Matryoshka truncation, so the dimension is a deliberate choice rather than a fixed property of the
model. It is the hardest value in the system to change: altering it invalidates every vector, the
whole embeddings cache (§9), and requires a full corpus re-embed.

The pinned model tag and dimension are part of the run manifest —
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md). Because the corpus is
embedded locally, re-embedding costs GPU hours rather than API spend, which makes it *feasible* but
not *cheap*; treat a model change as a migration, not a config edit.

### 8. Index writes

Three destinations, written from one pipeline:

| Destination | Holds | Purpose |
|---|---|---|
| **Qdrant** | Vectors + metadata payload | Dense retrieval with metadata filtering |
| **BM25 index** | Lexical index | Exact-term retrieval |
| **PostgreSQL** | Document/chunk metadata, provenance | System of record; joins for citations and audits |

✅ **Resolved 2026-08-14 ([D-3](15-open-decisions.md)): Qdrant native sparse vectors**, not a
separate index. §5 applies metadata constraints **before** both dense and BM25; sharing one datastore
and one filter language makes filter parity **structural** rather than something maintained by
discipline across two systems.

---

## Ingestion requirements (§4)

All five are hard requirements, not guidance.

| # | Requirement | Implementation consequence |
|---|---|---|
| 1 | **Idempotent ingestion** — identical content must not be embedded twice | `content_hash` gate before embedding; re-runs are no-ops |
| 2 | **Version every source document and preserve provenance** | `document_id` + `version`; superseded versions retained |
| 3 | **Treat source content as untrusted data** | Content/instruction separation everywhere downstream |
| 4 | **Separate ingestion workers from user-facing API processes** | Ingestion is its own process; never runs in an HTTP handler |
| 5 | **Record ingestion status, parser errors, embedding model/version, and timestamps** | An ingestion-run table in PostgreSQL, not just logs |

### On requirement 4

This is the same architectural principle as the research worker (§13): long-running, retry-prone,
resource-heavy work does not share a failure domain or a scaling axis with the request path. An
ingestion run that pins CPU on embedding generation must not degrade API latency.

✅ **Resolved 2026-08-14 ([D-16](15-open-decisions.md)): separate deployables**, not just separate
from the API. Different resource profiles (CPU/embedding throughput vs LLM latency) and schedules
(batch vs on-demand) argue against sharing an autoscaling group.

### On requirement 5 — ingestion telemetry

Recording these makes ingestion *auditable*, which is what the §3 `audits` entity in PostgreSQL
implies. Minimum recorded per ingestion run and per document:

- ingestion status (succeeded / failed / skipped-duplicate)
- parser errors, with the document they occurred on
- embedding model and version used
- timestamps

Without this you cannot answer "why is this document missing from retrieval?" — which will be the
most common ingestion question in practice.

---

## What good looks like at the V1 exit gate

The corpus in [03-data-sources.md](03-data-sources.md) (NVIDIA controlled structure, then a small
benchmark set of companies) is fully ingested, with:

- every document having complete metadata
- re-running ingestion producing zero new embeddings
- an ingestion-run record explaining every document that failed to land
- both Qdrant and the BM25 index queryable with identical metadata filters
