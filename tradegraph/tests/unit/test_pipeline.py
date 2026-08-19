"""Unit tests for src.graph.pipeline — every collaborator mocked
(retriever, PromptRunner, PostgreSQL session). Real end-to-end behavior
against live services is covered in
tests/integration/test_research_pipeline_live.py.

The central thing under test: the final report is built from validated
claims, not trusted from the Synthesizer's prose — a REMOVE verdict must
actually remove text from `final_report`, not just get logged.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

from src.graph.pipeline import _research_sub_question, run_research
from src.graph.schemas import (
    CitationDecision,
    ClaimDraft,
    ContradictionPair,
    ContradictionResult,
    CriticResult,
    EvidenceExtractionResult,
    ExtractedEvidence,
    PlannerOutput,
    QueryDecomposition,
    SubQuestion,
    SynthesisResult,
    VerificationDecision,
    VerificationResult,
)
from src.models.orm import JobStatus
from src.rag.hybrid.retriever import HybridSearchResult

RESEARCH_ID = str(uuid.uuid4())
TRACE_ID = "trace-1"


def _uuid_for(name: str) -> str:
    """Real chunk/document ids are UUIDs (`Chunk.id` / `Document.id` from
    PostgreSQL) — deterministic per `name` so call sites stay readable.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def _hit(chunk_name: str, document_name: str, text: str) -> HybridSearchResult:
    chunk_id = _uuid_for(chunk_name)
    document_id = _uuid_for(document_name)
    return HybridSearchResult(
        point_id=chunk_id,
        rrf_score=1.0,
        payload={"chunk_id": chunk_id, "document_id": document_id, "text": text},
    )


class FakePromptRunner:
    """Scripted responses per node, consumed in call order — no HTTP, no
    real LLM. `nodes.py`'s wiring is trusted (covered by test_nodes.py);
    this fake only needs to satisfy `PromptRunner.run`'s signature.
    """

    def __init__(self, responses: dict[str, list[object]]) -> None:
        self._responses: dict[str, list[object]] = defaultdict(list, responses)
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        *,
        node: str,
        version: int,
        model: str,
        variables: dict[str, str],
        schema: object,
        research_id: str,
        trace_id: str,
    ) -> tuple[object, MagicMock]:
        self.calls.append({"node": node, "variables": variables})
        queue = self._responses[node]
        if not queue:
            raise AssertionError(f"no scripted response left for node={node!r}")
        return queue.pop(0), MagicMock()


def _mock_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    # No pre-existing job row by default — matches every test here calling
    # run_research() directly with a fresh research_id, as opposed to the API
    # flow that pre-creates a PENDING ResearchJob before enqueueing.
    session.get = AsyncMock(return_value=None)
    return session


