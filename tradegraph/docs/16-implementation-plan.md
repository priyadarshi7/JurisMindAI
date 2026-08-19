# 16 — Implementation Plan & Master Checklist

> **Source:** Blueprint §16 (Build Roadmap V1–V5), §17 (Master Checklist), §18 (MVP Definition), §20.
> **Status:** Phases and exit criteria are specification-derived. The checklist merges §17 with the
> phase gates, the MVP definition, the subsystem documents, and the resolved decisions from
> [15-open-decisions.md](15-open-decisions.md) — **all 32 resolved as of 2026-08-14.** Items marked
> ✅ resolve a decision rather than build a feature; 🎛️ marks a versioned default expected to change
> under benchmark evidence, 🔒 marks an architectural choice that would require a migration to
> change.

---

## Phase overview (§16)

| Phase | Build | Exit criterion |
|---|---|---|
| **MVP** | Planner → hybrid retrieval → reranking → evidence → verification → cited report | A small, demonstrable cited report (§18) |
| **V1** | Financial corpus + ingestion + Qdrant + BM25 + basic RAG + citations | A cited financial research report works end-to-end |
| **V2** | LangChain tools + LangGraph planner/research/verify loop | The agent can research and retry when evidence is insufficient |
| **V3** | Market-data tools + event studies + comparative quantitative analysis | Research reports combine retrieved evidence with deterministic calculations |
| **V4** | Redis caching + prompt versioning + LangSmith + OTel + auth + rate limits | A production-quality deployed application with traces and controls |
| **V5** | Evidence graph + contradiction detection + benchmark suite + backtesting + ablations | Measurable retrieval / agent / quant improvements |

### The ordering logic

**Retrieval quality before agency · agency before numbers · numbers before production hardening ·
production hardening before measurement infrastructure.**

Each phase depends on the previous one being *measurably* good. An agentic loop over bad retrieval
amplifies bad retrieval; production hardening around an unproven pipeline hardens the wrong thing.

§16 notes this mirrors the source learning roadmap: basic RAG → production RAG → LangChain research
assistant → LangGraph workflow → agentic research → UI/API → evaluation → production.

---

## MVP first (§18)

> **Do not build the entire platform first. The first useful release should be small and
> demonstrable.**

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

**Success criterion:** given a financial research question, TradeGraph produces a useful report whose
important claims trace to retrieved evidence and whose quantitative statements come from
deterministic calculations — **and the system recognizes insufficient evidence instead of blindly
answering.**

❗ That last clause is the real acceptance test. A system that always answers has not passed it.

---

# Phase 0 — Foundations & Decisions

**Goal:** nothing is blocked by an unmade decision or a missing scaffold.

### Decisions
- [x] ✅ **D-1** — LLM provider → **Qwen3 via Ollama**, tiered by node (smaller for extraction/rewrite,
      stronger for verify/critic/synthesize/validate) *(2026-08-14)*
- [x] ✅ **D-2** — Embedding model → **self-hosted Qwen3-Embedding-0.6B** *(2026-08-14)*
- [x] ✅ **D-25** — Prompt versioning → **Git-resident structured YAML** *(2026-08-14)*
- [x] ✅ **D-30** 🎛️ — One Ollama instance to start; benchmark concurrency before replicas; sizes
      pinned per node; **reranker gets its own service, not Ollama** (no rerank endpoint) — vLLM /
      TEI / FastAPI wrapper, simplest viable option first *(2026-08-14)*
- [x] ✅ **D-15** — `TradeGraph_Final_Production_Project_Blueprint.pdf` is the authoritative spec; the
      ResearchGraph source stays historical context; broken `filecite` markers removed from generated
      text *(2026-08-14)*

### Scaffold
- [x] Repository structure per §15, plus ⚙ `src/mcp/` and ⚙ `ops/` — see
      [12](12-infrastructure-and-deployment.md) *(implemented 2026-08-14)*
- [x] `pyproject.toml`; lint (ruff), format (ruff format), type-check (mypy --strict) configuration
      *(implemented and passing clean — 33 source files — 2026-08-14)*
- [x] `.env.example` documenting every required variable, **with no values** *(2026-08-14)*
- [x] Docker Compose local stack: PostgreSQL, Redis, Qdrant, MinIO, **Ollama**, **reranker server**,
      Prometheus, Grafana *(`docker compose config` validated 2026-08-14; services not yet run live —
      see note below)*
- [x] ❗ Ollama modelfiles in `ops/`, tier-fast / tier-strong / embedding *(2026-08-14 — tags are
      named placeholders pending the D-30 hardware benchmark; **digest-pinning itself is not done
      until that benchmark picks real sizes**, tracked as an open follow-up)*
- [x] Secrets sourced only from managed environment configuration (§12) — enforced by
      `src/core/config.py` reading only from env/`.env`, never a committed value
- [x] GitHub Actions skeleton: unit tests → integration tests → lint/format → type checks →
      dependency/security scan → Docker build (§14) *(written 2026-08-14; not yet exercised by a
      real PR/push)*
- [x] Three environments defined: development, staging, production (§14, §20) — `Environment` enum
      in `src/core/config.py`

✅ **Update, same day:** the Docker daemon was not running when this scaffold was first built, so
verification was limited to `docker compose config` and in-memory/mocked equivalents. It was started
during the Phase 1 pass below — Postgres, MinIO, Qdrant, and Ollama (with the real
`qwen3-embedding:0.6b` model pulled) have since all been run live and are exercised by real
integration tests. Reranker and the two LLM-tier Ollama models are still not pulled — no reranker
serving path is chosen yet (D-30), and no code calls the LLM tiers yet.

### Configuration versioning — [17](17-ai-configuration-versioning.md)
- [x] Prompt file format fixed: `src/prompts/<node>/vN.yaml` with `name`, `version`, `description`,
      `model_requirements`, `variables`, `prompt` — all eight nodes have a real `v1.yaml`
      *(2026-08-14)*
- [x] Prompt loader validates identity and declared `variables` **at startup**, not at call time —
      `src/prompts/loader.py`, wired into `apps/api/main.py`'s lifespan; 15 unit tests covering every
      failure mode (missing node, unexpected node, filename/version mismatch, duplicate version,
      empty node, bad filename) *(2026-08-14)*
- [x] ❗ A committed prompt version is **immutable** — enforced by convention/review; `PromptDefinition`
      is a frozen Pydantic model so an in-process mutation attempt also fails loudly
- [x] ❗ No runtime prompt fetch from LangSmith; Git is the production source of truth — no LangSmith
      prompt-pull code path exists anywhere in the codebase
- [x] Run-manifest structure defined (prompt · LLM · embedding · reranker · chunking · retrieval ·
      RRF · benchmark versions) — `src/models/run_manifest.py`'s `RunManifest`, with a
      `cache_key_component()` whose tests confirm it changes with every versioned field and ignores
      job identity *(2026-08-14)*

> Note: §16 schedules prompt versioning in V4. It moves to Phase 0 by the 2026-08-14 decision —
> the file format costs nothing now and cannot be retrofitted onto V1 experiments run without it.

### ✅ Phase 0 exit check
29/29 unit tests pass · `ruff check` clean · `mypy --strict` clean (33 files) · `docker compose
config` valid. Since superseded by real verification in Phase 1 (117/117 tests, real services live)
— see that section's summary. Still not done: digest-pinning the Ollama modelfiles (blocked on the
D-30 hardware benchmark), exercising CI against a real PR.

