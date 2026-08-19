// Mirrors apps/api/routers/jobs.py's Pydantic response models exactly —
// keep the two in sync by hand until there's a shared schema generator.

export type JobStatus = 'pending' | 'running' | 'awaiting_review' | 'succeeded' | 'failed'

export type CitationStatus = 'accept' | 'rewrite' | 'remove' | 'flag'

export interface DocumentRef {
  document_id: string
  company: string
  ticker: string
  document_type: string
}

export interface CitationResponse {
  citation_id: string
  status: CitationStatus
  rewritten_claim_text: string | null
  justification: string
  supporting_passage: string
  evidence_summary: string
  document: DocumentRef
}

export interface ClaimResponse {
  claim_id: string
  text: string
  citations: CitationResponse[]
}

export interface JobResponse {
  job_id: string
  status: JobStatus
  query: string
  insufficient_evidence: boolean
  progress_detail: string | null
  final_report: string | null
  error_message: string | null
  claims: ClaimResponse[]
  // Not present in today's API — optional until docs/16 Phase 4 ships it.
  // See LegalReport below.
  legal_report?: LegalReport | null
}

// GET /jobs — a history-list row. Deliberately narrower than JobResponse:
// no claims/citations, so a sidebar rendering many of these stays cheap.
export interface JobSummary {
  job_id: string
  query: string
  status: JobStatus
  insufficient_evidence: boolean
  created_at: string
}

// The target structured shape docs/16 Phase 4 (backend pivot plan) will add
// to JobResponse — not present in today's API yet. `ReportView` renders
// this when present and falls back to `final_report` prose otherwise, so
// the frontend needs no rework once the backend ships it.
export interface LegalIssue {
  issue: string
  relevant_provision: string
  supporting_authority: {
    citation: string
    court: string | null
    year: number | null
  }
  why_relevant: string
}

export interface LegalReport {
  legal_issues: LegalIssue[]
  counterarguments: string[]
  sources: DocumentRef[]
}