async def test_insufficient_evidence_when_retrieval_finds_nothing() -> None:
    retriever = MagicMock()
    retriever.search.return_value = []

    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=[], evidence_needed="both", is_compound=False, plan_notes="x"
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
        }
    )
    session = _mock_session()

    outcome = await run_research(
        "why?",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    assert outcome.insufficient_evidence is True
    assert "insufficient" in outcome.final_report.lower()


async def test_accepted_claim_appears_in_final_report() -> None:
    retriever = MagicMock()
    hit = _hit("chunk-1", "doc-1", "Gross margin declined due to higher costs.")
    retriever.search.return_value = [hit]

    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=["NVDA"],
                    evidence_needed="qualitative",
                    is_compound=False,
                    plan_notes="x",
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
            "evidence_extractor": [
                EvidenceExtractionResult(
                    items=[
                        ExtractedEvidence(
                            passage_index=0,
                            supporting_text="Gross margin declined due to higher costs.",
                            summary="Margin decline explained",
                        )
                    ]
                )
            ],
            "verifier": [
                VerificationResult(
                    decisions=[
                        VerificationDecision(evidence_index=0, verdict="SUPPORTS", reason="matches")
                    ]
                )
            ],
            "contradiction": [ContradictionResult(contradictions=[], gaps=[], confidence="high")],
            "synthesizer": [
                SynthesisResult(
                    report_text="ignored — final report is built from claims, not this",
                    claims=[
                        ClaimDraft(
                            claim_text="Margin declined due to higher costs.", evidence_indices=[0]
                        )
                    ],
                )
            ],
            "critic": [CriticResult(problems=[], ok=True)],
            "citation_validator": [
                CitationDecision(
                    verdict="ACCEPT", rewritten_claim=None, justification="matches exactly"
                )
            ],
        }
    )
    session = _mock_session()

    outcome = await run_research(
        "why did margin decline?",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    assert outcome.insufficient_evidence is False
    assert "Margin declined due to higher costs." in outcome.final_report
    assert "ignored" not in outcome.final_report


async def test_remove_verdict_excludes_claim_from_final_report() -> None:

    retriever = MagicMock()
    retriever.search.return_value = [_hit("chunk-1", "doc-1", "Some passage text.")]

    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=[], evidence_needed="both", is_compound=False, plan_notes="x"
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
            "evidence_extractor": [
                EvidenceExtractionResult(
                    items=[
                        ExtractedEvidence(
                            passage_index=0, supporting_text="Some passage text.", summary="s"
                        )
                    ]
                )
            ],
            "verifier": [
                VerificationResult(
                    decisions=[
                        VerificationDecision(evidence_index=0, verdict="SUPPORTS", reason="ok")
                    ]
                )
            ],
            "contradiction": [ContradictionResult(contradictions=[], gaps=[], confidence="high")],
            "synthesizer": [
                SynthesisResult(
                    report_text="draft",
                    claims=[
                        ClaimDraft(
                            claim_text="An unsupported overreach claim.", evidence_indices=[0]
                        )
                    ],
                )
            ],
            "critic": [CriticResult(problems=[], ok=True)],
            "citation_validator": [
                CitationDecision(
                    verdict="REMOVE",
                    rewritten_claim=None,
                    justification="passage does not support this",
                )
            ],
        }
    )
    session = _mock_session()

    outcome = await run_research(
        "q",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    # Proves this actually exercised REMOVE-driven exclusion rather than
    # bailing out early with no evidence at all: every stage through
    # citation validation ran (8 LLM calls: planner, query_rewriter,
    # evidence_extractor, verifier, contradiction, synthesizer, critic,
    # citation_validator), and only *then* did the claim get dropped.
    assert len(outcome.llm_call_records) == 8

    assert "unsupported overreach" not in outcome.final_report
    # No claim survived citation validation -> declared insufficient, not a
    # silently empty report.
    assert outcome.insufficient_evidence is True


async def test_flag_verdict_marks_claim_uncertain() -> None:

    retriever = MagicMock()
    retriever.search.return_value = [_hit("chunk-1", "doc-1", "Ambiguous passage.")]

    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=[], evidence_needed="both", is_compound=False, plan_notes="x"
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
            "evidence_extractor": [
                EvidenceExtractionResult(
                    items=[
                        ExtractedEvidence(
                            passage_index=0, supporting_text="Ambiguous passage.", summary="s"
                        )
                    ]
                )
            ],
            "verifier": [
                VerificationResult(
                    decisions=[
                        VerificationDecision(evidence_index=0, verdict="PARTIAL", reason="ok")
                    ]
                )
            ],
            "contradiction": [ContradictionResult(contradictions=[], gaps=[], confidence="medium")],
            "synthesizer": [
                SynthesisResult(
                    report_text="draft",
                    claims=[
                        ClaimDraft(
                            claim_text="A claim with ambiguous support.", evidence_indices=[0]
                        )
                    ],
                )
            ],
            "critic": [CriticResult(problems=[], ok=True)],
            "citation_validator": [
                CitationDecision(
                    verdict="FLAG", rewritten_claim=None, justification="support is ambiguous"
                )
            ],
        }
    )
    session = _mock_session()

    outcome = await run_research(
        "q",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    assert "[uncertain]" in outcome.final_report
    assert "A claim with ambiguous support." in outcome.final_report


async def test_on_progress_reports_each_stage() -> None:
    """The frontend's progress view (docs/16 Application) needs more than a
    single opaque "running" for the whole multi-minute run — `on_progress`
    is how src/graph/tasks.py surfaces per-stage detail onto
    ResearchJob.progress_detail. Every stage this pipeline actually runs
    through must fire it, in order.
    """
    retriever = MagicMock()
    retriever.search.return_value = [_hit("chunk-1", "doc-1", "Gross margin declined.")]

    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=["NVDA"],
                    evidence_needed="qualitative",
                    is_compound=False,
                    plan_notes="x",
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
            "evidence_extractor": [
                EvidenceExtractionResult(
                    items=[
                        ExtractedEvidence(
                            passage_index=0, supporting_text="Gross margin declined.", summary="s"
                        )
                    ]
                )
            ],
            "verifier": [
                VerificationResult(
                    decisions=[
                        VerificationDecision(evidence_index=0, verdict="SUPPORTS", reason="ok")
                    ]
                )
            ],
            "contradiction": [ContradictionResult(contradictions=[], gaps=[], confidence="high")],
            "synthesizer": [
                SynthesisResult(
                    report_text="draft",
                    claims=[ClaimDraft(claim_text="Margin declined.", evidence_indices=[0])],
                )
            ],
            "critic": [CriticResult(problems=[], ok=True)],
            "citation_validator": [
                CitationDecision(verdict="ACCEPT", rewritten_claim=None, justification="matches")
            ],
        }
    )
    session = _mock_session()
    seen: list[str] = []

    async def on_progress(message: str) -> None:
        seen.append(message)

    await run_research(
        "why did margin decline?",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
        on_progress=on_progress,
    )

    assert seen == [
        "Planning research approach",
        "Decomposing into sub-questions",
        "Researching sub-question 1/1: q1",
        "Extracting evidence for: q1",
        "Verifying evidence for: q1",
        "Checking for contradictions in: q1",
        "Synthesizing report from 1 evidence items",
        "Reviewing draft report",
        "Validating citations for 1 claims",
    ]


