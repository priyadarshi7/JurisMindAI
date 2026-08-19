"""Hybrid retriever — dense + BM25 sparse, fused by RRF, optionally reranked
(docs/05, D-20).

Ties together the Qdrant store, the Ollama embedder, and the BM25 sparse
encoder. The one thing this class enforces structurally: **the same
`query_filter` object goes to both `search_dense` and `search_sparse`** —
there is no code path that lets the two arms see different filters, which
is what makes D-3's filter-parity requirement a property of the code
rather than a discipline someone has to remember.

❗ Reranking exists because RRF score alone is not precision — found live
(2026-08-17): a real NVDA revenue question's actual answer (a numeric
table) ranked ~22-41 out of a 42-candidate fused pool, well outside any
reasonable `top_n`. A bare table embeds/BM25-matches weakly against a
narrative question even though it's the right answer. The reranker
re-scores the wider candidate pool by actual relevance before the final
`top_n` cut, so `top_n` can go back to a small, precise number instead of
needing to widen indefinitely to catch a low-ranked correct answer.

❗ Reranking sends **truncated previews**, not full passage text — found
live, same day: real chunks run up to ~3400 chars each, so 40 full
candidates made a >100K-character single prompt that either timed out or
came back with degenerate all-zero scores (a synthetic test with short
one-line filler passages worked fine at the same candidate count — the
model wasn't broken, the real prompt was just too large to reason over
in one pass). A few hundred characters is enough to judge topical
relevance; the *unmodified* full text still reaches evidence_extractor
afterward via the same payload, only the reranker's own input is
shortened.
"""

from __future__ import annotations

from dataclasses import dataclass

from qdrant_client.models import Filter

from src.observability.metrics import RETRIEVAL_LATENCY
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.hybrid.fusion import RankedResult, reciprocal_rank_fusion
from src.rag.reranking.reranker_client import RerankerClient
from src.rag.vector.qdrant_store import QdrantStore

DENSE_TOP_K = 50  # docs/15 D-20 baseline was 30; widened 2026-08-18, see below
SPARSE_TOP_K = 50
RERANK_CANDIDATE_LIMIT = 40
# History (2026-08-18): lowered 30 -> 15 as a speed/recall tradeoff while
# Ollama had no GPU offload (`ollama ps` reported size_vram=0) and the
# reranker's own LLM call was the dominant per-sub-question cost (up to
# ~10 min at 30 candidates). Enabling GPU passthrough for the Ollama
# container (docker-compose.yml, previously commented out despite a real
# GPU — RTX 4050 — being present) cut a full research job from ~1511s to
# ~108s, making the speed tradeoff unnecessary. Reverted, then widened
# further: live-diagnosing why a real revenue sub-question still returned
# insufficient_evidence found the answer chunk sitting at dense rank 37 /
# sparse rank 52 — outside even the original 30/30 top-K, so it never
# reached RRF fusion at all (a distinct, deeper problem than the
# reranker's own discrimination limitation documented separately below).
# Qdrant search cost is negligible next to an LLM call, so widening
# DENSE_TOP_K/SPARSE_TOP_K to 50 (catching rank 37) and
# RERANK_CANDIDATE_LIMIT to 40 (catching the resulting fused rank ~35) was
# close to free once the reranker itself was fast. Verified live: this
# chunk was unreachable at 30/30/30 no matter how the reranker or
# extractor were tuned downstream — a retrieval-recall gap, not a ranking
# or extraction one.
RERANK_PREVIEW_CHARS = 400
# Enough to identify a table's subject line/headers or a paragraph's
# topic without sending its full body — found live, real chunks run up
# to ~3400 chars, and 30-40 of those in one prompt is what produced
# degenerate all-zero-score output (see module docstring).
RETRIEVAL_CONFIG_VERSION = (
    "hybrid_v2_reranked"  # docs/17 run-manifest field; docs/09 cache-key component
)


@dataclass(frozen=True)
class HybridSearchResult:
    point_id: str
    rrf_score: float
    payload: dict[str, object]


class HybridRetriever:
    def __init__(
        self,
        *,
        store: QdrantStore,
        embedder: OllamaEmbedder,
        sparse_encoder: Bm25SparseEncoder,
        dense_top_k: int = DENSE_TOP_K,
        sparse_top_k: int = SPARSE_TOP_K,
        reranker: RerankerClient | None = None,
        rerank_candidate_limit: int = RERANK_CANDIDATE_LIMIT,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._sparse_encoder = sparse_encoder
        self._dense_top_k = dense_top_k
        self._sparse_top_k = sparse_top_k
        self._reranker = reranker
        self._rerank_candidate_limit = rerank_candidate_limit

    def search(
        self, query: str, *, query_filter: Filter | None, top_n: int
    ) -> list[HybridSearchResult]:
        with RETRIEVAL_LATENCY.labels(stage="hybrid_retrieval").time():
            return self._search(query, query_filter=query_filter, top_n=top_n)

    def _search(
        self, query: str, *, query_filter: Filter | None, top_n: int
    ) -> list[HybridSearchResult]:
        dense_vector = self._embedder.embed_query(query).vector
        sparse_vector = self._sparse_encoder.encode_query(query)

        dense_hits = self._store.search_dense(
            dense_vector, query_filter=query_filter, limit=self._dense_top_k
        )
        sparse_hits = self._store.search_sparse(
            indices=sparse_vector.indices,
            values=sparse_vector.values,
            query_filter=query_filter,  # same object as the dense call above
            limit=self._sparse_top_k,
        )

        fused = reciprocal_rank_fusion(
            [
                [RankedResult(h.point_id, h.payload) for h in dense_hits],
                [RankedResult(h.point_id, h.payload) for h in sparse_hits],
            ]
        )

        if self._reranker is None or not fused:
            return [
                HybridSearchResult(point_id=f.point_id, rrf_score=f.rrf_score, payload=f.payload)
                for f in fused[:top_n]
            ]

        candidates = fused[: self._rerank_candidate_limit]
        previews = [str(c.payload.get("text", ""))[:RERANK_PREVIEW_CHARS] for c in candidates]
        reranked = self._reranker.rerank(query=query, passages=previews, top_n=top_n)
        return [
            HybridSearchResult(
                point_id=candidates[r.index].point_id,
                rrf_score=r.score,
                payload=candidates[r.index].payload,  # full, untruncated text
            )
            for r in reranked
            if 0 <= r.index < len(candidates)
        ]