---

# Phase 1 (V1) — Corpus, Ingestion, Hybrid RAG, Citations

**Exit criterion:** a cited financial research report works end-to-end.
**Docs:** [03](03-data-sources.md) · [04](04-ingestion-pipeline.md) · [05](05-rag-retrieval-pipeline.md) · [08](08-evidence-citations.md)

> ✅ **2026-08-14 — the exit criterion's core loop now passes for real**, as a *linear* pipeline
> (`src/graph/pipeline.py::run_research`): Planner → Query Decomposer → {retrieve → extract →
> verify → detect contradictions} → Synthesize → Critic → Citation Validator → a report built from
> validated `Claim`/`Citation` rows. Verified against a real, live-ingested NVIDIA 10-Q with real
> Qwen3 (`qwen3:4b` reasoning, `qwen3-embedding:0.6b` retrieval) — no mocks
> (`tests/integration/test_research_pipeline_live.py`, 494s). Two real bugs were found and fixed
> in the process (FLAG-verdict claims silently dropped like REMOVE; embedder batch timeout on a
> full-size filing) — see the Evidence & citations and Ingestion sections below.
> **Still open before the phase itself is done:** the investor-relations/transcript adapters, the
> full 10-company benchmark corpus, Celery worker wiring, the reranker, the retrieval metrics
> harness, and the FastAPI/React application layer — none of that changed in this pass. This is
> the reasoning core, not the whole phase.

> ✅ **2026-08-15 — the reasoning core is now reachable over HTTP, for real**, not just as a
> Python function: `POST /jobs` creates a job and enqueues it, `GET /jobs/{id}` reports status and
> the final report, `GET /jobs/{id}/stream` polls status transitions over SSE — and
> `src/graph/tasks.py` is the Celery `research`-queue task D-8 named but never wrote. Verified by
> actually running a real worker (`celery ... --pool=solo`) and a real API process against real
> Redis/PostgreSQL/Qdrant/Ollama and posting real jobs, not just unit tests — which is how three
> more real bugs surfaced (none of them present in yesterday's direct-function-call test, all of
> them only reachable by driving the system the way a real client would):
> - A cached `AsyncEngine` (`src.core.db.get_engine()`) reused across two sequential Celery tasks
>   crashed the second one — its asyncpg connection pool was bound to the first task's
>   `asyncio.run()` event loop, already closed by the time task two started. Fixed by giving
>   `src/graph/tasks.py` its own per-invocation engine, disposed at the end of every task.
> - The Query Decomposer's free-text `company` field ("NVIDIA") never exact-matched Qdrant's
>   canonical stored legal name ("NVIDIA CORP"), silently zeroing every retrieval hit for every
>   query that included a company filter — real evidence sat in the collection the whole time.
>   Fixed by dropping `company` from the metadata filter `run_research()` builds; `ticker` (a
>   controlled vocabulary the LLM reproduces reliably) is what retrieval actually filters on now.
> - The Ollama chat client's 180s default timeout was too tight for `evidence_extractor` — the
>   node reasoning over the most input text at once — on CPU-only serving; raised to 300s (same
>   fix already made once for batch embedding, same root cause: CPU inference is not fast here).
>
> With both the engine and filter fixes in place, a real job posted to the real API found real
> evidence, ran the full reasoning chain, and returned a report that honestly stated what it could
> and couldn't determine from the retrieved passages — verified over HTTP, not by calling
> `run_research()` directly. **Still open:** the ingestion Celery queue (only `research` has a
> task; `ingest_filing` is still Python-function-only), and the React frontend has nothing to call
> these endpoints yet.

> ✅ **2026-08-17 — the React frontend exists, has live progress, and the reranker is real**, in
> that order. The frontend (`apps/web`, React + TypeScript + Tailwind + Vite) has a query form, a
> live SSE-driven progress view, a report view, and an evidence panel showing claim → citation →
> passage/document detail — verified in an actual headless browser against the real running
> API/worker/Ollama stack, screenshots taken at each state, zero console errors. Building it exposed
> that `run_research()` gave no visibility into a multi-minute run beyond a single "running" status,
> so `ProgressCallback` (`src/graph/pipeline.py`) and `ResearchJob.progress_detail` (migration 0003)
> were added — the worker now commits a human-readable "what's happening now" string
> (`src/graph/tasks.py`) on its own short-lived session per pipeline stage, and the SSE stream emits
> it as a separate `event: progress` frame.
>
> Testing that frontend against a real question then surfaced the session's biggest finding: a real
> NVDA revenue question's actual answer retrieved at fused rank ~22-41 out of 42 candidates — RRF
> score alone is not precision, `top_n_per_subquestion` (5 → 15 → 30) chased it without converging
> (missing evidence → truncated extraction → generation-time timeout, each fix relocating the
> failure rather than resolving it) — see the Retrieval section below for the reranker that was
> built as the actual fix, and its own honestly-documented remaining limitation.

> ✅ **2026-08-17 (continued) — the corpus was found empty, restored, and a second real bug found
> and fixed: evidence-extraction quality, not retrieval.** Resuming this session, a live DB check
> found `documents`/`chunks`/`tenants`/`ingestion_runs` all at 0 rows — the NVDA 10-Q ingested and
> verified earlier this session was gone (most likely an over-broad prior cleanup script), and `.env`
> was separately pointed at a leftover `tradegraph_documents_test` Qdrant collection instead of the
> real one. Fixed both: corrected `QDRANT_COLLECTION_NAME`, killed several stale duplicate API/
> worker/reranker processes left running from earlier in the session (Windows venv processes show as
> parent+child pairs, which briefly looked like the previously-documented "two workers" bug but
> wasn't — genuine duplicates were still found and killed among them), restarted all three services
> clean, and re-ingested NVIDIA's latest 10-Q (filed 2026-05-20) for real via `ingest_filing` — 140
> chunks, verified matching in both PostgreSQL and Qdrant.
>
> A fresh job against the restored corpus still came back `insufficient_evidence` — same symptom as
> before, but this time a live diagnostic proved retrieval and reranking were *not* the cause: the
> two chunks containing the real answer ("Gross margin increased to 74.9%...") were confirmed present
> in the corpus by direct SQL search, and a direct retrieval+rerank replay of the exact failing
> sub-question put both of them at reranked rank 0–1 of 7 with a clean 0.9/0.0 score split — the
> reranker fix from earlier in the session is holding up. The actual cause was downstream:
> `run_evidence_extractor`, given all 7 reranked passages (~20K characters, much of it boilerplate —
> investor-relations links, blog URLs, FASB pronouncements — sharing chunks with the real financial
> tables), returned 30 fabricated "evidence items" with invented `passage_index` values, none about
> the sub-question. Handing the same extractor call only the 2 known-good passages produced correct,
> clean extraction (74.9% gross margin, verbatim) and a `SUPPORTS` verdict both times; re-running the
> *full* real retrieval pipeline at `top_n=3` instead of `7` reproduced that same correct result
> without hand-picking passages. **Fix:** `top_n_per_subquestion` lowered 7 → 3
> (`src/graph/pipeline.py`) — a real, live-found ceiling on how much raw passage text this 4B model
> reliably reasons over in one structured-extraction call, distinct from the reranker's own
> already-documented CPU-non-determinism limitation. 163 unit tests still pass after the change (no
> test pinned the old default).

### Decisions due this phase — all resolved 2026-08-14
- [x] ✅ **D-3** 🔒 — BM25 → **Qdrant native sparse vectors**; same canonical filter as dense, so
      filter parity is structural, not maintained by discipline
- [x] ✅ **D-11** 🔒 — Tenancy → **multi-tenant**; `tenant_id` filter enforced in PostgreSQL **and**
      Qdrant **and** sparse retrieval, decided now even though full JWT auth ships in V4
- [x] ✅ **D-16** 🔒 — Ingestion worker and research worker are **separate deployables**
- [x] ✅ **D-18** 🎛️ — Benchmark set → **10 companies**: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA,
      JPM, V, WMT
- [x] ✅ **D-19** 🎛️ — Chunk size **700** / overlap **100**; tables as structured chunks (title,
      headers, rows, page, section), never plain-text split
- [x] ✅ **D-20** 🎛️ — Dense top-K 30, sparse top-K 30, standard RRF, reranker top-N 7, final context
      5–7 passages. ⚠ The reranker itself is LLM-based listwise scoring over Ollama, not the
      dedicated Qwen3-Reranker cross-encoder this decision assumed — see the Retrieval section's
      reranker entry for why and what it cost/found live (2026-08-17). 🎛️ `top_n_per_subquestion`
      (final context size) is actually **3** as of 2026-08-17, not 5-7 — lowered live after finding
      the 4B extractor's reliability, not retrieval, was the binding constraint at 7 (see the
      Evidence extractor entry below).
