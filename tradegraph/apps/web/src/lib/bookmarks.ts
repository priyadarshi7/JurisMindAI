import { useCallback, useEffect, useState } from 'react'

// Saved Research (dashboard spec) — deliberately localStorage-backed, not a
// new backend endpoint: this redesign is presentation-only, and a "Saved
// Research" list that's honestly client-side beats a fake server-backed
// one that doesn't exist. Scoped to this browser only, which is disclosed
// in the UI copy wherever bookmarks are shown.

const STORAGE_KEY = 'jurismindai:bookmarked-job-ids'

function readBookmarks(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function writeBookmarks(ids: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
  } catch {
    // Storage unavailable (private browsing, quota) — bookmarking silently
    // becomes a no-op rather than crashing the workspace over it.
  }
}

export function useBookmarks(): {
  bookmarkedIds: Set<string>
  isBookmarked: (jobId: string) => boolean
  toggleBookmark: (jobId: string) => void
  removeBookmark: (jobId: string) => void
} {
  const [bookmarkedIds, setBookmarkedIds] = useState<Set<string>>(() => readBookmarks())

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setBookmarkedIds(readBookmarks())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const toggleBookmark = useCallback((jobId: string) => {
    setBookmarkedIds((current) => {
      const next = new Set(current)
      if (next.has(jobId)) next.delete(jobId)
      else next.add(jobId)
      writeBookmarks(next)
      return next
    })
  }, [])

  // Unlike toggleBookmark, idempotent removal — used when a job is deleted,
  // so a stale bookmark id never outlives the research it pointed to.
  const removeBookmark = useCallback((jobId: string) => {
    setBookmarkedIds((current) => {
      if (!current.has(jobId)) return current
      const next = new Set(current)
      next.delete(jobId)
      writeBookmarks(next)
      return next
    })
  }, [])

  const isBookmarked = useCallback((jobId: string) => bookmarkedIds.has(jobId), [bookmarkedIds])

  return { bookmarkedIds, isBookmarked, toggleBookmark, removeBookmark }
}
