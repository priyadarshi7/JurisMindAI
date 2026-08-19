"""Linear research pipeline (docs/00 MVP flow, docs/06 nodes without the
cyclic loop): Planner -> Query Decomposer -> {retrieve -> extract -> verify
-> detect contradictions} per sub-question -> Synthesize -> Critic ->
Citation Validator -> stored report.

Deliberately not the LangGraph `StateGraph` yet — no "Research Again" cycle,
no conditional sufficiency gate. That loop is what V2 adds (docs/06's whole
justification for LangGraph over a plain chain). This pipeline runs each
node exactly once, which is the honest MVP scope docs/00 describes, and it
calls the same node functions (`src/graph/nodes.py`) the eventual graph
will call — introducing the loop later wraps this ordering, it does not
replace it.

❗ The final report is assembled from the **validated claim chain**, not
from the Synthesizer's free-text prose. docs/08: "do not generate citations
after writing the report — build the evidence chain first." Trusting
`SynthesisResult.report_text` as final output would make citation
validation a check with no enforcement power — a REMOVE verdict couldn't
un-write a sentence already in prose. Building the final text from
`SynthesisResult.claims` after each claim has been individually validated
means a rejected claim is a claim that was never included, not one that
was written and then ignored.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from qdrant_client.models import Filter
from sqlalchemy.ext.asyncio import AsyncSession

from src.graph.nodes import (
    run_citation_validator,
    run_contradiction_detector,
    run_critic,
    run_evidence_extractor,
    run_planner,
    run_query_decomposer,
    run_synthesizer,
    run_verifier,
)
from src.graph.prompt_runner import PromptRunner
from src.graph.schemas import ContradictionPair, ExtractedEvidence
from src.models.orm import (
    Citation,
    CitationStatus,
    Claim,
    ClaimEvidence,
    EvidenceItem,
    JobStatus,
    Report,
    ResearchJob,
)
from src.models.run_manifest import PerCallLLMRecord
from src.rag.hybrid.retriever import HybridRetriever, HybridSearchResult
from src.rag.vector.qdrant_store import build_metadata_filter

NO_QUANTITATIVE_RESULTS = (
    "No quantitative results available — the deterministic quant engine is V3 work."
)
DECLARED_INSUFFICIENT = (
    "Evidence insufficient to answer this question within the current corpus and "
    "research budget. No verified evidence was found for any sub-question."
)

# Called with a short human-readable "what's happening now" string as the
# pipeline moves between stages. Optional and side-effect-only by design —
# run_research() never reads its return value, so a caller (src/graph/tasks.py)
# is free to implement it as "commit to ResearchJob.progress_detail on a
# separate session" without this module knowing anything about persistence.
ProgressCallback = Callable[[str], Awaitable[None]]


async def _report_progress(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


@dataclass(frozen=True)
class VerifiedEvidence:
    """One evidence item that survived verification, with its source
    retrieval hit still attached — the hit's payload is where `chunk_id`
    (for PostgreSQL persistence) and the ticker/company/section context
    ultimately come from.
    """

    evidence: ExtractedEvidence
    source: HybridSearchResult


@dataclass
class ResearchOutcome:
    job_id: uuid.UUID
    final_report: str
    insufficient_evidence: bool
    llm_call_records: list[PerCallLLMRecord] = field(default_factory=list)


async def run_research(
    query: str,
    *,
    session: AsyncSession,
    retriever: HybridRetriever,
    prompt_runner: PromptRunner,
    model: str,
    research_id: str,
    trace_id: str,
    tenant_id: uuid.UUID | None = None,
    top_n_per_subquestion: int = 3,
    # Lowered 7 -> 3 (2026-08-17), found live: a fresh corpus re-ingestion
    # produced a job with correct retrieval (the reranker put both real
    # answer passages at rank 0-1 of 7, confirmed via direct diagnostic) that
    # STILL returned insufficient_evidence. Isolated the cause to
    # evidence_extractor, not retrieval: given all 7 reranked passages
    # (~20K chars of real filing text, much of it unrelated boilerplate
    # sharing a chunk with the answer), qwen3:4b produced 30 fabricated
    # "evidence items" with invented passage_index values, none actually
    # about the sub-question. Re-run with only the 2 known-good passages
    # handed directly to the same extractor call: correct extraction and
    # SUPPORTS verdicts both times. The 4B model's instruction-following
    # degrades sharply past a few large passages in one call — this is a
    # real extraction-capacity ceiling, not a retrieval problem. History:
    # 5 (D-20 baseline) -> 15 -> 30 (chasing a retrieval-recall problem,
    # see git blame) -> 7 (once the reranker existed) -> 3 (this fix, once
    # the actual bottleneck turned out to be extraction, not recall).
    on_progress: ProgressCallback | None = None,
) -> ResearchOutcome:
    records: list[PerCallLLMRecord] = []

    # Get-or-create: the API (`apps/api/routers/jobs.py`) pre-creates the
    # `ResearchJob` row as PENDING before enqueueing the Celery task, so the
    # caller gets a job ID back immediately without waiting on this function.
    # Callers that pass a fresh `research_id` (tests, direct invocation)
    # still get a row created here exactly as before.
    job = await session.get(ResearchJob, uuid.UUID(research_id))
    if job is None:
        job = ResearchJob(
            id=uuid.UUID(research_id),
            trace_id=trace_id,
            tenant_id=tenant_id,
            query=query,
            status=JobStatus.RUNNING,
            # Explicit rather than relying on the ORM column default, which
            # only materializes on a real flush — code that reads this field
            # before the row round-trips a live database (as this function
            # itself does, below) should never see an ambiguous None.
            insufficient_evidence=False,
        )
        session.add(job)
    else:
        job.status = JobStatus.RUNNING
    await session.flush()

    await _report_progress(on_progress, "Planning research approach")
    plan, record = run_planner(
        prompt_runner, query=query, model=model, research_id=research_id, trace_id=trace_id
    )
    records.append(record)

    await _report_progress(on_progress, "Decomposing into sub-questions")
    decomposition, record = run_query_decomposer(
        prompt_runner,
        query=query,
        research_plan=plan.plan_notes,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    verified_evidence: list[VerifiedEvidence] = []
    gaps: list[str] = []
    contradictions: list[ContradictionPair] = []

    total_sub_questions = len(decomposition.sub_questions)
    for i, sub_question in enumerate(decomposition.sub_questions, start=1):
        await _report_progress(
            on_progress,
            f"Researching sub-question {i}/{total_sub_questions}: {sub_question.question}",
        )
        sub_records, sub_verified, sub_gaps, sub_contradictions = await _research_sub_question(
            sub_question.question,
            # ❗ `company` deliberately excluded — found live, not by
            # inspection: the Query Decomposer returns free-text company
            # names ("NVIDIA") that don't exact-match the canonical legal
            # name Qdrant stores from SEC filer data ("NVIDIA CORP"),
            # silently zeroing every hit even though the passages were
            # right there. `ticker` is the reliable identifier for exactly
            # this reason — it's a controlled vocabulary the LLM reliably
            # reproduces verbatim, unlike a company's legal name.
            query_filter=build_metadata_filter(
                ticker=sub_question.ticker,
                document_type=sub_question.document_type,
                tenant_id=str(tenant_id) if tenant_id else None,
            ),
            retriever=retriever,
            prompt_runner=prompt_runner,
            model=model,
            research_id=research_id,
            trace_id=trace_id,
            top_n=top_n_per_subquestion,
            evidence_index_offset=len(verified_evidence),
            on_progress=on_progress,
        )
        records.extend(sub_records)
        verified_evidence.extend(sub_verified)
        gaps.extend(sub_gaps)
        contradictions.extend(sub_contradictions)

    if not verified_evidence:
        job.insufficient_evidence = True
        job.status = JobStatus.SUCCEEDED
        report = Report(
            job_id=job.id,
            tenant_id=tenant_id,
            final_report=DECLARED_INSUFFICIENT,
            run_manifest={"model": model, "insufficient_evidence": True},
        )
        session.add(report)
        await session.flush()
        return ResearchOutcome(
            job_id=job.id,
            final_report=DECLARED_INSUFFICIENT,
            insufficient_evidence=True,
            llm_call_records=records,
        )

    descriptions = [_describe(ve.evidence) for ve in verified_evidence]
    contradictions_text = (
        "\n".join(
            f"{c.evidence_index_a} vs {c.evidence_index_b}: {c.description}" for c in contradictions
        )
        or "None"
    )
    gaps_text = "\n".join(gaps) or "None"

    await _report_progress(
        on_progress, f"Synthesizing report from {len(verified_evidence)} evidence items"
    )
    synthesis, record = run_synthesizer(
        prompt_runner,
        query=query,
        evidence_descriptions=descriptions,
        quantitative_results=NO_QUANTITATIVE_RESULTS,
        contradictions=contradictions_text,
        gaps=gaps_text,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    await _report_progress(on_progress, "Reviewing draft report")
    critic_result, record = run_critic(
        prompt_runner,
        draft=synthesis.report_text,
        evidence_descriptions=descriptions,
        quantitative_results=NO_QUANTITATIVE_RESULTS,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    await _report_progress(on_progress, f"Validating citations for {len(synthesis.claims)} claims")
    report_lines: list[str] = []
    persisted_evidence_by_index: dict[int, uuid.UUID] = {}

    for claim_draft in synthesis.claims:
        cited = [
            verified_evidence[i]
            for i in claim_draft.evidence_indices
            if 0 <= i < len(verified_evidence)
        ]
        if not cited:
            continue  # ❗ a claim with no resolvable evidence index is dropped, not trusted

        claim_row = Claim(job_id=job.id, text=claim_draft.claim_text)
        session.add(claim_row)
        await session.flush()

        accepted_text: str | None = None
        flagged = False
        for index, ve in zip(claim_draft.evidence_indices, cited, strict=False):
            if index not in persisted_evidence_by_index:
                chunk_id = ve.source.payload.get("chunk_id")
                evidence_row = EvidenceItem(
                    job_id=job.id,
                    chunk_id=uuid.UUID(str(chunk_id)),
                    supporting_passage=ve.evidence.supporting_text,
                    summary=ve.evidence.summary,
                )
                session.add(evidence_row)
                await session.flush()
                persisted_evidence_by_index[index] = evidence_row.id
            evidence_id = persisted_evidence_by_index[index]
            session.add(ClaimEvidence(claim_id=claim_row.id, evidence_id=evidence_id))

            citation_decision, cite_record = run_citation_validator(
                prompt_runner,
                claim=claim_draft.claim_text,
                cited_passage=ve.evidence.supporting_text,
                model=model,
                research_id=research_id,
                trace_id=trace_id,
            )
            records.append(cite_record)

            citation_row = Citation(
                claim_id=claim_row.id,
                evidence_id=evidence_id,
                document_id=uuid.UUID(str(ve.source.payload.get("document_id"))),
                status=CitationStatus(citation_decision.verdict.lower()),
                rewritten_claim_text=citation_decision.rewritten_claim,
                justification=citation_decision.justification,
            )
            session.add(citation_row)

            if citation_decision.verdict == "ACCEPT" and accepted_text is None:
                accepted_text = claim_draft.claim_text
            elif citation_decision.verdict == "REWRITE" and citation_decision.rewritten_claim:
                accepted_text = citation_decision.rewritten_claim
            elif citation_decision.verdict == "FLAG":
                # ❗ FLAG is a legitimate outcome that still ships (docs/08:
                # "Flag ... this is a legitimate outcome, not a fallback"),
                # not merely a modifier applied only when some other
                # evidence for the same claim also got ACCEPT/REWRITE. A
                # claim citing exactly one FLAGged passage must still
                # appear, marked uncertain, or "flag" would be
                # indistinguishable from "remove."
                flagged = True
                if accepted_text is None:
                    accepted_text = claim_draft.claim_text

        if accepted_text:
            report_lines.append(f"{accepted_text} [uncertain]" if flagged else accepted_text)
        # REMOVE (or no ACCEPT/REWRITE/FLAG reached) -> claim silently
        # excluded from the final report, exactly as docs/08 requires.

    if not report_lines:
        job.insufficient_evidence = True
        final_report = DECLARED_INSUFFICIENT
    else:
        sections = [" ".join(report_lines)]
        if gaps:
            sections.append("Evidence gaps: " + "; ".join(gaps))
        if contradictions:
            sections.append(
                "Contradictions found: " + "; ".join(c.description for c in contradictions)
            )
        final_report = "\n\n".join(sections)

    job.status = JobStatus.SUCCEEDED
    report = Report(
        job_id=job.id,
        tenant_id=tenant_id,
        draft=synthesis.report_text,
        final_report=final_report,
        run_manifest={
            "model": model,
            "critic_ok": critic_result.ok,
            "critic_problems": critic_result.problems,
        },
    )
    session.add(report)
    await session.flush()

    return ResearchOutcome(
        job_id=job.id,
        final_report=final_report,
        insufficient_evidence=job.insufficient_evidence,
        llm_call_records=records,
    )


async def _research_sub_question(
    question: str,
    *,
    query_filter: Filter | None,
    retriever: HybridRetriever,
    prompt_runner: PromptRunner,
    model: str,
    research_id: str,
    trace_id: str,
    top_n: int,
    evidence_index_offset: int,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[PerCallLLMRecord], list[VerifiedEvidence], list[str], list[ContradictionPair]]:
    records: list[PerCallLLMRecord] = []

    hits = retriever.search(question, query_filter=query_filter, top_n=top_n)
    if not hits:
        return records, [], [f"No retrieved evidence for: {question}"], []

    await _report_progress(on_progress, f"Extracting evidence for: {question}")
    passages = [str(h.payload.get("text", "")) for h in hits]
    extraction, record = run_evidence_extractor(
        prompt_runner,
        sub_question=question,
        passages=passages,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    if not extraction.items:
        return records, [], [f"No evidence extracted for: {question}"], []

    await _report_progress(on_progress, f"Verifying evidence for: {question}")
    verification, record = run_verifier(
        prompt_runner,
        sub_question=question,
        evidence_items=extraction.items,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    verdict_by_index = {d.evidence_index: d.verdict for d in verification.decisions}
    kept: list[VerifiedEvidence] = []
    for i, item in enumerate(extraction.items):
        verdict = verdict_by_index.get(i)
        if verdict in ("SUPPORTS", "PARTIAL") and 0 <= item.passage_index < len(hits):
            kept.append(VerifiedEvidence(evidence=item, source=hits[item.passage_index]))

    if not kept:
        return records, [], [f"No verified evidence for: {question}"], []

    await _report_progress(on_progress, f"Checking for contradictions in: {question}")
    descriptions = [_describe(ve.evidence) for ve in kept]
    contradiction_result, record = run_contradiction_detector(
        prompt_runner,
        sub_question=question,
        evidence_descriptions=descriptions,
        model=model,
        research_id=research_id,
        trace_id=trace_id,
    )
    records.append(record)

    offset_contradictions = [
        ContradictionPair(
            evidence_index_a=pair.evidence_index_a + evidence_index_offset,
            evidence_index_b=pair.evidence_index_b + evidence_index_offset,
            description=pair.description,
        )
        for pair in contradiction_result.contradictions
    ]

    return records, kept, list(contradiction_result.gaps), offset_contradictions


def _describe(evidence: ExtractedEvidence) -> str:
    return f'{evidence.summary} — "{evidence.supporting_text}"'
