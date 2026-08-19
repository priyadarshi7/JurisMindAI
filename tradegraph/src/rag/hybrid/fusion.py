"""Reciprocal Rank Fusion (docs/05, D-20).

Fuses by rank, not score — dense cosine similarity and BM25-style sparse
scores live on incomparable scales, so combining them by score would need a
normalization weight tuned per query. RRF sidesteps that entirely: only
each list's *rank order* matters.
"""

from __future__ import annotations

from dataclasses import dataclass

RRF_K = 60  # standard RRF constant (docs/15 D-20: "standard RRF")


@dataclass(frozen=True)
class RankedResult:
    point_id: str
    payload: dict[str, object]


@dataclass(frozen=True)
class FusedResult:
    point_id: str
    rrf_score: float
    payload: dict[str, object]


def reciprocal_rank_fusion(
    ranked_lists: list[list[RankedResult]], *, k: int = RRF_K
) -> list[FusedResult]:
    """Standard RRF: score(d) = sum over lists containing d of 1/(k + rank).

    A point that appears in only one list still scores — RRF rewards
    consensus across lists but does not require it, which matters for the
    two failure modes hybrid retrieval exists to cover (docs/05): a
    paraphrase-only match found by dense but not sparse, and an exact-token
    match found by sparse but not dense.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, object]] = {}

    for ranked_list in ranked_lists:
        for rank, result in enumerate(ranked_list, start=1):
            scores[result.point_id] = scores.get(result.point_id, 0.0) + 1.0 / (k + rank)
            payloads.setdefault(result.point_id, result.payload)

    fused = [
        FusedResult(point_id=point_id, rrf_score=score, payload=payloads[point_id])
        for point_id, score in scores.items()
    ]
    fused.sort(key=lambda r: r.rrf_score, reverse=True)
    return fused
