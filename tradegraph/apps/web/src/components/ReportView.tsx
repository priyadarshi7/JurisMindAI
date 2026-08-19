import { ShieldAlert } from 'lucide-react'
import type { JobResponse, LegalIssue } from '../types'
import { DISCLAIMER } from '../lib/theme'

interface ReportViewProps {
  job: JobResponse
}

function LegalIssueCard({ issue, index }: { issue: LegalIssue; index: number }) {
  return (
    <article className="border border-hairline px-5 py-4">
      <div className="flex items-baseline gap-2">
        <span className="font-serif text-ink-2">{index + 1}.</span>
        <h3 className="font-serif text-[16px] text-ink-0">{issue.issue}</h3>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <span className="border border-hairline-strong px-2 py-0.5 text-[11px] text-ink-1">
          {issue.relevant_provision}
        </span>
        <span className="border border-accent-muted px-2 py-0.5 text-[11px] text-accent">
          {issue.supporting_authority.citation}
          {issue.supporting_authority.court ? ` · ${issue.supporting_authority.court}` : ''}
          {issue.supporting_authority.year ? `, ${issue.supporting_authority.year}` : ''}
        </span>
      </div>
      <p className="mt-2.5 text-[14px] leading-relaxed text-ink-1">{issue.why_relevant}</p>
    </article>
  )
}

export function ReportView({ job }: ReportViewProps) {
  if (job.status === 'failed') {
    return (
      <div className="border border-rose-900 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
        {job.error_message ?? 'The research job failed for an unknown reason.'}
      </div>
    )
  }

  if (job.insufficient_evidence) {
    return (
      <div className="flex items-start gap-3 border border-amber-900 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <p className="font-medium">Insufficient evidence in the current corpus</p>
          <p className="mt-1 text-amber-200/80">{job.final_report}</p>
        </div>
      </div>
    )
  }

  const legalReport = job.legal_report

  return (
    <div className="space-y-6">
      {legalReport ? (
        <>
          <div className="space-y-3">
            <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-2">
              Potential legal issues
            </h2>
            <div className="space-y-3">
              {legalReport.legal_issues.map((issue, index) => (
                <LegalIssueCard key={index} issue={issue} index={index} />
              ))}
            </div>
          </div>

          {legalReport.counterarguments.length > 0 && (
            <div className="border-l-2 border-accent-muted pl-4">
              <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-2">
                Potential counterarguments
              </h2>
              <ul className="mt-2 space-y-1.5">
                {legalReport.counterarguments.map((point, index) => (
                  <li key={index} className="text-[14px] leading-relaxed text-ink-1">
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {legalReport.sources.length > 0 && (
            <div>
              <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-2">Sources</h2>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {legalReport.sources.map((source) => (
                  <li
                    key={source.document_id}
                    className="border border-hairline px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {source.company} · {source.document_type}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        // Fallback: today's API returns a flat prose report — no
        // legal_report field yet (docs/16 Phase 4 hasn't shipped).
        <div className="space-y-3">
          {(job.final_report ?? '')
            .split('\n\n')
            .filter(Boolean)
            .map((paragraph, index) => (
              <p key={index} className="text-[14px] leading-relaxed text-ink-1">
                {paragraph}
              </p>
            ))}
        </div>
      )}

      <p className="border-t border-hairline pt-4 text-[12px] text-ink-2">{DISCLAIMER}</p>
    </div>
  )
}
