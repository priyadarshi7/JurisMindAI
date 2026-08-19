import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bell, Plus, Scale, Search, Settings, UserCircle } from 'lucide-react'
import { useJobHistory } from '../lib/queryClient'
import { useNotifications } from '../lib/notifications'
import { PRODUCT_NAME, PRODUCT_TAGLINE } from '../lib/theme'
import { CommandPalette } from './CommandPalette'

export function Header() {
  const navigate = useNavigate()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)
  const profileRef = useRef<HTMLDivElement>(null)
  const { data: history } = useJobHistory({ limit: 50 })
  const { notifications, unreadCount, markAllRead } = useNotifications()

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(event.target as Node)) setNotifOpen(false)
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) setProfileOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  return (
    <>
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-hairline bg-surface-0 px-5">
        <Link to="/" className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-accent" aria-hidden="true" />
          <span className="font-serif text-[15px] tracking-tight text-ink-0">{PRODUCT_NAME}</span>
          <span className="hidden text-[11px] text-ink-2 sm:inline">{PRODUCT_TAGLINE}</span>
        </Link>

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="flex flex-1 items-center gap-2 rounded-sm border border-hairline bg-surface-1 px-3 py-1.5 text-left text-sm text-ink-2 transition hover:border-hairline-strong max-w-md"
        >
          <Search className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="flex-1 truncate">Search research, cases, provisions…</span>
          <kbd className="hidden rounded-sm border border-hairline px-1.5 py-0.5 text-[10px] text-ink-2 sm:inline">
            ⌘K
          </kbd>
        </button>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate('/research/new')}
            className="flex items-center gap-1.5 rounded-sm bg-accent px-3 py-1.5 text-sm font-medium text-surface-0 transition hover:bg-accent-muted"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New Research
          </button>

          <div className="relative" ref={notifRef}>
            <button
              type="button"
              onClick={() => {
                setNotifOpen((open) => !open)
                if (!notifOpen) markAllRead()
              }}
              aria-label="Notifications"
              className="relative flex h-8 w-8 items-center justify-center rounded-sm text-ink-1 transition hover:bg-surface-1 hover:text-ink-0"
            >
              <Bell className="h-4 w-4" aria-hidden="true" />
              {unreadCount > 0 && (
                <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />
              )}
            </button>
            {notifOpen && (
              <div className="absolute right-0 z-20 mt-2 w-80 rounded-sm border border-hairline bg-surface-1 py-1 shadow-lg shadow-black/40">
                <p className="px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-ink-2">
                  Recent activity
                </p>
                {notifications.length === 0 && (
                  <p className="px-3 py-3 text-sm text-ink-2">Nothing yet this session.</p>
                )}
                {notifications.map((n) => (
                  <Link
                    key={`${n.jobId}-${n.status}`}
                    to={`/research/${n.jobId}`}
                    onClick={() => setNotifOpen(false)}
                    className="block px-3 py-2 text-sm text-ink-1 transition hover:bg-surface-2"
                  >
                    <span className="line-clamp-1">{n.query}</span>
                    <span className={n.status === 'succeeded' ? 'text-emerald-400' : 'text-rose-400'}>
                      {' '}
                      · {n.status === 'succeeded' ? 'Completed' : 'Failed'}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            aria-label="Settings"
            className="flex h-8 w-8 items-center justify-center rounded-sm text-ink-1 transition hover:bg-surface-1 hover:text-ink-0"
          >
            <Settings className="h-4 w-4" aria-hidden="true" />
          </button>

          <div className="relative" ref={profileRef}>
            <button
              type="button"
              onClick={() => setProfileOpen((open) => !open)}
              aria-label="Account"
              className="flex h-8 w-8 items-center justify-center rounded-full border border-hairline text-ink-1 transition hover:border-hairline-strong hover:text-ink-0"
            >
              <UserCircle className="h-4 w-4" aria-hidden="true" />
            </button>
            {profileOpen && (
              <div className="absolute right-0 z-20 mt-2 w-48 rounded-sm border border-hairline bg-surface-1 py-1 text-sm shadow-lg shadow-black/40">
                <p className="px-3 py-2 text-ink-1">Guest researcher</p>
                <p className="border-t border-hairline px-3 py-2 text-[11px] text-ink-2">
                  Sign-in isn't wired up yet — this is a local demo profile.
                </p>
              </div>
            )}
          </div>
        </div>
      </header>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        history={history ?? []}
      />
    </>
  )
}
