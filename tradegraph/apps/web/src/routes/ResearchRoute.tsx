import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Bookmark, Check, Copy, Trash2 } from 'lucide-react'
import { streamJobStatus } from '../api'
import { jobKeys, useDeleteJob, useJob } from '../lib/queryClient'
import { useBookmarks } from '../lib/bookmarks'
import { JOB_STATUS_DOT, JOB_STATUS_LABELS, JOB_STATUS_TEXT } from '../lib/theme'
import { JobProgress } from '../components/JobProgress'
import { ReportView } from '../components/ReportView'
import { EvidencePanel } from '../components/EvidencePanel'
import type { JobResponse, JobStatus } from '../types'

const TERMINAL_STATUSES: JobStatus[] = ['succeeded', 'failed']

export function ResearchRoute() {
  const { jobId } = useParams<{ jobId: string }>()
  const queryClient = useQueryClient()
  const { data: job, isLoading, isError } = useJob(jobId)
  const [liveStatus, setLiveStatus] = useState<JobStatus | null>(null)
  const [progressLog, setProgressLog] = useState<string[]>([])
  const unsubscribeRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!jobId) return undefined

    setProgressLog([])
    setLiveStatus(null)
    unsubscribeRef.current?.()

    unsubscribeRef.current = streamJobStatus(jobId, {
      onStatus: (status) => {
        setLiveStatus(status)
        if (TERMINAL_STATUSES.includes(status)) {
          unsubscribeRef.current?.()
          void queryClient.invalidateQueries({ queryKey: jobKeys.detail(jobId) })
          void queryClient.invalidateQueries({ queryKey: jobKeys.history() })
        }
      },
      onProgress: (detail) => setProgressLog((log) => [...log, detail]),
      onConnectionError: () => {
        void queryClient.invalidateQueries({ queryKey: jobKeys.detail(jobId) })
      },
    })

    return () => unsubscribeRef.current?.()
  }, [jobId, queryClient])

  if (!jobId) return null

  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-8">
        <div className="h-5 w-2/3 animate-pulse bg-surface-1" />
        <div className="mt-6 space-y-2">
          <div className="h-16 animate-pulse bg-surface-1" />
          <div className="h-16 animate-pulse bg-surface-1" />
        </div>
      </div>
    )
  }

  if (isError || !job) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-8">
        <div className="border border-rose-900 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">
          Could not load this research job.
        </div>
      </div>
    )
  }

  // The fetched `job` (React Query cache) is the source of truth for which
  // view to show — `liveStatus` from SSE only enriches the in-progress
  // stepper. Switching views based on the SSE event alone would flash a
  // blank state in the gap between "succeeded" arriving over the wire and
  // the resulting refetch actually landing.
  const isTerminal = TERMINAL_STATUSES.includes(job.status)

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <WorkspaceHeader job={job} />

      <div className="mt-6 space-y-6">
        {!isTerminal && <JobProgress status={liveStatus ?? job.status} progressLog={progressLog} />}

        {isTerminal && (
          <>
            <ReportView job={job} />
            {job.status === 'succeeded' && <EvidencePanel claims={job.claims} />}
          </>
        )}
      </div>
    </div>
  )
}

function WorkspaceHeader({ job }: { job: JobResponse }) {
  const navigate = useNavigate()
  const { isBookmarked, toggleBookmark, removeBookmark } = useBookmarks()
  const deleteJob = useDeleteJob()
  const [copied, setCopied] = useState(false)
  const bookmarked = isBookmarked(job.job_id)
  const deletable = TERMINAL_STATUSES.includes(job.status)

  const handleCopy = async () => {
    const text = job.final_report ?? ''
    await navigator.clipboard.writeText(`${job.query}\n\n${text}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const handleDelete = () => {
    if (!window.confirm(`Delete this research? "${job.query}" cannot be recovered.`)) return
    deleteJob.mutate(job.job_id, {
      onSuccess: () => {
        removeBookmark(job.job_id)
        navigate('/history')
      },
    })
  }

  return (
    <header className="border-b border-hairline pb-4">
      <div className="flex items-start gap-3">
        <h1 className="flex-1 font-serif text-xl leading-snug text-ink-0">{job.query}</h1>
        <div className="flex shrink-0 items-center gap-1">
          {job.status === 'succeeded' && job.final_report && (
            <button
              type="button"
              onClick={handleCopy}
              aria-label="Copy report"
              className="flex h-7 w-7 items-center justify-center text-ink-2 transition hover:text-ink-0"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          )}
          <button
            type="button"
            onClick={() => toggleBookmark(job.job_id)}
            aria-label={bookmarked ? 'Remove from saved research' : 'Save research'}
            aria-pressed={bookmarked}
            className="flex h-7 w-7 items-center justify-center text-ink-2 transition hover:text-accent"
          >
            <Bookmark
              className="h-3.5 w-3.5"
              fill={bookmarked ? 'currentColor' : 'none'}
              color={bookmarked ? 'var(--color-accent)' : 'currentColor'}
            />
          </button>
          {deletable && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleteJob.isPending}
              aria-label="Delete research"
              className="flex h-7 w-7 items-center justify-center text-ink-2 transition hover:text-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-3 text-[12px] text-ink-2">
        <span className={`inline-flex items-center gap-1.5 ${JOB_STATUS_TEXT[job.status]}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${JOB_STATUS_DOT[job.status]}`} />
          {JOB_STATUS_LABELS[job.status]}
        </span>
        {job.status === 'succeeded' && (
          <span>
            {job.claims.length} claim{job.claims.length === 1 ? '' : 's'} ·{' '}
            {job.claims.reduce((n, c) => n + c.citations.length, 0)} citation
            {job.claims.reduce((n, c) => n + c.citations.length, 0) === 1 ? '' : 's'}
          </span>
        )}
      </div>
    </header>
  )
}