- [x] ✅ **D-23** 🔒 — Two-stage entailment: deterministic provenance check → local-Qwen semantic
      judge; accept / flag / rewrite-remove thresholds
- [x] ✅ **D-14** 🔒 — Benchmark authored in-house, manually verified, **starting now** at 50–100
      questions (completes in V5)

### Ingestion
- [x] SEC EDGAR adapter — 10-K, 10-Q, 8-K — `src/rag/ingestion/sec_edgar.py`. **Verified live**
      against the real SEC API: resolves tickers via `company_tickers.json`, lists/filters real
      filings, fetches a real NVIDIA 10-K and 8-K (`tests/integration/test_sec_edgar_live.py`).
- [ ] Investor-relations adapter — annual reports, earnings releases, presentations *(not built —
      only the SEC EDGAR source exists so far)*
- [ ] Earnings materials / transcripts adapter — prepared remarks + Q&A *(not built)*
- [x] Raw immutable originals written to object storage **before** any parsing —
      `src/data/object_storage.py` + the pipeline's ordering, content-addressed by hash. **Verified**
      against real MinIO, including a call-order test proving the write happens before any embedding
      call.
- [x] Parser + cleaner; ❗ treat all source content as **untrusted data** —
      `src/rag/ingestion/parser.py`. **Verified** against a real, live-fetched NVIDIA 10-K: finds
      ≥5 Item sections and ≥5 tables, strips scripts/styles, no security-boundary claim made (the
      untrusted-data rule is enforced at the LLM prompt boundary — see `src/prompts/`).
- [x] `content_hash` deduplication — **idempotent ingestion**; identical content never embedded
      twice — `src/rag/ingestion/dedup.py`. **Verified end-to-end**: re-ingesting the same real
      filing returns `SKIPPED_DUPLICATE` and calls neither the embedder nor Qdrant.
- [x] Document **versioning**; superseded versions retained, provenance preserved —
      `determine_version()` in `dedup.py`, unit-tested (first version, amendment, multiple-version
      chain). ⚠ Not exercised against a *real* amended filing (e.g. a 10-K/A) — no such filing was
      ingested in this pass, so the "real" version of this guarantee is unit-level only.
- [ ] ⚠ Partial — Metadata extraction to the full schema — see [03](03-data-sources.md). Present:
      `document_id`, `company`, `ticker`, `document_type`, `filing_date`, `fiscal_year`,
      `source`, `source_url`, `version`, `content_hash`, ingestion timestamp. **Gap:** `fiscal_year`
      is populated but SEC's submissions API does not directly supply `fiscal_quarter` — it is
      derivable from `reportDate` but that derivation is not implemented yet.
- [x] **Section-aware chunking** — `src/rag/chunking/chunker.py`, 700/100 token baseline, tables
      always whole. **Verified**: overlap-token-equality test, and real-filing table/section counts.
      ⚠ Token counting uses `tiktoken` (`cl100k_base`) as a documented approximation of Qwen3's real
      tokenizer — see the module docstring.
- [x] Embedding generation via **Ollama / Qwen3 Embedding**, with model + version recorded —
      `src/rag/embeddings/ollama_embedder.py`. **Verified live** against the real pulled model
      (`qwen3-embedding:0.6b`, 1024-dim): a real embed call, a batching test, and a semantic-
      similarity test confirming paraphrase recall is real, not asserted
      (`tests/integration/test_ollama_embedder_live.py`).
- [x] ❗ **Pin the embedding dimension before creating the Qdrant collection** — `ensure_collection`
      takes `dense_dimension` explicitly; **verified** the real model's output is exactly the pinned
      1024.
- [ ] ⚠ Partial — Ingestion telemetry: status, parser errors, embedding model/version, timestamps. Per-document
      telemetry is real (`Document.ingestion_status`, `ingested_at`, `Chunk.embedding_model/
      dimension`). **Gap:** the `ingestion_runs` table (aggregate per-run status, documents
      processed/failed, parser errors) is defined in the schema but **not yet written to** — no code
      creates or updates an `IngestionRun` row. `src/rag/ingestion/pipeline.py` ingests one filing at
      a time; a run-level orchestrator that wraps a batch of filings in one `IngestionRun` does not
      exist yet.
- [ ] ❗ Ingestion workers run **separately from the API process** — the worker Dockerfile and queue
      convention exist (Phase 0), but no Celery task wraps `ingest_filing` yet, so there is nothing
      running "separately" — the pipeline is only callable as a Python function today.
- [ ] Ingest the NVIDIA controlled corpus (2025 10-K · Q1/Q2/Q3 10-Qs · relevant 8-Ks · earnings
      release · investor presentation · transcript) — **not done at this granularity.** One real
      NVDA 8-K was ingested end-to-end as verification; the full controlled corpus (all filing types,
      plus the IR/transcript sources this checklist item also names) requires the two missing
      adapters above.
- [ ] Replicate the same controlled structure across the benchmark company set — not started; only
      NVDA has been touched.

### Storage & indexes
- [x] PostgreSQL schema + migrations: users, jobs, documents, chunks, claims, evidence, citations,
      reports, audits, **plus `tenants` and `ingestion_runs`** — `src/models/orm.py` +
      `migrations/versions/0001_initial_schema.py`. **Verified with zero drift** against a real
      PostgreSQL instance (`alembic check` / `compare_metadata` both report no diff), upgrade and
      downgrade both exercised for real.
- [x] Qdrant collections with metadata payloads and filter indexes — `src/rag/vector/qdrant_store.py`.
      **Verified** against a real Qdrant server (not just in-memory mode): dense + native sparse
      vectors in one collection, payload filtering on company/ticker/document_type/tenant/filing date.
