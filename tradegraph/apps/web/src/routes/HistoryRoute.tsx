import { useJobHistory } from '../lib/queryClient'
import { ResearchTable } from '../components/ResearchTable'

export function HistoryRoute() {
  const { data: history, isLoading } = useJobHistory({ limit: 100 })

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <h1 className="font-serif text-xl text-ink-0">All research</h1>
      <p className="mt-1 text-sm text-ink-1">Every research session, most recent first.</p>

      <div className="mt-6">
        <ResearchTable jobs={history ?? []} isLoading={isLoading} emptyText="No research yet." />
      </div>
    </div>
  )
}
