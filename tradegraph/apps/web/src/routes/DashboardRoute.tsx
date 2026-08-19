import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  BookMarked,
  FileSearch,
  Gavel,
  Scale,
  ScrollText,
  Sparkles,
  UploadCloud,
} from 'lucide-react'
import { useJobHistory } from '../lib/queryClient'
import { useBookmarks } from '../lib/bookmarks'
import { JOB_STATUS_DOT, JOB_STATUS_LABELS, JOB_STATUS_TEXT } from '../lib/theme'
import { ResearchTable } from '../components/ResearchTable'

const QUICK_ACTIONS = [
  { to: '/research/new', icon: Sparkles, label: 'Start Legal Research', enabled: true },
  { to: '/research/new?mode=case-law', icon: Gavel, label: 'Search Case Law', enabled: true },
  { to: '/research/new?mode=constitution', icon: Scale, label: 'Search Constitution', enabled: true },
  { to: '/research/new?mode=statutes', icon: ScrollText, label: 'Search Statutes', enabled: true },
  { to: '#', icon: UploadCloud, label: 'Upload Document', enabled: false },
  { to: '#', icon: FileSearch, label: 'Analyze Case', enabled: false },
] as const

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function DashboardRoute() {
  const { data: history, isLoading } = useJobHistory({ limit: 20 })
  const { bookmarkedIds } = useBookmarks()

  const continuable = (history ?? []).filter((j) => j.status !== 'failed').slice(0, 4)
  const saved = (history ?? []).filter((j) => bookmarkedIds.has(j.job_id)).slice(0, 4)

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <h1 className="font-serif text-xl text-ink-0">Dashboard</h1>
      <p className="mt-1 text-sm text-ink-1">Continue your work or start new legal research.</p>

      <Section title="Continue Research">
        {isLoading && <SkeletonRows count={2} />}
        {!isLoading && continuable.length === 0 && (
          <EmptyRow text="No research in progress yet." />
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {continuable.map((job) => (
            <Link
              key={job.job_id}
              to={`/research/${job.job_id}`}
              className="rounded-sm border border-hairline bg-surface-1 p-4 transition hover:border-hairline-strong"
            >
              <div className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${JOB_STATUS_DOT[job.status]}`} />
                <span className={`text-[11px] font-medium uppercase tracking-wide ${JOB_STATUS_TEXT[job.status]}`}>
                  {JOB_STATUS_LABELS[job.status]}
                </span>
                <span className="ml-auto text-[11px] text-ink-2">{relativeTime(job.created_at)}</span>
              </div>
              <p className="mt-2 line-clamp-2 text-sm text-ink-0">{job.query}</p>
              <span className="mt-2 inline-block text-[13px] font-medium text-accent">
                Resume research →
              </span>
            </Link>
          ))}
        </div>
      </Section>

      <Section title="Quick Actions">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {QUICK_ACTIONS.map(({ to, icon: Icon, label, enabled }) =>
            enabled ? (
              <Link
                key={label}
                to={to}
                className="flex flex-col gap-2 rounded-sm border border-hairline bg-surface-1 p-4 transition hover:border-accent-muted"
              >
                <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
                <span className="text-[13px] font-medium text-ink-0">{label}</span>
              </Link>
            ) : (
              <div
                key={label}
                className="flex cursor-not-allowed flex-col gap-2 rounded-sm border border-hairline bg-surface-1/50 p-4 opacity-60"
              >
                <div className="flex items-center justify-between">
                  <Icon className="h-4 w-4 text-ink-2" aria-hidden="true" />
                  <span className="rounded-sm border border-hairline px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-ink-2">
                    Coming soon
                  </span>
                </div>
                <span className="text-[13px] font-medium text-ink-1">{label}</span>
              </div>
            ),
          )}
        </div>
      </Section>

      <Section title="Recent Activity">
        <ResearchTable
          jobs={(history ?? []).slice(0, 8)}
          isLoading={isLoading}
          emptyText="No research sessions yet — start one above."
        />
      </Section>

      <Section title="Saved Research" icon={BookMarked}>
        <ResearchTable jobs={saved} emptyText="Star a research session to save it here." />
      </Section>
    </div>
  )
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string
  icon?: typeof BookMarked
  children: ReactNode
}) {
  return (
    <section className="mt-8 first:mt-6">
      <div className="mb-3 flex items-center gap-1.5">
        {Icon && <Icon className="h-3.5 w-3.5 text-ink-2" aria-hidden="true" />}
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-2">{title}</h2>
      </div>
      {children}
    </section>
  )
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-sm bg-surface-1" />
      ))}
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return (
    <div className="rounded-sm border border-dashed border-hairline px-4 py-6 text-center text-sm text-ink-2">
      {text}
    </div>
  )
}