- [x] BM25 index built, with **identical metadata filter semantics** to dense retrieval —
      `src/rag/bm25/sparse_encoder.py` (fastembed's `Qdrant/bm25`) + `build_metadata_filter()` used
      as the *only* filter-construction path for both arms. **Verified structurally**: a test asserts
      the same filter excludes the same points from both `search_dense` and `search_sparse`.

### Retrieval
- [x] Intent + entity extraction — wired: the Planner node (`src/graph/nodes.py::run_planner`,
      `src/prompts/planner/v1.yaml`) is now called by the linear research pipeline
      (`src/graph/pipeline.py::run_research`) and returns structured `PlannerOutput`
      (entities, evidence_needed, plan_notes) from a real Qwen3 call. **Verified live**
      end-to-end (`tests/integration/test_research_pipeline_live.py`, real SEC filing, real
      Ollama, real PostgreSQL persistence, 8m14s) plus unit tests
      (`tests/unit/test_nodes.py`, `test_pipeline.py`). This is the linear MVP pipeline, not
      yet the cyclic LangGraph `StateGraph` with a conditional sufficiency-gate loop — that
      loop is V2 (docs/06).
- [x] Query rewriting / decomposition — wired: the Query Decomposer node
      (`run_query_decomposer`, prompt node `query_rewriter`, `src/prompts/query_rewriter/v1.yaml`)
      runs after the Planner and produces the `sub_questions` the pipeline researches
      independently. Same live + unit verification as above.
- [x] Metadata constraint construction — company / ticker / document type / filing-date range —
      `build_metadata_filter()`, **verified real**. ⚠ Fiscal-period (quarter) filtering is not wired
      since `fiscal_quarter` isn't populated or indexed yet (see the Metadata gap above).
- [x] Dense retrieval — `QdrantStore.search_dense`, **verified real** (real Qdrant, real embeddings).
- [ ] ⚠ Partial — Parallel dense + BM25 execution — both arms run and fuse correctly (**verified real**), but
      `HybridRetriever.search` currently calls `search_dense` then `search_sparse` **sequentially**,
      not concurrently. Functionally correct; not yet the latency-optimal "parallel" the checklist
      item names — an `asyncio.gather`-style change is a follow-up, not a redesign.
- [x] Reciprocal Rank Fusion → Top-N candidate set *(starting top-K retrieval 30)* —
      `src/rag/hybrid/fusion.py`, **verified**: hand-computed-score test, consensus-ranking test, and
      a real end-to-end fused result from live services.
- [x] ⚠ Partial — **Reranker wired** *(starting top-K rerank 7)*, but not the dedicated Qwen3-Reranker
      cross-encoder D-20 names — `apps/reranker/main.py` implements the `/rerank` contract for real
      using **LLM-based listwise scoring** over the already-running Ollama chat model, not a separate
      cross-encoder runtime (still gated on the D-30 hardware benchmark, never run). Found live
      (2026-08-17), not by inspection: a real NVDA revenue question's actual answer (a numeric table)
      ranked ~22-41 out of a 42-candidate fused pool — RRF score alone isn't precision, and widening
      `top_n` to compensate just traded a missing-evidence failure for a generation-time-limit
      failure (see `src/graph/pipeline.py`'s `top_n_per_subquestion` history). The reranker re-scores
      the wider candidate pool by relevance before the final cut, so `top_n_per_subquestion` is back
      to D-20's 5-7 baseline. **Real, load-bearing gap found and fixed along the way:** the exact
      same real query and passage set, scored twice at temperature=0.0 (nominally deterministic),
      came back once with real differentiated scores and once with every passage scored identically
      — CPU-backend floating-point non-associativity, not a prompt bug (isolated single-passage
      scoring was correct in every test). `apps/reranker/main.py` now retries up to 3× on a
      degenerate (all-identical-score) response before trusting it.
      **Known remaining limitation, documented not hidden:** for large batches (~30) of real,
      structurally-similar financial passages (several legitimate tables in the same filing — a
      full income statement vs. a segment breakdown, say — each plausibly "financial" and
      "NVIDIA-related"), a 4B CPU-served model's discrimination reliability degrades even across
      retries; this is a genuine capability ceiling of a small self-hosted model doing nuanced
      financial-document comparison at scale (consistent with D-1's own note that self-hosted models
      are weaker than frontier hosted ones at this kind of task), not a bug in this implementation.
      A dedicated cross-encoder (the original D-20 design) or a smaller candidate window would both
      likely do better; neither was in scope for this pass.
- [ ] Context selection / compression — not built.
- [x] ⚠ Partial — Evidence extractor → structured evidence items — wired: `run_evidence_extractor`
      (`src/prompts/evidence_extractor/v4.yaml` as of 2026-08-17 — v2/v3 superseded on max_tokens
      only, found live when wider reranker candidate windows needed more output room; prompt text
      unchanged since v2 — index-based passage referencing) is called per
      sub-question in `_research_sub_question()`, and items that survive the Verifier node
      (SUPPORTS/PARTIAL) are persisted as real `EvidenceItem` rows keyed to their source
      `chunk_id`. **Verified live**: the end-to-end test asserts non-empty `Claim`/`Citation`
      rows traceable back through this path against a real ingested filing. **Real, load-bearing gap
      found and fixed live (2026-08-17, second pass):** given 7 large reranked passages in one call
      (~20K characters, several containing unrelated boilerplate merged into the same chunk as the
      real financial figures), the 4B model fabricated 30 "evidence items" referencing
      `passage_index` values beyond the 7 actually supplied — none relevant to the question, despite
      the correct answer being present verbatim in passage 1. The same extractor call given only the
      2 relevant passages directly, and separately a full real-retrieval run at `top_n=3`, both
      produced correct, clean extraction and `SUPPORTS` verdicts. This is an extraction-capacity
      ceiling of the small self-hosted model given noisy multi-passage input, not a retrieval bug —
      `top_n_per_subquestion` lowered 7 → 3 as the fix (see D-20 note above). **Not yet built:**
      anything that would make the extractor robust to a *wider* window again (e.g. one
      extraction call per passage instead of one call over N passages) — 3 works today but is a
      narrower safety margin than the system was designed around.

> ✅ **2026-08-18 — confirmed the extraction fix live end-to-end, then addressed job latency.** A
> real `POST /jobs` through the restored API/worker, with the `top_n=3` fix in place, came back with
> a real cited report: NVIDIA's gross margin (74.9%, Q1 FY2027) with 4 claims, real
> accept/rewrite citation verdicts, and correct provenance to the real ingested 10-Q. **Still an open
> gap, not chased further this pass:** the same job's *revenue* sub-question still came back
> insufficient, even though the answer sits in the same top-ranked passage as the gross-margin one —
> not yet root-caused. Separately, the user flagged the system as too slow to use/demo comfortably.
> Diagnosis: `ollama ps` shows `size_vram: 0` for the loaded chat model — there is no GPU offload at
> all (the machine has an AMD Radeon 780M integrated GPU, no NVIDIA card; `nvidia-smi` fails outright,
> and AMD/ROCm Ollama support was not pursued this pass as a bigger, uncertain-payoff lift). Every
> node's LLM call is fully CPU-bound, and the reranker — up to 3 sequential LLM calls scoring up to 30
> passages each — is the dominant per-sub-question cost, observed up to ~10 minutes for one rerank
> call. Presented the tradeoff to the user rather than picking unilaterally (shrinking the reranker's
> candidate window trades away some of the recall margin the 2026-08-17 reranker work was built to
> buy back); they chose a middle point. `RERANK_CANDIDATE_LIMIT` lowered 30 → 15
> (`src/rag/hybrid/retriever.py`) — still covers the RRF ranks (~12, ~24) real answers have actually
> landed at this session, but is a real, acknowledged thinner margin than 30 for a harder query.
- [ ] ⚠ Partial — Retrieval configuration is **versioned** (§14) and appears in the run manifest — version
      constants exist (`CHUNKING_CONFIG_VERSION`, `RETRIEVAL_CONFIG_VERSION`) and `RunManifest`
      (Phase 0) can represent them, and `run_research()` now does construct and persist a
      manifest-shaped dict on `Report.run_manifest` for every real run (model, critic verdict).
      **Still a gap:** that persisted dict does not yet include the `CHUNKING_CONFIG_VERSION` /
      `RETRIEVAL_CONFIG_VERSION` constants themselves — the two pieces are wired to each other now,
      just not completely.

### Evidence & citations
- [x] ❗ Evidence chain built **forward**: Source → Passage → Evidence item → Claim → Citation →
      Synthesis — now **real, not schema-only**. `src/graph/pipeline.py::run_research` populates
      `evidence_items → claims → citations` from a real retrieval, in that order: the final report
      text is assembled *from* the validated `Claim`/`Citation` rows after citation validation,
      never from the Synthesizer's free-text prose (docs/08's "build forward, never reconstruct").
      **Verified live** end-to-end (`tests/integration/test_research_pipeline_live.py`, real SEC
      filing → real Qdrant retrieval → real Qwen3 reasoning chain → real PostgreSQL rows) plus
      `tests/unit/test_pipeline.py`. This is the linear MVP pipeline (docs/00); the cyclic
      LangGraph loop with a conditional sufficiency gate is still V2.
- [x] Machine-readable provenance per claim — `EvidenceItem.chunk_id`/`supporting_passage` and
      `Citation.document_id`/`justification` are now written for real from the retrieval hit's
      Qdrant payload, not left empty.
- [x] Citation validator — entailment gate with accept / rewrite / remove / **flag** — wired via
      `run_citation_validator` (`src/prompts/citation_validator/v1.yaml`), called once per
      claim/evidence pair in `run_research()`. All four verdicts are handled distinctly: ACCEPT and
      REWRITE change the shipped claim text, REMOVE silently drops the claim, and FLAG still ships
      the claim marked `[uncertain]` rather than being dropped like REMOVE — a real bug (FLAG was
      initially indistinguishable from REMOVE) was found via `test_flag_verdict_marks_claim_uncertain`
      and fixed.
- [x] Insufficient evidence is **declared**, not papered over — `ResearchJob.insufficient_evidence`
      is now set `True` and a fixed `DECLARED_INSUFFICIENT` report is returned whenever either no
      sub-question yields verified evidence, or every claim's citations resolve to REMOVE. Exercised
      by both unit tests and structurally by the live test (which asserts the pipeline reaches one
      of the two honest outcomes — cited claims or a truthful insufficiency declaration — and never
      an empty non-insufficient report).

### Application
- [x] FastAPI: create job, stream job (SSE), fetch report / evidence — `apps/api/routers/jobs.py`:
      `POST /jobs` (writes a PENDING `ResearchJob`, enqueues the Celery task, 202), `GET /jobs/{id}`
      (status + `progress_detail` + final report once `SUCCEEDED` + full `claims`/`citations`/
      evidence detail for the evidence panel + `error_message` once `FAILED`), `GET
      /jobs/{id}/stream` (SSE `event: status` and `event: progress` frames, polling a fresh
      short-lived session per tick since the job is updated by a different process). **Verified
      live**: real jobs posted to a real running API, picked up by a real Celery worker, reaching
      `succeeded` with a real cited report and a real browser rendering it — see the 2026-08-15 and
      2026-08-17 callouts above.
- [x] ✅ **D-8** 🔒 — job queue → **Celery + Redis**; LangGraph checkpoints stay in PostgreSQL, Redis
      carries transport only. `src/core/celery_app.py` + `src/graph/tasks.py` (`research` queue) —
      **verified live** against a real Redis broker/backend and a real `--pool=solo` worker. ⚠ Only
      the `research` queue has a task; `ingestion` is routed but nothing implements it yet (see the
      ingestion-workers gap above) — `ingest_filing` is still Python-function-only.
- [x] React workspace: question input, progress stream, report view, evidence panel — `apps/web`
      (React + TypeScript + Tailwind + Vite): `QueryForm`, `JobProgress` (live per-stage SSE detail,
      not just three coarse steps), `ReportView`, `EvidencePanel` (claim → citation → passage/
      document, including REMOVE-status claims shown struck-through rather than hidden — the honest
      "here's what got filtered out and why" view, not just the polished report). **Verified live**
      in a real headless browser against the real running stack, screenshots at each state, zero
      console errors. Required adding CORS middleware to `apps/api/main.py` (previously configured
      but never wired) for the dev server's origin.

### Evaluation
- [ ] **Start the benchmark dataset** — questions + gold relevant chunks — not started; this is
      unbudgeted manual authorship work (D-14) independent of the code in this pass.
- [ ] Retrieval metrics harness: Recall@K, Precision@K, MRR, nDCG — not built. (The ingredients this
      pass *did* verify — real hybrid search returning the right document for a real query — are the
      kind of case a Recall@K harness would formalize, but no harness exists yet.)

### ✅ Exit gate
- [x] A cited financial research report works end-to-end — **the core mechanism is met, as of
      2026-08-15, now with a real UI and materially better retrieval precision as of 2026-08-17.** A
      real HTTP request (`POST /jobs`) against a real running API, picked up by a real Celery worker,
      ran the full Planner → Query Decomposer → {retrieve → extract → verify → detect
      contradictions} → Synthesize → Critic → Citation Validator chain against a real, live-ingested
      NVIDIA 10-Q and real Qwen3, and returned (`GET /jobs/{id}`) a report built from validated,
      persisted `Claim`/`Citation` rows — not the Synthesizer's raw prose — now renderable in a real
      browser (`apps/web`) instead of only via curl. Live testing across three passes found and
      fixed real bugs at every layer (see the 2026-08-14/15/17 callouts above): Qwen3's thinking mode
      eating the token budget, a FLAG-verdict claim dropped like REMOVE, a cross-event-loop engine
      crash, a company-name filter silently zeroing retrieval, a real answer ranking far outside any
      reasonable retrieval window, and a reranker whose CPU-inference output wasn't reliably
      deterministic even at temperature=0.0. **What "met" does not mean here:** the phase checklist
      above still has real gaps — only one company's corpus (NVDA), no IR/transcript adapters, no
      benchmark dataset, the reranker is LLM-based (not the dedicated cross-encoder D-20 named) with
      a documented discrimination ceiling at large candidate counts, no retrieval metrics harness.
      The exit criterion is a single sentence about the mechanism working; the rest of this phase's
      checklist is the surrounding scope that sentence doesn't cover.

### Summary of this pass (2026-08-17)
Three things, in the order the user asked for them and in the order they turned out to depend on
each other. **(1) UI/UX**: built the React frontend (`apps/web`) and, in verifying it against a real
job, found the API gave no progress visibility beyond one static "running" status for a multi-minute
run — added `ProgressCallback` threading through `run_research()` and `ResearchJob.progress_detail`
(migration 0003) so the SSE stream now emits real per-stage detail. **(2) Corpus breadth**: not
reached this pass — see below. **(3) The agentic loop**: not reached either — testing (1) surfaced a
retrieval-precision problem serious enough that neither breadth nor a retry loop would have been
worth building on top of it. Chased live: a real NVDA revenue question's answer retrieved at fused
rank ~22-41 out of 42 — three rounds of widening `top_n_per_subquestion` (5→15→30) and the
corresponding extractor/verifier token budgets (evidence_extractor v2→v3→v4, verifier v2→v3) each
fixed the specific failure they targeted and immediately hit the next one (missing evidence →
truncated JSON → a >100K-character prompt timing out), which is what motivated building the
reranker (`apps/reranker/main.py`, LLM-based listwise scoring — no torch/transformers dependency
added) instead of continuing to raise constants. Building *that* surfaced the pass's most important
finding: the exact same real query and passage set, reranked twice at temperature=0.0, came back
once correct and once with every passage scored identically — verified as genuine CPU-backend
non-determinism (not a prompt bug) by testing isolated single-passage scoring, which was correct in
every trial. Fixed with a retry-on-degenerate-output loop, not by trusting the first answer. Honestly
documented, not hidden: at large candidate counts (~30 real, structurally-similar financial
passages), even three retries don't guarantee a 4B CPU-served model discriminates reliably — a real
capability ceiling, not a bug, consistent with D-1's own note that self-hosted models are weaker than
frontier ones at this kind of task. 163 unit tests pass; ruff and mypy clean across 57 source files.

### Summary of the previous pass (2026-08-15)
Wired the API/worker layer onto the reasoning core from the previous pass, and — per this project's
standing rule — verified it by actually driving the system live rather than trusting unit tests:
`POST /jobs` → real Celery task (`--pool=solo`, real Redis) → real `run_research()` → `GET
/jobs/{id}` returning a real report, plus an SSE status stream. That live path is what surfaced three
new real bugs unit tests couldn't have (cross-event-loop engine reuse crashing a second sequential
job; a company-name metadata filter silently zeroing retrieval despite the evidence being present;
an LLM call timeout too tight for the evidence-extraction node) — all fixed, all covered by new
regression tests, and the live pipeline test re-run clean afterward (1014s). 144 unit tests pass;
ruff and mypy clean across 56 source files. Explicitly **not** attempted in this pass: the ingestion
Celery queue (`ingest_filing` is still Python-function-only), the React frontend, the reranker's real
serving path, and the benchmark dataset.

