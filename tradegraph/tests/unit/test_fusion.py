"""Unit tests for src.rag.hybrid.fusion (Reciprocal Rank Fusion, D-20)."""

from __future__ import annotations

from src.rag.hybrid.fusion import RankedResult, reciprocal_rank_fusion


def _r(point_id: str) -> RankedResult:
    return RankedResult(point_id=point_id, payload={"id": point_id})


def test_single_list_preserves_order() -> None:
    fused = reciprocal_rank_fusion([[_r("a"), _r("b"), _r("c")]])
    assert [f.point_id for f in fused] == ["a", "b", "c"]


def test_consensus_across_lists_outranks_single_list_top_hit() -> None:
    """A document ranked 2nd in both lists should be able to outscore a
    document ranked 1st in only one list — RRF rewards cross-arm consensus.
    """
    dense = [_r("only_dense"), _r("both")]
    sparse = [_r("only_sparse"), _r("both")]

    fused = reciprocal_rank_fusion([dense, sparse])
    ranked_ids = [f.point_id for f in fused]

    assert ranked_ids[0] == "both"


def test_score_matches_hand_computed_rrf_formula() -> None:
    dense = [_r("x")]
    sparse = [_r("x")]
    fused = reciprocal_rank_fusion([dense, sparse], k=60)

    expected = 1.0 / (60 + 1) + 1.0 / (60 + 1)
    assert fused[0].rrf_score == expected


def test_point_present_in_only_one_list_still_included() -> None:
    dense = [_r("dense_only")]
    sparse: list[RankedResult] = []

    fused = reciprocal_rank_fusion([dense, sparse])
    assert [f.point_id for f in fused] == ["dense_only"]


def test_empty_lists_produce_empty_result() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


def test_payload_preserved_from_first_occurrence() -> None:
    fused = reciprocal_rank_fusion([[RankedResult("a", {"company": "NVDA"})]])
    assert fused[0].payload == {"company": "NVDA"}
