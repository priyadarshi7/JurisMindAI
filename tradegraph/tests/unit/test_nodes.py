"""Unit tests for src.graph.nodes — verifies each node function calls
PromptRunner.run with the right node name, prompt version, and rendered
variables. The runner itself is mocked; real rendering is covered by
test_prompt_runner.py and test_prompt_loader.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.graph import nodes
from src.graph.schemas import CitationDecision, ExtractedEvidence, PlannerOutput


def _mock_runner(return_value: object) -> MagicMock:
    runner = MagicMock()
    runner.run.return_value = (return_value, MagicMock())
    return runner


def test_run_planner_calls_correct_node_and_version() -> None:
    runner = _mock_runner(
        PlannerOutput(entities=[], evidence_needed="both", is_compound=False, plan_notes="x")
    )
    nodes.run_planner(runner, query="why?", model="m", research_id="r", trace_id="t")

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "planner"
    assert kwargs["version"] == 1
    assert kwargs["variables"] == {"query": "why?"}
    assert kwargs["schema"] is PlannerOutput


def test_run_query_decomposer_uses_query_rewriter_node() -> None:
    runner = _mock_runner(MagicMock(sub_questions=[]))
    nodes.run_query_decomposer(
        runner, query="q", research_plan="plan", model="m", research_id="r", trace_id="t"
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "query_rewriter"
    assert kwargs["variables"] == {"query": "q", "research_plan": "plan"}


def test_run_evidence_extractor_numbers_passages() -> None:
    runner = _mock_runner(MagicMock())
    nodes.run_evidence_extractor(
        runner,
        sub_question="q",
        passages=["passage A", "passage B"],
        model="m",
        research_id="r",
        trace_id="t",
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "evidence_extractor"
    assert kwargs["version"] == 4
    assert kwargs["variables"]["numbered_passages"] == "[0] passage A\n[1] passage B"


def test_run_verifier_describes_evidence_with_index() -> None:
    runner = _mock_runner(MagicMock())
    evidence = [
        ExtractedEvidence(passage_index=0, supporting_text="text one", summary="summary one"),
        ExtractedEvidence(passage_index=1, supporting_text="text two", summary="summary two"),
    ]
    nodes.run_verifier(
        runner, sub_question="q", evidence_items=evidence, model="m", research_id="r", trace_id="t"
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "verifier"
    assert kwargs["version"] == 3
    numbered = kwargs["variables"]["numbered_evidence_items"]
    assert "[0] summary one" in numbered
    assert "[1] summary two" in numbered
    assert '"text one"' in numbered


def test_run_contradiction_detector_uses_contradiction_node() -> None:
    runner = _mock_runner(MagicMock())
    nodes.run_contradiction_detector(
        runner,
        sub_question="q",
        evidence_descriptions=["desc A"],
        model="m",
        research_id="r",
        trace_id="t",
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "contradiction"
    assert kwargs["version"] == 2


def test_run_synthesizer_passes_all_variables() -> None:
    runner = _mock_runner(MagicMock())
    nodes.run_synthesizer(
        runner,
        query="q",
        evidence_descriptions=["e1"],
        quantitative_results="none",
        contradictions="none",
        gaps="none",
        model="m",
        research_id="r",
        trace_id="t",
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "synthesizer"
    assert kwargs["version"] == 2
    assert set(kwargs["variables"]) == {
        "query",
        "numbered_evidence_items",
        "quantitative_results",
        "contradictions",
        "gaps",
    }


def test_run_critic_uses_critic_node_v3() -> None:
    runner = _mock_runner(MagicMock())
    nodes.run_critic(
        runner,
        draft="draft text",
        evidence_descriptions=["e1"],
        quantitative_results="none",
        model="m",
        research_id="r",
        trace_id="t",
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "critic"
    assert kwargs["version"] == 3
    assert kwargs["variables"]["draft"] == "draft text"


def test_run_citation_validator_uses_v1() -> None:
    runner = _mock_runner(
        CitationDecision(verdict="ACCEPT", rewritten_claim=None, justification="matches")
    )
    nodes.run_citation_validator(
        runner,
        claim="claim text",
        cited_passage="passage text",
        model="m",
        research_id="r",
        trace_id="t",
    )

    kwargs = runner.run.call_args.kwargs
    assert kwargs["node"] == "citation_validator"
    assert kwargs["version"] == 1
    assert kwargs["variables"] == {"claim": "claim text", "cited_passage": "passage text"}