### Summary of the previous pass (2026-08-14)
Built and verified against **real, live services** (not mocks) for every piece except the LLM-calling
reasoning steps: PostgreSQL schema, MinIO object storage, the SEC EDGAR adapter, the HTML parser, the
chunker, the Ollama embedding client, Qdrant hybrid (dense+sparse) retrieval with structural filter
parity, RRF fusion, and the ingestion pipeline tying them together — end to end, on a real NVIDIA
8-K, including a genuine dedup no-op on re-ingestion. 117 tests pass (unit + integration). Explicitly
**not** attempted in this pass: any LLM-calling node (Planner through Citation Validator), the
FastAPI job/streaming endpoints, Celery task wiring, the React frontend, the reranker's real serving
path (gated on D-30), and the benchmark dataset (unbudgeted manual work, D-14). These are the natural
next slice — the docs' own ordering logic ("retrieval quality before agency") argues for building
this ingestion/retrieval spine first, which is what this pass did.

---

# Phase 2 (V2) — LangGraph Agentic Research Loop

**Exit criterion:** the agent researches and retries when evidence is insufficient.
**Docs:** [06](06-agent-langgraph.md) · [11](11-security-and-safety.md)

### Decisions due this phase — all resolved 2026-08-14
- [x] ✅ **D-4** 🔒 — "External tools" branch **removed**; replaced by named `quant` / `market_data` /
      `SEC/XBRL` / `web/news` (opt-in) tools, each with its own schema, permission, and audit trail
