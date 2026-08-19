import { NavLink } from 'react-router-dom'
import { Bookmark, History, LayoutDashboard } from 'lucide-react'
import { useJobHistory } from '../lib/queryClient'
import { useBookmarks } from '../lib/bookmarks'
import { JOB_STATUS_DOT } from '../lib/theme'
import type { JobSummary } from '../types'

function groupByDay<T extends { created_at: string }>(items: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const label = new Date(item.created_at).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    })
    const existing = groups.get(label)
    if (existing) existing.push(item)
    else groups.set(label, [item])
  }
  return Array.from(groups.entries())
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] font-medium transition ${
    isActive ? 'bg-surface-2 text-ink-0' : 'text-ink-1 hover:bg-surface-1 hover:text-ink-0'
  }`

export function Sidebar() {
  const { data: history, isLoading } = useJobHistory({ limit: 30 })
  const { bookmarkedIds } = useBookmarks()

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-hairline bg-surface-0">
      <nav className="space-y-0.5 px-3 pt-4" aria-label="Primary">
        <NavLink to="/" end className={navLinkClass}>
          <LayoutDashboard className="h-3.5 w-3.5" aria-hidden="true" />
          Dashboard
        </NavLink>
        <NavLink to="/history" className={navLinkClass}>
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          All research
        </NavLink>
        <NavLink to="/saved" className={navLinkClass}>
          <Bookmark className="h-3.5 w-3.5" aria-hidden="true" />
          Saved research
          {bookmarkedIds.size > 0 && (
            <span className="ml-auto text-[11px] text-ink-2">{bookmarkedIds.size}</span>
          )}
        </NavLink>
      </nav>

      <div className="mt-5 flex min-h-0 flex-1 flex-col px-3 pb-4">
        <h2 className="px-2.5 text-[11px] font-medium uppercase tracking-wide text-ink-2">
          Recent
        </h2>

        <div className="mt-1.5 flex-1 overflow-y-auto" aria-label="Research history">
          {isLoading && (
            <ul className="space-y-1.5 px-1 pt-1" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="h-8 animate-pulse rounded-sm bg-surface-1" />
              ))}
            </ul>
          )}

          {!isLoading && (!history || history.length === 0) && (
            <p className="px-2.5 pt-1 text-[13px] text-ink-2">No research yet.</p>
          )}

          {!isLoading &&
            history &&
            groupByDay(history).map(([day, jobs]) => (
              <SidebarGroup key={day} day={day} jobs={jobs} />
            ))}
        </div>
      </div>
    </aside>
  )
}

function SidebarGroup({ day, jobs }: { day: string; jobs: JobSummary[] }) {
  return (
    <div className="mt-2.5 first:mt-0">
      <p className="px-2.5 pb-0.5 text-[10px] font-medium text-ink-2">{day}</p>
      <ul>
        {jobs.map((job) => (
          <li key={job.job_id}>
            <NavLink
              to={`/research/${job.job_id}`}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] transition ${
                  isActive ? 'bg-surface-2 text-ink-0' : 'text-ink-1 hover:bg-surface-1'
                }`
              }
            >
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${JOB_STATUS_DOT[job.status]}`} />
              <span className="line-clamp-1">{job.query}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  )
}
