import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { JobResponse } from '../types'
import { jobKeys } from './queryClient'

// The header's notification bell (dashboard spec) is sourced from real job
// state transitions observed via TanStack Query's cache — not canned
// content. ResearchRoute already invalidates a job's query on every SSE
// status event, so subscribing to the cache here catches every real
// completion across the app without a second SSE connection or a fake
// notifications backend. Session-scoped only (in-memory) — reset on
// reload, same honesty tradeoff as the bookmarks store being
// localStorage-only rather than server-backed.

export interface Notification {
  jobId: string
  query: string
  status: 'succeeded' | 'failed'
  at: number
}

let notifications: Notification[] = []
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

function recordIfNew(job: JobResponse): void {
  if (job.status !== 'succeeded' && job.status !== 'failed') return
  if (notifications.some((n) => n.jobId === job.job_id && n.status === job.status)) return
  notifications = [{ jobId: job.job_id, query: job.query, status: job.status, at: Date.now() }, ...notifications].slice(0, 20)
  notify()
}

export function useNotifications(): {
  notifications: Notification[]
  unreadCount: number
  markAllRead: () => void
} {
  const queryClient = useQueryClient()
  const [, setTick] = useState(0)
  const [readCount, setReadCount] = useState(notifications.length)

  useEffect(() => {
    const listener = () => setTick((t) => t + 1)
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }, [])

  useEffect(() => {
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== 'updated') return
      const [root, , jobId] = event.query.queryKey as [string, string, string]
      if (root !== jobKeys.all[0] || jobId === undefined) return
      const data = event.query.state.data as JobResponse | undefined
      if (data) recordIfNew(data)
    })
    return unsubscribe
  }, [queryClient])

  return {
    notifications,
    unreadCount: Math.max(0, notifications.length - readCount),
    markAllRead: () => setReadCount(notifications.length),
  }
}