- [x] ✅ **D-10** 🔒 — Checkpointer → **PostgreSQL**
- [x] ✅ **D-13** 🔒 — News: no arbitrary full-text ingestion; metadata + headline + URL + permitted
      excerpt only, full text requires an explicit licence check
- [x] ✅ **D-21** 🎛️ — Max iterations 5, max tool calls 20, max parallel branches 3, max LLM calls 30
      *(must absorb structured-output retries — see Guardrails below)*
- [x] ✅ **D-29** 🔒 — MCP: `quant` server first; **retrieval deliberately excluded**, not deferred;
      stdio for dev, local/private HTTP for production → [14](14-mcp-assessment.md)

### Graph
- [ ] `ResearchState` with all sixteen fields — see [06](06-agent-langgraph.md)
- [ ] Checkpointer wired; **persistent research state** survives worker restart
- [ ] LangChain tool definitions for retrieval and document search
- [ ] Node — Planner (3–5 sub-questions per §18)
- [ ] Node — Query Decomposer (sub-questions + retrieval filters)
- [ ] Node — Parallel Research fan-out
- [ ] Node — Evidence Extraction
- [ ] Node — Verification
- [ ] Node — Gap / contradiction detection
- [ ] **Conditional edge** — evidence sufficient? → Research Again ⟲ or Synthesis
- [ ] Node — Synthesis
- [ ] Node — Critic
- [ ] Node — Citation Validator → FINAL
- [ ] Research Again re-enters retrieval with **revised** filters informed by the detected gap

### Guardrails
- [ ] ❗ **Structured outputs between every node** — no prose handoffs
- [ ] ❗ **Constrained decoding or validate-and-retry** for structured output — required with a
      self-hosted model, not a refinement ([06](06-agent-langgraph.md))
- [ ] Maximum research iterations
- [ ] Maximum tool calls per research job — ❗ the counter must count **MCP calls** too
- [ ] Token budget enforced from state — ❗ must absorb structured-output retries
- [ ] Cost budget enforced from state, on **imputed** cost ([17](17-ai-configuration-versioning.md))
- [ ] **Explicit stopping criteria** with a defined answer for every exit path
- [ ] ❗ Budget exhaustion produces a report that **declares insufficiency**, never a confident answer
- [ ] Explicit, narrow tool permissions per node (§12) — ❗ **per-node allowlists must survive the
      MCP boundary**; server-level exposure is not node-level permission
- [ ] Tool-argument validation (§12) — ❗ **server-side as well as client-side**

### Serving (⚙ owner additions)
- [ ] Ollama health-checked at worker startup; unreachable **fails the job loudly**
- [ ] ❗ Measure whether the **Parallel Research fan-out actually runs concurrently**, or serializes
      behind Ollama — if it serializes, the fan-out's architectural benefit is gone
      ([D-30](15-open-decisions.md))
- [ ] Prometheus scraping Ollama saturation from this phase, ahead of the V4 observability build

### Corpus
- [ ] Earnings-transcript retrieval branch, if not completed in V1
- [ ] ❗ News ingestion **only after** retrieval evaluation is stable (`datasource.txt` §3) and D-13
      is resolved

### Evaluation
- [ ] Agent metrics: tool-selection accuracy, unnecessary calls, research completeness, iteration
      count

### ✅ Exit gate
- [ ] The agent researches and retries when evidence is insufficient

---

# Phase 3 (V3) — Quantitative Analysis Engine

**Exit criterion:** research reports combine retrieved evidence with deterministic calculations.
**Docs:** [07](07-quant-engine.md)

