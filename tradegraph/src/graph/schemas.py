"""Typed I/O contracts for every LLM-calling node (docs/06 — "structured
outputs between nodes... never prose handoffs").

Two design choices run through every schema here:

1. **Index-based referencing, never reproduced IDs.** A node that needs to
   point at a specific retrieved passage or evidence item refers to it by
   its position in a numbered list this code supplies — it never asks the
   model to reproduce a document ID, UUID, or exact citation string.
   Models reliably lose or subtly alter long identifiers; an integer index
   into a list the caller already controls cannot drift. Provenance is
   still exact because the caller resolves the index, not the model.

2. **No prose fields where a typed one will do.** Verdicts are `Literal`
   enums, not free text a caller would need to re-parse. Where free text is
   unavoidable (a summary, a report body) it sits alongside — never instead
   of — the structured fields a downstream step actually consumes.

These are node-local contracts, not the sixteen-field `ResearchState`
(docs/06) itself — that lands with the real LangGraph `StateGraph` in V2.
This linear pipeline (`src/graph/pipeline.py`) is deliberately built from
the same node functions the graph will later call, so introducing
`StateGraph` later is a wiring change, not a rewrite of this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceVerdict = Literal["SUPPORTS", "PARTIAL", "DOES_NOT_SUPPORT"]
CitationVerdict = Literal["ACCEPT", "REWRITE", "REMOVE", "FLAG"]
ConfidenceLevel = Literal["low", "medium", "high"]


class PlannerOutput(BaseModel):
    """Planner node (docs/06) — turns a question into a bounded plan."""

    entities: list[str] = Field(description="Companies, tickers, periods named or implied")
    evidence_needed: Literal["qualitative", "quantitative", "both"]
    is_compound: bool = Field(description="Whether the question needs decomposition")
    plan_notes: str = Field(description="What evidence would answer the question")


class SubQuestion(BaseModel):
    question: str
    company: str | None = None
    ticker: str | None = None
    document_type: str | None = None


class QueryDecomposition(BaseModel):
    """Query Decomposer node — 3-5 sub-questions per §18."""

    sub_questions: list[SubQuestion] = Field(min_length=1, max_length=5)


class ExtractedEvidence(BaseModel):
    """One evidence item, referencing its source passage by index."""

    passage_index: int = Field(description="Index into the retrieved-passages list supplied")
    supporting_text: str = Field(description="Verbatim excerpt, not paraphrased")
    summary: str = Field(description="One sentence: what this passage establishes")


class EvidenceExtractionResult(BaseModel):
    items: list[ExtractedEvidence] = Field(default_factory=list)


class VerificationDecision(BaseModel):
    """One verdict, referencing its evidence item by index into the list
    the Evidence Extractor produced (docs/06 Verification node).
    """

    evidence_index: int
    verdict: EvidenceVerdict
    reason: str


class VerificationResult(BaseModel):
    decisions: list[VerificationDecision] = Field(default_factory=list)


class ContradictionPair(BaseModel):
    """References two evidence items by index — both indices are into the
    *verified* evidence list (SUPPORTS/PARTIAL only), the same numbering
    the Synthesizer step below also uses.
    """

    evidence_index_a: int
    evidence_index_b: int
    description: str


class ContradictionResult(BaseModel):
    contradictions: list[ContradictionPair] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel


class ClaimDraft(BaseModel):
    """One claim the Synthesizer wrote, tied to the verified-evidence
    indices it rests on. A claim with an empty `evidence_indices` list is a
    contract violation the caller rejects before it ever reaches the
    Critic — docs/06: "do not write a claim with no corresponding evidence
    item."
    """

    claim_text: str
    evidence_indices: list[int] = Field(min_length=1)


class SynthesisResult(BaseModel):
    report_text: str
    claims: list[ClaimDraft] = Field(default_factory=list)


class CriticResult(BaseModel):
    """Critic node — adversarial review; never rewrites the draft itself
    (docs/06: that stays a human-legible list of problems, not a silent
    edit).
    """

    problems: list[str] = Field(default_factory=list)
    ok: bool = Field(description="True only if problems is empty")


class CitationDecision(BaseModel):
    """Citation Validator node — the entailment gate (docs/08, D-23). Runs
    once per claim, against one evidence passage at a time (the caller
    resolves which evidence item(s) back a claim and calls this per pair).
    """

    verdict: CitationVerdict
    rewritten_claim: str | None = Field(
        default=None, description="Required when verdict is REWRITE, else null"
    )
    justification: str
