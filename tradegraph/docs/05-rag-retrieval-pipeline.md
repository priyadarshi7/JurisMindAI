# 05 — RAG & Retrieval Pipeline

> **Source:** Blueprint §5 (Retrieval Pipeline).
> **Status:** Specification-derived. The "problem it solves" column is our justification.

---

## Pipeline

```
User query
  → Intent + entity extraction
  → Query rewriting / decomposition
  → Metadata constraints
  → Dense retrieval  ‖  BM25            (parallel)
  → Reciprocal Rank Fusion
  → Top-N candidate set
  → Cross-encoder / reranker
  → Top evidence
  → Context selection / compression
  → Evidence extractor
```

---

## Stage by stage

| Stage | What it does | The problem it solves |
|---|---|---|
| **Intent + entity extraction** | Identifies the question type and the entities in it | Financial questions carry hard constraints — company, ticker, fiscal period, document type. Extracting them early turns free text into something filterable. |
| **Query rewriting / decomposition** | Rewrites and/or splits the query | User questions are compound ("compare the fundamental and market-risk profiles of two companies"). A single embedding of a compound question retrieves poorly for *every* part of it. |
| **Metadata constraints** | Builds filters from extracted entities | Prevents the worst failure mode in filings RAG: retrieving the *right passage from the wrong company or wrong quarter*. Applied **before** retrieval, not after. |
| **Dense retrieval** | Vector search in Qdrant, over **Qwen3 Embedding** vectors | Semantic recall — matches paraphrase and concept ("margin compression" ↔ "gross margin declined"). |
| **BM25** | Lexical search | Exact-term recall. §3 names the reason: exact names, tickers, identifiers, financial terminology. Embeddings blur precisely the tokens finance depends on. |
| **Reciprocal Rank Fusion** | Merges the two ranked lists | Dense scores and BM25 scores are on incomparable scales. RRF fuses by **rank**, not score, so no normalization weight needs tuning per query. |
| **Top-N candidate set** | Truncates the fused list | Bounds the cost of the expensive next stage. |
| **Reranker — Qwen3 Reranker** | Re-scores query–passage pairs jointly | Bi-encoders embed query and passage independently, so the top of the list is noisy. Joint scoring reads both together — much higher precision, affordable only over a bounded N. |
| **Context selection / compression** | Selects and compresses passages | Keeps the synthesis context inside budget while preserving the passages that actually support claims. |
| **Evidence extractor** | Passages → structured evidence items | The entry point to the claim/citation chain of §8. Retrieval ends here; provenance begins here. |

---

## Why hybrid retrieval is non-optional here

The two arms fail on opposite inputs:

| Query | Dense alone | BM25 alone | Hybrid |
|---|---|---|---|
| "What drove gross margin compression?" | ✅ finds "gross margin declined due to…" | ❌ misses the paraphrase | ✅ |
| "Item 7A quantitative disclosures for NVDA" | ❌ blurs `Item 7A`, `NVDA` | ✅ exact match | ✅ |
| "ASC 606 revenue recognition change" | ⚠ partial | ✅ exact | ✅ |

Financial research produces both query shapes constantly, often in the same question. §10 requires
this be **proven, not assumed** — the first ablation is *dense vs BM25 vs hybrid*. See
[13-evaluation.md](13-evaluation.md).

---

## Full technique inventory (§5)

The RAG techniques carried over from the source project:

- Semantic retrieval
- Metadata filtering
- Vector + BM25 hybrid retrieval
- Reranking
- Query rewriting
- Multi-query retrieval
- Context compression
- Citation / source attribution
- Retrieval evaluation with **Recall@K** and **MRR**

Every one of these appears in the §17 Master Checklist and in
[16-implementation-plan.md](16-implementation-plan.md).

---

## Vector store decision — closed

> **Qdrant is the primary vector store** in the final production architecture. **Chroma is not
> required**; it may be used **only** as a temporary local prototype if it accelerates an
> experiment. (§5)

This is settled. Chroma must never appear in a deployment path, a Docker Compose file intended for
staging/production, or the CI pipeline.

---

## Retrieval configuration is versioned

§14: *"Retrieval configurations and prompts should be versioned so experiments do not silently alter
production behavior."*

This connects directly to the §9 cache identity rule: the **retrieval cache key includes the
retrieval config version**, so changing a config cannot serve results computed under a different
one.

A retrieval configuration includes at minimum:

- embedding model + version
- top-k for dense, top-k for BM25
- RRF parameters
- reranker model + top-N
- context compression settings

✅ **Resolved 2026-08-14 ([D-20](15-open-decisions.md)), 🎛️ tunable V1 baseline** — established as a
versioned default, to be tuned empirically against the frozen benchmark, not a permanent answer:

| Parameter | Starting value |
|---|---|
| Chunk size / overlap | 700 / 100 tokens ([D-19](15-open-decisions.md)) |
| Dense top-K | 30 |
| Sparse (BM25) top-K | 30 |
| Fusion | Standard RRF |
| Candidate set | ~30–50 unique chunks |
| Reranker top-N | 7 |
| Final context | 5–7 passages |

The retrieval config version is part of the run manifest and the retrieval cache key, so tuning these
is a versioned, cache-invalidating event by design —
[17-ai-configuration-versioning.md](17-ai-configuration-versioning.md).

---

## Model serving for the retrieval path

The embedder and reranker are both **self-hosted** ([D-1](15-open-decisions.md),
[D-2](15-open-decisions.md)), which changes the operational picture for this pipeline:

| Component | Model | Served by |
|---|---|---|
| Dense embeddings | Qwen3 Embedding | Ollama |
| Reranking | Qwen3 Reranker | ❗ **not Ollama** — see below |

❗ **Ollama exposes generation and embedding endpoints but has no rerank API.** The reranker very
likely needs its own serving path — Text Embeddings Inference, vLLM, or a small FastAPI wrapper over
`transformers`. Confirm this before V1: it is an additional deployable, an additional health check,
and an additional hop in the retrieval path. Tracked as [D-30](15-open-decisions.md).

Two further consequences of self-hosting:

- **The embeddings cache (§9) now saves latency and GPU time rather than money.** It matters more,
  not less — query embedding sits on the critical path of every retrieval.
- ❗ **Pin the embedding dimension before creating the Qdrant collection.** Qwen3 Embedding supports
  Matryoshka truncation, so the dimension is a *choice*. Changing it later invalidates every vector
  and forces a full corpus re-embed.

---

## Interaction with the agent

Retrieval is invoked from graph nodes, not called directly by the API. In the §6 workflow it appears
in three places:

1. **Parallel Research** fan-out — financial document retrieval and news/document retrieval branches
2. **Research Again → Retrieval** — the loop-back path when evidence is insufficient
3. Implicitly, wherever `retrieval_filters` from the Query Decomposer are applied

The second is the reason retrieval must be **parameterized by filters held in graph state** rather
than derived fresh from the original query each time — the second pass should search differently from
the first, informed by the detected gap.

See [06-agent-langgraph.md](06-agent-langgraph.md).

---

## Evaluation hooks

Retrieval is the most heavily benchmarked subsystem in the project.

| Metric | Measures |
|---|---|
| Recall@K | Did we retrieve the relevant chunks at all? |
| Precision@K | How much of what we retrieved was relevant? |
| MRR | How high was the first relevant result? |
| nDCG | Rank-weighted quality of the whole list |

❗ §20: **"Do not hide retrieval quality. Benchmark it."**
❗ §10: create the benchmark dataset **before** optimizing, and keep it fixed.

Detail: [13-evaluation.md](13-evaluation.md).