### Decisions due this phase — all resolved 2026-08-14
- [x] ✅ **D-6** 🔒 *(was the largest gap in the spec)* — `MarketDataProvider` adapter over a free
      provider; PostgreSQL (canonical) + MinIO/Parquet (bulk); every record carries
      `timestamp`/`observed_at`/`effective_at`/`source`; raw data + adjustment metadata, never
      silently mixed; missing required data fails loudly; 🎛️ benchmark = S&P 500/SPY, risk-free =
      US Treasury series recorded in the run manifest
- [x] ✅ **D-17** 🔒 — Macro data **not** summarized into RAG by default
- [x] ✅ **D-22** 🔒 — Strict Pydantic schemas for all nine tools; annualization fixed (252/52/12);
      missing data fails loudly; 🎛️ benchmark/risk-free supplied by the D-6 market-data layer

### Data
- [ ] Market-data ingestion — OHLCV, returns, volume — into the **quant store, not the vector store**
- [ ] Macro data ingestion — rates, CPI, GDP — into the quant/data layer

### Tools
- [ ] `calculate_returns`
- [ ] `calculate_volatility`
- [ ] `calculate_sharpe`
- [ ] `calculate_max_drawdown`
- [ ] `calculate_beta`
- [ ] `calculate_correlation`
- [ ] `compare_assets`
- [ ] `event_study` — pre-event baseline; **+1 / +3 / +5 / +20 trading-day** windows; absolute **and**
      benchmark-adjusted returns; volume and volatility changes
- [ ] `backtest_strategy`

### Backtesting guarantees (§7)
- [ ] Train/in-sample vs out-of-sample separation
- [ ] Walk-forward validation where appropriate
- [ ] Transaction costs
- [ ] Slippage assumptions
- [ ] ❗ No look-ahead bias — enforced structurally via `filing_date` and point-in-time market data
- [ ] No survivorship-bias shortcuts where avoidable
- [ ] ❗ Historical analysis explicitly distinguished from future prediction
- [ ] Assumptions and historical-data limitations disclosed with every backtest result

### Correctness
- [ ] ❗ Unit tests with known-answer fixtures for **every** quant function
- [ ] Edge cases: insufficient data, missing days, zero-variance series, single-observation windows
- [ ] Missing-data behaviour explicit — ❗ fail loudly rather than silently interpolate

### Integration
- [ ] Structured quant results flow into `ResearchState.quantitative_results`
- [ ] Frontend charts for quantitative output
- [ ] Quant metrics: Sharpe, drawdown, turnover, transaction costs, out-of-sample performance

### ⚙ MCP servers — build the tools first, wrap them second
- [ ] `src/mcp/quant` server exposing all nine §7 tools — **only after** their known-answer tests pass
- [ ] `src/mcp/market-data` server (gated on D-6)
- [ ] ❗ No LLM inside any quant server — MCP is transport, never a source of numbers
- [ ] Servers **co-located** with the research worker; health-checked at startup
- [ ] ❗ `research_id` propagates **across the protocol boundary**; servers emit spans under it
- [ ] Audit rows for MCP tool calls still land in PostgreSQL
- [ ] ❗ No `retrieval` MCP server — decided against in D-29, not a measurement gate to revisit

### ✅ Exit gate
- [ ] Research reports combine retrieved evidence with deterministic calculations

---

# Phase 4 (V4) — Production Hardening

**Exit criterion:** a production-quality deployed application with traces and controls.
**Docs:** [09](09-caching-and-prompts.md) · [10](10-observability.md) · [11](11-security-and-safety.md) · [12](12-infrastructure-and-deployment.md)

### Decisions due this phase — all resolved 2026-08-14
- [x] ✅ **D-5** 🔒 — Human review → LangGraph interrupt + checkpoint; triggers on low confidence,
      unresolved contradiction, citation failure, high-impact quant/research output, or a backtest
      requiring review; 🎛️ exact thresholds tuned later
- [x] ✅ **D-11** 🔒 — Auth → **JWT + multi-tenant** (tenancy question already decided in V1)
- [x] ✅ **D-24** 🎛️ — Embeddings 30d / retrieval 24h / LLM 24h / job-state no TTL while active
- [x] ✅ **D-27** 🔒 — Two IDs: `research_id` (product-level, stable) + `trace_id` (OTel, per-execution)
- [x] ✅ **D-28** 🎛️ — CI runs a fixed 20-question subset; fails on >5% Recall@K / MRR / citation-
      correctness regression or a test failure; full benchmark nightly/release
- [x] ✅ **D-31** 🔒 label discipline / 🎛️ dashboards — API/RAG/LLM/worker/Ollama/MCP metric families;
      low-cardinality labels only, `research_id` never a label
- [x] ✅ **D-25** — Prompt versioning *(resolved 2026-08-14; implemented at Phase 0)*
- [x] ✅ **D-26** — Per-call accounting → **LangSmith + PostgreSQL + Prometheus** *(2026-08-14)*

### Caching (§9)
- [ ] Embeddings cache — key: text + embedding model/version; invalidate on model change
- [ ] Retrieval cache — key: query + **filters** + retrieval config/version; invalidate on config change
- [ ] LLM cache — key: model + prompt version + input + generation settings
- [ ] Job-state cache — key: `research_job_id`; **transient only**
- [ ] ❗ Every cache key contains its version component (§20)

### Prompts & accounting
- [x] Versioned prompt repository *(delivered at Phase 0)*
- [ ] **Versioned retrieval configurations** so experiments never silently alter production (§14)
- [ ] Per-LLM-call record: model, prompt version, temperature/generation settings, token usage,
      latency, cost — written to **PostgreSQL and LangSmith**
- [ ] ❗ **Imputed cost** (tokens × configured rate) recorded alongside real wall-clock/compute time;
      the rate is part of the run manifest ([17](17-ai-configuration-versioning.md))
- [ ] Budget enforcement reads from **PostgreSQL**, never from an external service
- [ ] Run manifest persisted with every stored report

### Observability (§11 + ⚙ owner additions)
- [ ] LangSmith — LLM traces, graph execution, prompt versions, tool calls, RAG/eval runs
- [ ] OpenTelemetry — API traces, worker traces, DB/Redis latency, infra health, cross-service
      propagation
- [ ] ⚙ Prometheus — §10 System metrics, Ollama saturation, MCP server health and call latency
- [ ] ⚙ Grafana dashboards
- [ ] ❗ No high-cardinality labels in Prometheus — `research_id` belongs in traces and PostgreSQL
- [ ] ❗ `research_id` / `trace_id` propagated API → worker → graph → tools → **across MCP** → final
      report
- [ ] Durable audit log in PostgreSQL: major tool calls and state transitions

### Security (§12)
- [ ] Authentication and authorization for research history and private documents
- [ ] ❗ If multi-tenant: tenant isolation enforced in **Qdrant filters and BM25 filters**, not only
      PostgreSQL rows
- [ ] Rate limiting and abuse controls
- [ ] Secrets only in managed secret/environment configuration
- [ ] ❗ Prompt-injection posture verified: retrieved text can never override system instructions;
      content separated from instructions
- [ ] Product-boundary enforcement in output: informational / decision-support labelling; no
      guaranteed returns; no autonomous execution; **no brokerage connection**
- [ ] Uncertainty and evidence gaps surfaced rather than a conclusion forced