async def test_metadata_filter_excludes_company_field() -> None:
    """Regression: found live via a real job through the API/Celery worker
    (2026-08-15) — the Query Decomposer returns free-text company names
    ("NVIDIA") that don't exact-match Qdrant's canonical stored legal name
    ("NVIDIA CORP"), silently zeroing every retrieval hit even though the
    passages were right there. `company` must never reach the metadata
    filter; `ticker` (a controlled vocabulary the LLM reproduces reliably)
    is the identifier retrieval actually filters on.
    """
    retriever = MagicMock()
    retriever.search.return_value = []
    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=["NVDA"],
                    evidence_needed="quantitative",
                    is_compound=False,
                    plan_notes="x",
                )
            ],
            "query_rewriter": [
                QueryDecomposition(
                    sub_questions=[
                        SubQuestion(
                            question="q1", company="NVIDIA", ticker="NVDA", document_type="10-Q"
                        )
                    ]
                )
            ],
        }
    )
    session = _mock_session()

    await run_research(
        "why?",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    retriever.search.assert_called_once()
    _, kwargs = retriever.search.call_args
    query_filter = kwargs["query_filter"]
    assert query_filter is not None
    condition_keys = {c.key for c in query_filter.must}
    assert "company" not in condition_keys
    assert "ticker" in condition_keys


async def test_research_sub_question_no_hits_reports_gap() -> None:
    retriever = MagicMock()
    retriever.search.return_value = []
    runner = FakePromptRunner({})

    records, verified, gaps, contradictions = await _research_sub_question(
        "unanswerable question",
        query_filter=None,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
        top_n=5,
        evidence_index_offset=0,
    )

    assert records == []
    assert verified == []
    assert contradictions == []
    assert len(gaps) == 1 and "unanswerable question" in gaps[0]


async def test_research_sub_question_applies_evidence_index_offset() -> None:
    """The second sub-question's contradiction indices must be offset by
    how much verified evidence the first sub-question already contributed
    — otherwise two sub-questions' evidence lists collide in the final,
    combined evidence list the Synthesizer sees.
    """
    retriever = MagicMock()
    retriever.search.return_value = [_hit("c1", "d1", "passage")]

    runner = FakePromptRunner(
        {
            "evidence_extractor": [
                EvidenceExtractionResult(
                    items=[
                        ExtractedEvidence(passage_index=0, supporting_text="passage", summary="s")
                    ]
                )
            ],
            "verifier": [
                VerificationResult(
                    decisions=[
                        VerificationDecision(evidence_index=0, verdict="SUPPORTS", reason="ok")
                    ]
                )
            ],
            "contradiction": [
                ContradictionResult(
                    contradictions=[
                        ContradictionPair(evidence_index_a=0, evidence_index_b=0, description="x")
                    ],
                    gaps=[],
                    confidence="high",
                )
            ],
        }
    )

    _, _, _, contradictions = await _research_sub_question(
        "q2",
        query_filter=None,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
        top_n=5,
        evidence_index_offset=3,  # first sub-question already contributed 3 items
    )

    assert contradictions[0].evidence_index_a == 3
    assert contradictions[0].evidence_index_b == 3


async def test_job_status_set_to_running_then_succeeded() -> None:
    retriever = MagicMock()
    retriever.search.return_value = []
    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=[], evidence_needed="both", is_compound=False, plan_notes="x"
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
        }
    )
    session = _mock_session()
    added_jobs = []
    session.add.side_effect = lambda obj: added_jobs.append(obj)

    await run_research(
        "q",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    jobs = [o for o in added_jobs if type(o).__name__ == "ResearchJob"]
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.SUCCEEDED
    assert jobs[0].insufficient_evidence is True


async def test_reuses_preexisting_job_row_instead_of_creating_duplicate() -> None:
    """The API flow (apps/api/routers/jobs.py) pre-creates a PENDING
    ResearchJob and passes its id as research_id — run_research must reuse
    that row (flip it to RUNNING, then a terminal status) rather than trying
    to INSERT a second row sharing the same primary key.
    """
    retriever = MagicMock()
    retriever.search.return_value = []
    runner = FakePromptRunner(
        {
            "planner": [
                PlannerOutput(
                    entities=[], evidence_needed="both", is_compound=False, plan_notes="x"
                )
            ],
            "query_rewriter": [QueryDecomposition(sub_questions=[SubQuestion(question="q1")])],
        }
    )
    session = _mock_session()
    existing_job = MagicMock()
    existing_job.status = JobStatus.PENDING
    session.get = AsyncMock(return_value=existing_job)
    added: list[object] = []
    session.add.side_effect = lambda obj: added.append(obj)

    await run_research(
        "q",
        session=session,
        retriever=retriever,
        prompt_runner=runner,  # type: ignore[arg-type]
        model="qwen3:4b",
        research_id=RESEARCH_ID,
        trace_id=TRACE_ID,
    )

    assert not any(type(o).__name__ == "ResearchJob" for o in added)
    assert existing_job.status == JobStatus.SUCCEEDED
