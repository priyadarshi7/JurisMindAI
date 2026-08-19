import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { Search } from 'lucide-react'
import type { JobSummary } from '../types'
import { JOB_STATUS_DOT } from '../lib/theme'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  history: JobSummary[]
}

// Global search (header spec) — filters real research history client-side.
// Deliberately not a corpus/case-law search: no such backend endpoint
// exists, and this redesign doesn't add one (see plan). Scoped honestly to
// what's actually searchable today.
export function CommandPalette({ open, onClose, history }: CommandPaletteProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return history.slice(0, 8)
    return history.filter((job) => job.query.toLowerCase().includes(q)).slice(0, 8)
  }, [query, history])

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          className="fixed left-1/2 top-24 z-50 w-full max-w-lg -translate-x-1/2 rounded-sm border border-hairline-strong bg-surface-1 shadow-2xl shadow-black/60"
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">Search research history</Dialog.Title>
          <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
            <Search className="h-4 w-4 text-ink-2" aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search research history…"
              className="flex-1 bg-transparent text-sm text-ink-0 outline-none placeholder:text-ink-2"
            />
            <kbd className="rounded-sm border border-hairline px-1.5 py-0.5 text-[10px] text-ink-2">
              Esc
            </kbd>
          </div>

          <div className="max-h-80 overflow-y-auto py-1">
            {results.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-ink-2">No matching research found.</p>
            )}
            {results.map((job) => (
              <button
                key={job.job_id}
                type="button"
                onClick={() => {
                  navigate(`/research/${job.job_id}`)
                  onClose()
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-ink-1 transition hover:bg-surface-2"
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${JOB_STATUS_DOT[job.status]}`} />
                <span className="line-clamp-1 flex-1">{job.query}</span>
              </button>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
