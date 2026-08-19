import { Link } from 'react-router-dom'
import { Bookmark, Trash2 } from 'lucide-react'
import type { JobSummary } from '../types'
import { useBookmarks } from '../lib/bookmarks'
import { useDeleteJob } from '../lib/queryClient'
import { JOB_STATUS_DOT, JOB_STATUS_LABELS, JOB_STATUS_TEXT } from '../lib/theme'

interface ResearchTableProps {
  jobs: JobSummary[]
  isLoading?: boolean
  emptyText: string
}

// Mirrors the API's DELETABLE_STATUSES (apps/api/routers/jobs.py) — a
// still-running job is rejected server-side because the worker is actively
// writing to it, so the row's delete affordance is disabled rather than
// left to fail on click.
const DELETABLE_STATUSES = new Set(['succeeded', 'failed'])

// Shared dense table register (Dashboard's Recent Activity / Saved
// Research, the History route) — one implementation so a status dot, a
// bookmark star, or a delete action behaves identically everywhere it
// appears.
export function ResearchTable({ jobs, isLoading, emptyText }: ResearchTableProps) {
  const { isBookmarked, toggleBookmark, removeBookmark } = useBookmarks()
  const deleteJob = useDeleteJob()

  if (isLoading) {
    return (
      <div className="space-y-2" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-11 animate-pulse rounded-sm bg-surface-1" />
        ))}
      </div>
    )
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-sm border border-dashed border-hairline px-4 py-6 text-center text-sm text-ink-2">
        {emptyText}
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-sm border border-hairline">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-hairline bg-surface-1 text-[11px] uppercase tracking-wide text-ink-2">
            <th className="w-8 px-3 py-2" />
            <th className="px-2 py-2 font-medium">Title</th>
            <th className="px-4 py-2 font-medium">Date</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="w-8 px-3 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline">
          {jobs.map((job) => {
            const bookmarked = isBookmarked(job.job_id)
            const deletable = DELETABLE_STATUSES.has(job.status)
            const deleting = deleteJob.isPending && deleteJob.variables === job.job_id
            return (
              <tr key={job.job_id} className="transition hover:bg-surface-1">
                <td className="px-3 py-2.5">
                  <button
                    type="button"
                    onClick={() => toggleBookmark(job.job_id)}
                    aria-label={bookmarked ? 'Remove from saved research' : 'Save research'}
                    aria-pressed={bookmarked}
                    className="text-ink-2 transition hover:text-accent"
                  >
                    <Bookmark
                      className="h-3.5 w-3.5"
                      fill={bookmarked ? 'currentColor' : 'none'}
                      color={bookmarked ? 'var(--color-accent)' : 'currentColor'}
                    />
                  </button>
                </td>
                <td className="px-2 py-2.5">
                  <Link
                    to={`/research/${job.job_id}`}
                    className="line-clamp-1 text-ink-0 hover:text-accent"
                  >
                    {job.query}
                  </Link>
                </td>
                <td className="whitespace-nowrap px-4 py-2.5 text-ink-2">
                  {new Date(job.created_at).toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                  })}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={`inline-flex items-center gap-1.5 text-[13px] ${JOB_STATUS_TEXT[job.status]}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${JOB_STATUS_DOT[job.status]}`} />
                    {JOB_STATUS_LABELS[job.status]}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <button
                    type="button"
                    disabled={!deletable || deleting}
                    title={deletable ? 'Delete research' : 'Wait for this job to finish before deleting'}
                    onClick={() => {
                      if (!window.confirm(`Delete this research? "${job.query}" cannot be recovered.`))
                        return
                      deleteJob.mutate(job.job_id, { onSuccess: () => removeBookmark(job.job_id) })
                    }}
                    aria-label="Delete research"
                    className="text-ink-2 transition hover:text-rose-400 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-ink-2"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
