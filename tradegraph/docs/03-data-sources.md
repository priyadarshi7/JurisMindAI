# 03 — Data Sources & Corpus

> **Source:** `datasource.txt` §3 (Final RAG Data Sources) and §4 (Example Corpus); Blueprint §4
> (document metadata).
> **Status:** Specification-derived.

---

## Source inventory

| Source | What we fetch | Role | Phase |
|---|---|---|---|
| **SEC EDGAR** | 10-K, 10-Q, 8-K and company filings | Primary authoritative corpus | **V1** |
| **Company investor relations** | Annual reports, earnings releases, presentations, shareholder materials | First-party context | **V1** |
| **Earnings materials / transcripts** | Prepared remarks + management/analyst Q&A | Qualitative reasoning | **V1/V2** |
| **Financial news** | Relevant articles from permitted/licensed sources | Market/event context | **V2** |
| **Historical documents** | Prior filings, reports, transcripts and versioned documents | Longitudinal research | — |
| **Market prices/volume** | OHLCV, returns, volume | **Quantitative tool input, not traditional RAG** | — |
| **Macro data** | Rates, CPI, GDP etc. | Quant/data layer; *optionally* summarized into RAG | — |

---

## The V1 sequencing rule

> **V1 recommendation:** begin with a controlled corpus of SEC + first-party investor-relations +
> earnings materials/transcripts. **Add live news only after core retrieval evaluation is stable.**

This is a methodological constraint, not a convenience. News is high-volume, low-signal-density, and
licensing-constrained. Adding it before Recall@K can be measured destroys the ability to attribute a
retrieval regression to any single change — which is precisely what the §10 ablation matrix depends
on.

❗ **Do not ingest news before the benchmark dataset exists and retrieval metrics are stable.**

---

## Market data is not RAG

The sixth row of the table is easy to skim past and expensive to get wrong.

| | Goes to | Consumed by |
|---|---|---|
| Filings, IR materials, transcripts, news | Qdrant + BM25 + PostgreSQL | Retrieval subsystem → evidence chain |
| **OHLCV, returns, volume** | **Market-data store** | **Quant Engine only** |
| Macro data (rates, CPI, GDP) | Quant/data layer | Quant Engine; *optionally* summarized into RAG |

Embedding price series would be an architectural error. Numbers are retrieved by **query**, not by
**similarity**. See [07-quant-engine.md](07-quant-engine.md).

✅ **Resolved 2026-08-14 ([D-6](15-open-decisions.md)):** market data goes through a
`MarketDataProvider` adapter (starting with a free provider, never a hard vendor dependency) into
**PostgreSQL for canonical structured data + MinIO/Parquet for bulk/historical**. Every record
carries `timestamp`, `observed_at`, `effective_at`, `source`; corporate actions are stored **raw plus
adjustment metadata**, never silently pre-adjusted; missing required data **fails loudly**. Default
benchmark: S&P 500 / SPY; risk-free rate from a US Treasury series, recorded in the run manifest. Full
resolution: [15](15-open-decisions.md).

✅ **Resolved 2026-08-14 ([D-17](15-open-decisions.md)):** macro data is **not** summarized into RAG
by default. Add it only when a benchmark question demonstrates the need.

---

## Example corpus (`datasource.txt` §4)

The V1 corpus is deliberately small and structured:

**NVIDIA**
- 2025 10-K
- 2025 Q1 10-Q
- 2025 Q2 10-Q
- 2025 Q3 10-Q
- Relevant 8-Ks
- Earnings release
- Investor presentation
- Earnings-call transcript

> "Repeat the same controlled structure for a small benchmark set of companies."

The point of the controlled structure is that it makes the corpus **comparable across companies**,
which is what makes the §10 benchmark dataset and the comparative questions of §2 ("compare the
fundamental and market-risk profiles of two companies") answerable at all.

✅ **Resolved 2026-08-14 ([D-18](15-open-decisions.md)):** start with **10 companies** —
`AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, WMT` — spanning enough sectors to exercise company
filtering and cross-company comparison. 🎛️ Expand once V1 retrieval metrics are stable.

---

## Mandatory per-document metadata

Both source documents specify this, from slightly different angles. The union is the requirement.

### From `datasource.txt` §4

Every document gets:

- stable ID
- source / provenance
- company / ticker
- document type
- period / date
- content hash
- version
- ingestion timestamp

### From Blueprint §4 (schema form)

```
document_id, company, ticker, document_type, filing_date, fiscal_year,
quarter, section, source, source_url, version, content_hash
```

### Combined field reference

| Field | Purpose | Used by |
|---|---|---|
| `document_id` | Stable identity across versions | Citations, evidence chain |
| `company` | Human-readable entity | Retrieval filter, display |
| `ticker` | Machine key for joining to market data | Retrieval filter, quant join |
| `document_type` | 10-K / 10-Q / 8-K / transcript / presentation / release | Retrieval filter |
| `filing_date` | Actual filing date | Retrieval filter, **look-ahead-bias prevention** |
| `fiscal_year` | Fiscal year of the period reported | Retrieval filter |
| `quarter` | Fiscal quarter | Retrieval filter |
| `section` | Filing section (e.g. Item 1A, Item 7 MD&A) | Section-aware chunking, citation granularity |
| `source` | Which adapter/source produced it | Provenance, trust posture |
| `source_url` | Where it came from | Provenance, re-fetch, citation link |
| `version` | Document version | Longitudinal research, amended filings |
| `content_hash` | Content fingerprint | **Idempotency key** — identical content never embedded twice |
| *ingestion timestamp* | When we ingested it | Audit, staleness detection |

Notes on two fields that carry more weight than they look:

- **`section`** is why chunking is *section-aware* (§4). 10-K/10-Q structure is semantically
  meaningful — "Item 1A Risk Factors" and "Item 7 MD&A" answer different kinds of question — and
  `section` is a first-class citation field in §8.
- **`filing_date`** is the primary defence against look-ahead bias in event studies and backtests
  (§7). A document must never be retrievable as evidence for an event that preceded its filing.

---

## Trust posture

❗ §4 and §12: **treat all source content as untrusted data.** This applies to every source in the
table above, including SEC filings. Retrieved text must never be able to override system
instructions. See [11-security-and-safety.md](11-security-and-safety.md).

---

## Licensing

`datasource.txt` §3 restricts news to **"permitted/licensed sources."**

✅ **Resolved 2026-08-14 ([D-13](15-open-decisions.md)):** no arbitrary full-text news ingestion.
Store metadata + headline + source URL + a permitted excerpt only where the source's licence
explicitly allows it; full text requires an explicit per-source licence check. This keeps V2 news
ingestion independent of scraping legality questions.
