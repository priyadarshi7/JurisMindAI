"""Per-node LLM functions (docs/06). Each wraps one `PromptRunner.run()`
call with the variable-formatting a node's prompt needs.

These are plain functions over explicit arguments, not methods on a
`ResearchState` object — the real sixteen-field `ResearchState` and the
`StateGraph` that threads it between nodes are V2 work. Built this way on
purpose: a LangGraph node is a function `(state) -> partial_state`, so
wrapping these functions to read/write `ResearchState` fields later is a
thin adapter, not a rewrite.
"""

from __future__ import annotations

from src.graph.prompt_runner import PromptRunner, format_numbered_list
from src.graph.schemas import (
    CitationDecision,
    ContradictionResult,
    CriticResult,
    EvidenceExtractionResult,
    ExtractedEvidence,
    PlannerOutput,
    QueryDecomposition,
    SynthesisResult,
    VerificationResult,
)
from src.models.run_manifest import PerCallLLMRecord


def run_planner(
    runner: PromptRunner, *, query: str, model: str, research_id: str, trace_id: str
) -> tuple[PlannerOutput, PerCallLLMRecord]:
    return runner.run(
        node="planner",
        version=1,
        model=model,
        variables={"query": query},
        schema=PlannerOutput,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_query_decomposer(
    runner: PromptRunner,
    *,
    query: str,
    research_plan: str,
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[QueryDecomposition, PerCallLLMRecord]:
    return runner.run(
        node="query_rewriter",
        version=1,
        model=model,
        variables={"query": query, "research_plan": research_plan},
        schema=QueryDecomposition,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_evidence_extractor(
    runner: PromptRunner,
    *,
    sub_question: str,
    passages: list[str],
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[EvidenceExtractionResult, PerCallLLMRecord]:
    return runner.run(
        node="evidence_extractor",
        version=4,
        model=model,
        variables={
            "sub_question": sub_question,
            "numbered_passages": format_numbered_list(passages),
        },
        schema=EvidenceExtractionResult,
        research_id=research_id,
        trace_id=trace_id,
    )


def _describe_evidence(evidence: ExtractedEvidence) -> str:
    return f'{evidence.summary} — "{evidence.supporting_text}"'


def run_verifier(
    runner: PromptRunner,
    *,
    sub_question: str,
    evidence_items: list[ExtractedEvidence],
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[VerificationResult, PerCallLLMRecord]:
    numbered = format_numbered_list([_describe_evidence(e) for e in evidence_items])
    return runner.run(
        node="verifier",
        version=3,
        model=model,
        variables={"sub_question": sub_question, "numbered_evidence_items": numbered},
        schema=VerificationResult,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_contradiction_detector(
    runner: PromptRunner,
    *,
    sub_question: str,
    evidence_descriptions: list[str],
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[ContradictionResult, PerCallLLMRecord]:
    return runner.run(
        node="contradiction",
        version=2,
        model=model,
        variables={
            "sub_question": sub_question,
            "numbered_evidence_items": format_numbered_list(evidence_descriptions),
        },
        schema=ContradictionResult,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_synthesizer(
    runner: PromptRunner,
    *,
    query: str,
    evidence_descriptions: list[str],
    quantitative_results: str,
    contradictions: str,
    gaps: str,
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[SynthesisResult, PerCallLLMRecord]:
    return runner.run(
        node="synthesizer",
        version=2,
        model=model,
        variables={
            "query": query,
            "numbered_evidence_items": format_numbered_list(evidence_descriptions),
            "quantitative_results": quantitative_results,
            "contradictions": contradictions,
            "gaps": gaps,
        },
        schema=SynthesisResult,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_critic(
    runner: PromptRunner,
    *,
    draft: str,
    evidence_descriptions: list[str],
    quantitative_results: str,
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[CriticResult, PerCallLLMRecord]:
    return runner.run(
        node="critic",
        version=3,
        model=model,
        variables={
            "draft": draft,
            "evidence_items": format_numbered_list(evidence_descriptions),
            "quantitative_results": quantitative_results,
        },
        schema=CriticResult,
        research_id=research_id,
        trace_id=trace_id,
    )


def run_citation_validator(
    runner: PromptRunner,
    *,
    claim: str,
    cited_passage: str,
    model: str,
    research_id: str,
    trace_id: str,
) -> tuple[CitationDecision, PerCallLLMRecord]:
    return runner.run(
        node="citation_validator",
        version=1,
        model=model,
        variables={"claim": claim, "cited_passage": cited_passage},
        schema=CitationDecision,
        research_id=research_id,
        trace_id=trace_id,
    )
