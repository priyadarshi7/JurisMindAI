import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { CitationResponse, ClaimResponse } from '../types'
import { CITATION_STATUS_DOT, CITATION_STATUS_LABELS, CITATION_STATUS_TEXT } from '../lib/theme'

function CitationRow({ citation }: { citation: CitationResponse }) {
  const excluded = citation.status === 'remove'
  return (
    <li className="border-t border-hairline px-4 py-3 first:border-t-0">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${CITATION_STATUS_DOT[citation.status]}`} />
        <span
          className={`text-[11px] font-medium uppercase tracking-wide ${CITATION_STATUS_TEXT[citation.status]}`}
        >
          {CITATION_STATUS_LABELS[citation.status]}
        </span>
        <span className="ml-auto text-[11px] text-ink-2">
          {citation.document.company} · {citation.document.document_type}
        </span>
      </div>
      {citation.rewritten_claim_text && (
        <p className="mt-1.5 text-[13px] italic text-ink-1">"{citation.rewritten_claim_text}"</p>
      )}
      <p className={`mt-1.5 text-[13px] leading-relaxed ${excluded ? 'text-ink-2 line-through' : 'text-ink-0'}`}>
        {citation.supporting_passage}
      </p>
      <p className="mt-1.5 text-[12px] text-ink-2">{citation.justification}</p>
    </li>
  )
}

function ClaimRow({ claim }: { claim: ClaimResponse }) {
  const allExcluded = claim.citations.every((c) => c.status === 'remove')
  const [open, setOpen] = useState(!allExcluded)

  return (
    <div className={`border border-hairline ${allExcluded ? 'opacity-60' : ''}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 bg-surface-1 px-4 py-2.5 text-left text-[13px] font-medium text-ink-0 transition hover:bg-surface-2"
      >
        <span className="flex-1">{claim.text}</span>
        <span className="shrink-0 text-[11px] font-normal text-ink-2">
          {claim.citations.length} citation{claim.citations.length === 1 ? '' : 's'}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-ink-2 transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <ul>
          {claim.citations.map((citation) => (
            <CitationRow key={citation.citation_id} citation={citation} />
          ))}
        </ul>
      )}
    </div>
  )
}

interface EvidencePanelProps {
  claims: ClaimResponse[]
}

export function EvidencePanel({ claims }: EvidencePanelProps) {
  if (claims.length === 0) return null

  return (
    <div>
      <h2 className="mb-2.5 text-[11px] font-medium uppercase tracking-wide text-ink-2">
        Evidence &amp; citations
      </h2>
      <div className="space-y-2">
        {claims.map((claim) => (
          <ClaimRow key={claim.claim_id} claim={claim} />
        ))}
      </div>
    </div>
  )
}