### Deployment (§13, §14)
- [ ] Evaluation smoke tests added to the CI chain
- [ ] Frontend on Vercel or equivalent
- [ ] Dockerized FastAPI on a container platform
- [ ] **Separate** research worker service
- [ ] Managed PostgreSQL · Managed Redis · Qdrant Cloud · **MinIO** · Cloudflare/CDN
- [ ] ⚙ Ollama on a GPU host, **private network, never internet-exposed**
- [ ] ⚙ Reranker server deployed
- [ ] ⚙ MCP servers deployed **co-located with the research worker**
- [ ] ⚙ Prometheus + Grafana
- [ ] Staging environment live and **gating** production
- [ ] Production deployment
- [ ] ❗ Kubernetes **not** introduced (§13, §20) — running GPUs is not a demonstrated scaling
      requirement

### Evaluation
- [ ] System metrics: latency, token usage, cost, error rate, cache hit rate

### ✅ Exit gate
- [ ] A production-quality deployed application with traces and controls

---

# Phase 5 (V5) — Evidence Graph, Evaluation & Experimentation

**Exit criterion:** measurable retrieval / agent / quant improvements.
**Docs:** [08](08-evidence-citations.md) · [13](13-evaluation.md)

### Decisions due this phase — all resolved 2026-08-14
- [x] ✅ **D-7** 🔒 — Evidence graph → **PostgreSQL relational** tables (documents/chunks/
      evidence_items/claims/citations/reports, joined by foreign key)
- [x] ✅ **D-12** 🔒 method / 🎛️ thresholds — Deterministic numeric check first, then LLM qualitative
      judgement; never silently average conflicting evidence
- [ ] ✅ **D-14** — Benchmark ground truth **complete** *(authorship process resolved in V1; this box
      tracks reaching full coverage, not a remaining decision)*
- [x] ✅ **D-32** 🔒 — Experiment records → **Git** (config + result summary) + **LangSmith** (runs/
      traces) + **PostgreSQL** (durable `experiment_id` → metrics)
- [x] ✅ **D-9** — MCP → **adopted** *(2026-08-14; servers built in V3)* → [14](14-mcp-assessment.md)

### Build
- [ ] Claim/evidence graph
- [ ] Contradiction detection — numeric conflicts and qualitative conflicts
- [ ] Human review path implemented (D-5)

### Benchmark suite
- [ ] Benchmark dataset complete and **frozen**
- [ ] Retrieval: Recall@K · Precision@K · MRR · nDCG
- [ ] RAG: context relevance · answer relevance · faithfulness
- [ ] Citations: citation correctness · citation completeness · claim-support rate
- [ ] Agent trajectory evaluation
- [ ] Full quant backtest metric suite

### The seven ablations (§10)
- [ ] Dense vs BM25 vs hybrid retrieval
- [ ] Hybrid vs hybrid + reranker
- [ ] No metadata filtering vs metadata filtering
- [ ] No query rewriting vs query rewriting
- [ ] ❗ **Single-shot RAG vs iterative LangGraph research** — the honest test of the agentic layer
- [ ] Prompt v1 vs prompt v2
- [ ] ❗ **No cache vs cache** — must improve latency/cost **without changing answers**; if answers
      change, the cache identity is wrong

### Recording
- [ ] Every experiment records the **full run manifest**: prompt · LLM · embedding · reranker ·
      chunking · retrieval config · RRF params · benchmark version · git SHA
- [ ] Plus all relevant metrics, imputed cost, and latency
- [ ] ❗ **A metric without its configuration is not a result** — it cannot be compared, which makes
      it worse than no metric, because it looks like one
      ([17](17-ai-configuration-versioning.md))
- [ ] ❗ No optimization by intuition (§20)

### ✅ Exit gate
- [ ] Measurable retrieval / agent / quant improvements demonstrated by controlled experiment

---

# Standing rules — verified at every phase gate (§20)

- [ ] The LLM is never the calculator
- [ ] Retrieved text is never trusted
- [ ] Retrieval quality is benchmarked, never assumed
- [ ] No agent exists without a reason
- [ ] No citation ships unvalidated
- [ ] No cache key omits model / prompt / retrieval version
- [ ] Nothing reaches production without staging
- [ ] No infrastructure beyond Docker + managed services until scaling is demonstrated
- [ ] No backtest is presented as a prediction
- [ ] No optimization without a recorded experiment

### ⚙ Added by the 2026-08-14 stack decision
- [ ] No prompt is fetched from a service at runtime — Git is the source of truth
- [ ] No committed prompt version is edited in place
- [ ] No model tag is unpinned
- [ ] No result is recorded without its run manifest
- [ ] No tool permission is delegated to server-level exposure
- [ ] No `research_id` is dropped at a protocol boundary

### 🔒 vs 🎛️ — checked whenever a resolved decision changes

- [ ] A change to a 🔒 **locked** item (provider, embedding model, vector DB, sparse engine,
      checkpointer, tool protocol, auth model, object storage, job queue, evidence-graph storage) is
      treated as a **migration**: scoped, planned, and not slipped in alongside unrelated work
- [ ] A change to a 🎛️ **tunable** item (chunking, retrieval config, model size per node, cache TTLs,
      guardrail limits, CI thresholds) ships as a **new version**, is measured against the frozen
      benchmark, and is recorded as an experiment ([D-32](15-open-decisions.md)) — never applied by
      intuition alone

---

# Master checklist (§17, verbatim coverage)

Cross-reference confirming every item from the blueprint's own §17 checklist is covered above.

### Architecture
Clear service boundaries · Async research jobs · Persistent research state · Versioned documents ·
Evidence provenance

### RAG
Chunking · Embeddings · Qdrant · Metadata filtering · BM25 · Hybrid retrieval · Reranker · Query
rewriting · Context compression · Citation validation

### Agentic
LangChain tools · LangGraph state · Planner · Parallel research · Verification · Gap detection ·
Retry loop · Critic · Explicit stopping criteria

### Quant
Returns · Volatility · Sharpe · Drawdown · Beta/correlation · Event study · Backtesting ·
Out-of-sample evaluation · Costs/slippage

### Production
Redis · PostgreSQL · Object storage (MinIO) · Authentication · Rate limiting · Prompt versioning ·
Cost tracking · LangSmith · OpenTelemetry · Docker · CI/CD · Staging · Production deployment
⚙ *plus* Ollama · reranker server · MCP servers · Prometheus · Grafana

### Evaluation
Benchmark dataset · Recall@K · MRR · nDCG · Citation correctness · Faithfulness · Agent trajectory
evaluation · Latency · Cost · Cache hit rate · Quant backtest metrics

---

## The final objective, as an acceptance test

> Build a system that can explain **not only what it concluded, but why it concluded it, which
> evidence supports it, how the numbers were calculated, what evidence contradicts it, how the system
> performed on benchmarks, and how the production system behaves under real workloads.**

| Clause | Demonstrated by | Phase |
|---|---|---|
| What it concluded | Cited report | V1 |
| Why it concluded it | Persistent research state, traces | V2, V4 |
| Which evidence supports it | Forward-built evidence chain, validated citations | V1 |
| How the numbers were calculated | Deterministic quant engine | V3 |
| What evidence contradicts it | Contradiction detection | V5 |
| How it performed on benchmarks | Frozen benchmark + seven ablations | V5 |
| How production behaves | LangSmith + OpenTelemetry + system metrics | V4 |
