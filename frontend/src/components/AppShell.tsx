import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { runsApi } from '../lib/api'
import { Button } from './Button'
import { BrandMark, BranchIcon, GearIcon, PlayIcon, PlugIcon, TagIcon } from './icons'

type NavItem = {
  key: string
  label: string
  icon: ReactNode
  to?: string
  /** Matches the current path when it differs from `to`. */
  activePrefix?: string
  badge?: string
  /** Built, but nothing to open yet — muted without a "soon" label. */
  empty?: boolean
}

/** Items without a `to` are drawn muted — the screen does not exist yet, and
 *  a dead link is worse than a visible gap. */
function navItems(runs: RunsState): NavItem[] {
  return [
    {
      key: 'runs',
      label: 'Runs',
      icon: <PlayIcon size={16} />,
      // No run list screen yet, so Runs opens the most recent run.
      to: runs.latestId ? `/runs/${runs.latestId}` : undefined,
      activePrefix: '/runs/',
      badge: runs.activeCount > 0 ? `${runs.activeCount} live` : undefined,
      empty: runs.latestId === null,
    },
    { key: 'tickets', label: 'Tickets', icon: <TagIcon size={16} />, to: '/tickets' },
    { key: 'repos', label: 'Repositories', icon: <BranchIcon size={16} />, to: '/setup/source-code' },
    {
      key: 'connections',
      label: 'Connections',
      icon: <PlugIcon size={16} />,
      to: '/setup/project-management',
    },
    { key: 'settings', label: 'Settings', icon: <GearIcon size={16} /> },
  ]
}

type RunsState = { latestId: number | null; activeCount: number }

/** Chrome for the signed-in product screens (04 onward). */
export function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
}) {
  const { user, signOut } = useAuth()
  const { pathname } = useLocation()
  const [runs, setRuns] = useState<RunsState>({ latestId: null, activeCount: 0 })

  // Once per screen, from our own API — the badge is a hint, not a live feed,
  // so it does not poll. The run page itself polls its own run.
  useEffect(() => {
    let cancelled = false
    runsApi
      .list()
      .then(({ runs: list, activeCount }) => {
        if (!cancelled) setRuns({ latestId: list[0]?.id ?? null, activeCount })
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [pathname])

  return (
    <div className="flex min-h-dvh">
      <aside className="hidden w-59 shrink-0 flex-col border-r border-edge lg:flex">
        <div className="flex items-center gap-2.5 px-4.5 py-4.5">
          <BrandMark size={26} />
          <span className="font-display text-sm font-bold">QA Agent</span>
          <span className="rounded-[3px] border border-edge-strong px-1.5 py-px font-mono text-[9px] text-fg-faint">
            v0.1
          </span>
        </div>

        <nav className="flex flex-col gap-0.5 px-2.5">
          {navItems(runs).map((item) => {
            const active =
              (item.activePrefix !== undefined && pathname.startsWith(item.activePrefix)) ||
              (item.to !== undefined && pathname.startsWith(item.to))
            const className = `flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] ${
              active
                ? 'bg-ink-500 font-medium text-fg'
                : item.to
                  ? 'text-fg-dimmer hover:bg-ink-800 hover:text-fg-muted'
                  : 'cursor-default text-fg-ghost'
            }`
            const inner = (
              <>
                {item.icon}
                <span className="flex-1">{item.label}</span>
                {item.badge ? (
                  <span className="font-mono text-[10px] text-signal">{item.badge}</span>
                ) : (
                  !item.to && !item.empty && <span className="font-mono text-[9.5px]">soon</span>
                )}
              </>
            )
            return item.to ? (
              <Link key={item.key} to={item.to} className={`${className} no-underline`}>
                {inner}
              </Link>
            ) : (
              <span key={item.key} className={className} aria-disabled="true">
                {inner}
              </span>
            )
          })}
        </nav>

        <div className="flex-1" />

        <div className="flex items-center gap-2.5 border-t border-edge px-4 py-3">
          {user && (
            <>
              <span className="flex size-6.5 shrink-0 items-center justify-center rounded-md bg-signal-bg-strong font-mono text-[10px] text-signal">
                {user.initials}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] font-medium text-fg-muted">
                  {user.displayName}
                </span>
                <span className="block truncate font-mono text-[10px] text-fg-faint">
                  {user.email}
                </span>
              </span>
            </>
          )}
          <Button variant="ghost" onClick={() => void signOut()} className="shrink-0 px-2">
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-13 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-edge px-5">
          <h1 className="font-display text-[15px] font-semibold">{title}</h1>
          {subtitle && <div className="font-mono text-[11px] text-fg-faint">{subtitle}</div>}
          <div className="flex-1" />
          {actions}
        </header>
        {children}
      </div>
    </div>
  )
}
