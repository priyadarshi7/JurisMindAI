import { useJobHistory } from '../lib/queryClient'
import { useBookmarks } from '../lib/bookmarks'
import { ResearchTable } from '../components/ResearchTable'

export function SavedRoute() {
  // Pulls from the same cached history page the rest of the app already
  // fetches — bookmarks (localStorage, src/lib/bookmarks.ts) only store an
  // id, so a saved job outside the cached page won't resolve here. Honest
  // tradeoff for a client-only "saved" feature with no backing endpoint.
  const { data: history, isLoading } = useJobHistory({ limit: 100 })
  const { bookmarkedIds } = useBookmarks()

  const saved = (history ?? []).filter((job) => bookmarkedIds.has(job.job_id))

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <h1 className="font-serif text-xl text-ink-0">Saved research</h1>
      <p className="mt-1 text-sm text-ink-1">
        Bookmarked in this browser only — starring a research session from its workspace or the
        history list saves it here.
      </p>

      <div className="mt-6">
        <ResearchTable
          jobs={saved}
          isLoading={isLoading}
          emptyText="Nothing saved yet. Star a research session to keep it here."
        />
      </div>
    </div>
  )
}
