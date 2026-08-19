import type { CitationStatus, JobStatus } from '../types'

// Centralizes every status -> color/label mapping so the citation ledger,
// history tables, and workspace header all agree on what "accepted" or
// "running" looks like, referencing the design tokens in index.css
// (surface-*/ink-*/hairline/accent) rather than raw Tailwind slate/sky —
// see that file's header comment for the palette rationale.

// Dense contexts (citation ledger rows, history table rows) get a small
// status dot, not a colored pill — a page of pill badges reads as "chat
// app," a page of quiet dots with aligned labels reads as a data table.
export const CITATION_STATUS_DOT: Record<CitationStatus, string> = {
  accept: 'bg-emerald-500',
  rewrite: 'bg-sky-500',
  flag: 'bg-amber-500',
  remove: 'bg-ink-2',
}

export const CITATION_STATUS_TEXT: Record<CitationStatus, string> = {
  accept: 'text-emerald-400',
  rewrite: 'text-sky-400',
  flag: 'text-amber-400',
  remove: 'text-ink-2',
}

export const CITATION_STATUS_LABELS: Record<CitationStatus, string> = {
  accept: 'Accepted',
  rewrite: 'Rewritten',
  flag: 'Uncertain',
  remove: 'Excluded',
}

export const JOB_STATUS_DOT: Record<JobStatus, string> = {
  pending: 'bg-ink-2',
  running: 'bg-sky-500',
  awaiting_review: 'bg-amber-500',
  succeeded: 'bg-emerald-500',
  failed: 'bg-rose-500',
}

export const JOB_STATUS_TEXT: Record<JobStatus, string> = {
  pending: 'text-ink-2',
  running: 'text-sky-400',
  awaiting_review: 'text-amber-400',
  succeeded: 'text-emerald-400',
  failed: 'text-rose-400',
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  pending: 'Queued',
  running: 'Researching',
  awaiting_review: 'Awaiting review',
  succeeded: 'Completed',
  failed: 'Failed',
}

export const PRODUCT_NAME = 'JurisMindAI'
export const PRODUCT_TAGLINE = 'Legal Intelligence Platform'

export const DISCLAIMER =
  'This is legal research assistance, not legal advice. Consult a qualified advocate before acting on it.'

export const EXAMPLE_QUERIES = [
  'My client purchased a property in 2021. The seller allegedly concealed an existing dispute over the property. The client discovered the dispute in 2025 and wants to know what legal remedies may be available.',
  'A consumer bought a defective appliance and the seller refuses a refund six months later — what remedies exist under Indian consumer protection law?',
  'What is the limitation period for filing a suit for breach of a written contract, and when does it begin to run?',
]

// Quick-action entry points on the dashboard (docs: user-supplied dashboard
// spec) — each is a real, functional route into the composer with a
// framing hint, not a separate search backend that doesn't exist.
export type ComposerMode = 'general' | 'case-law' | 'constitution' | 'statutes'

export const COMPOSER_MODE_COPY: Record<ComposerMode, { label: string; placeholder: string }> = {
  general: {
    label: 'Legal Research',
    placeholder:
      'My client purchased a property in 2021. The seller allegedly concealed an existing dispute over the property...',
  },
  'case-law': {
    label: 'Case Law Research',
    placeholder: 'Search for precedent — e.g. landmark judgments on preventive detention...',
  },
  constitution: {
    label: 'Constitutional Research',
    placeholder: 'Ask about a fundamental right or constitutional provision — e.g. Article 21...',
  },
  statutes: {
    label: 'Statutory Research',
    placeholder: 'Ask about a specific Act or section — e.g. limitation period under Section 18...',
  },
}
