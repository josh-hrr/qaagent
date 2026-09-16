import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { Button } from '../components/Button'
import {
  AlertIcon,
  BranchIcon,
  CheckIcon,
  ExternalLinkIcon,
  PlayIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
} from '../components/icons'
import { ApiError, runsApi, ticketsApi, type ReadinessStatus, type Ticket, type TicketsResponse } from '../lib/api'

type FilterKey = 'ready' | 'linked' | 'blocked' | 'all'

/** Returning to the tab re-fetches only if the list is at least this old.
 *  Commented out with the auto-refresh it throttles — uncomment both together. */
// const FOCUS_REFRESH_AFTER_MS = 60_000

function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`
}

const STATUS_STYLES: Record<ReadinessStatus, { text: string; bg: string; border: string; dot: string }> =
  {
    ok: { text: 'text-signal', bg: 'bg-signal-bg', border: 'border-signal-edge', dot: 'bg-signal' },
    warning: { text: 'text-warn', bg: 'bg-warn-bg', border: 'border-warn-edge', dot: 'bg-warn' },
    blocked: { text: 'text-danger', bg: 'bg-danger-bg', border: 'border-danger-edge', dot: 'bg-danger' },
  }

/** Linear's state buckets are stable across teams; the names are not. */
const STATE_DOT: Record<string, string> = {
  started: 'bg-signal',
  unstarted: 'bg-warn',
  triage: 'bg-warn',
  backlog: 'bg-fg-ghost',
  completed: 'bg-fg-faint',
  canceled: 'bg-fg-faint',
}

export function TicketPickerPage() {
  const [data, setData] = useState<TicketsResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterKey>('ready')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const lastFetchRef = useRef(0)
  const inFlightRef = useRef(false)
  // Re-render periodically so "updated 3m ago" does not freeze.
  const [, setClock] = useState(0)

  const load = useCallback(async (mode: 'initial' | 'refresh') => {
    if (inFlightRef.current) return
    inFlightRef.current = true
    if (mode === 'refresh') setRefreshing(true)
    try {
      const value = await ticketsApi.list()
      lastFetchRef.current = Date.now()
      setData(value)
      setError(null)
      setRefreshError(null)
      // Keep the open ticket open across a refresh, unless it disappeared.
      setSelectedId((current) =>
        current && value.tickets.some((t) => t.id === current) ? current : (value.tickets[0]?.id ?? null),
      )
    } catch (err: unknown) {
      const apiError =
        err instanceof ApiError ? err : new ApiError('Could not load tickets.', { status: 0 })
      if (mode === 'initial') {
        setError(apiError)
      } else {
        // A failed refresh keeps the tickets already on screen rather than
        // replacing a useful list with an error page.
        setRefreshError(apiError.message)
      }
    } finally {
      inFlightRef.current = false
      setRefreshing(false)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load('initial')
  }, [load])

  useEffect(() => {
    // Auto-refresh on returning to the tab — DISABLED to stay well clear of
    // Linear's rate limit. Refreshing is manual (the button) for now. To
    // re-enable, uncomment the listener below; it is throttled by
    // FOCUS_REFRESH_AFTER_MS so tab-flicking does not re-fetch every time.
    //
    // function onVisible() {
    //   if (document.visibilityState === 'visible' && Date.now() - lastFetchRef.current > FOCUS_REFRESH_AFTER_MS) {
    //     void load('refresh')
    //   }
    // }
    // document.addEventListener('visibilitychange', onVisible)

    // Local re-render only, so "updated 3m ago" does not freeze. Makes no request.
    const tick = window.setInterval(() => setClock((n) => n + 1), 30_000)
    return () => {
      // document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(tick)
    }
  }, [load])

  const tickets = data?.tickets ?? []

  const counts = useMemo(
    () => ({
      ready: tickets.filter((t) => t.readiness.status !== 'blocked').length,
      linked: tickets.filter((t) => t.pullRequests.length > 0).length,
      blocked: tickets.filter((t) => t.readiness.status === 'blocked').length,
      all: tickets.length,
    }),
    [tickets],
  )

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase()
    return tickets.filter((ticket) => {
      if (filter === 'ready' && ticket.readiness.status === 'blocked') return false
      if (filter === 'linked' && ticket.pullRequests.length === 0) return false
      if (filter === 'blocked' && ticket.readiness.status !== 'blocked') return false
      if (!query) return true
      return (
        ticket.identifier.toLowerCase().includes(query) ||
        ticket.title.toLowerCase().includes(query)
      )
    })
  }, [tickets, filter, search])

  const selected = tickets.find((t) => t.id === selectedId) ?? visible[0] ?? null

  const subtitle = data
    ? `${data.workspace.organizationName || 'Linear'} · ${data.workspace.teamNames.join(', ') || 'no teams'}`
    : undefined

  return (
    <AppShell
      title="Tickets"
      // Full height beside the header, as in the design — not under it.
      aside={
        !loading && !error && selected ? (
          <TicketDetail key={selected.id} ticket={selected} />
        ) : undefined
      }
      subtitle={subtitle}
      actions={
        <div className="flex items-center gap-2.5">
        {data && (
          <span
            className={`hidden font-mono text-[11px] sm:inline ${refreshError ? 'text-danger' : 'text-fg-faint'}`}
            title={refreshError ?? `Fetched ${new Date(data.fetchedAt).toLocaleTimeString()}`}
          >
            {refreshError ? 'refresh failed' : `updated ${relativeTime(data.fetchedAt)}`}
          </span>
        )}
        <button
          type="button"
          onClick={() => void load('refresh')}
          disabled={refreshing || loading}
          aria-label="Refresh tickets from Linear"
          title="Refresh tickets from Linear"
          className="flex size-7.5 cursor-pointer items-center justify-center rounded-md border border-edge-field text-fg-dim transition-colors hover:border-edge-strong hover:text-fg disabled:cursor-default disabled:opacity-60"
        >
          {refreshing ? <SpinnerIcon size={13} /> : <RefreshIcon size={14} />}
        </button>
        <div className="flex h-7.5 w-65 items-center gap-2 rounded-md border border-edge-field bg-ink-800 px-2.5 focus-within:border-signal-edge">
          <SearchIcon size={13} className="shrink-0 text-fg-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search ticket ID or title…"
            aria-label="Search tickets"
            className="min-w-0 flex-1 bg-transparent text-[12px] text-fg-muted outline-none"
          />
        </div>
        </div>
      }
    >
      {loading ? (
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          <SpinnerIcon size={18} />
          <span className="text-[13px]">Reading tickets from Linear…</span>
        </div>
      ) : error ? (
        <SetupPrompt error={error} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* --- list --- */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-2 px-5 py-3">
              {(
                [
                  { key: 'ready', label: 'Ready to test' },
                  { key: 'linked', label: 'Has linked PR' },
                  { key: 'blocked', label: 'Needs attention' },
                  { key: 'all', label: 'All' },
                ] as const
              ).map((chip) => {
                const on = chip.key === filter
                return (
                  <button
                    key={chip.key}
                    type="button"
                    onClick={() => setFilter(chip.key)}
                    aria-pressed={on}
                    className={`flex h-6.75 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-[12px] transition-colors ${
                      on
                        ? 'border-signal-edge bg-signal-bg text-signal'
                        : 'border-edge-field text-fg-dim hover:border-edge-strong'
                    }`}
                  >
                    {chip.label}
                    <span className="font-mono text-[10px] opacity-70">{counts[chip.key]}</span>
                  </button>
                )
              })}
              <div className="flex-1" />
              <span className="font-mono text-[11px] text-fg-faint">
                {visible.length} shown · open work first
              </span>
            </div>

            {/* Column names, aligned to the row below: 2px of left border plus
                the row's own padding. */}
            <div className="flex shrink-0 flex-wrap items-center gap-x-3 px-4 pt-0.5 pb-2 pl-4.5">
              <span className="label-micro w-18 shrink-0">Ticket</span>
              <span className="label-micro w-26 shrink-0">State</span>
              <span className="label-micro min-w-0 flex-1">Title</span>
              <span className="label-micro w-40 shrink-0">Pull requests</span>
              <span className="label-micro w-24 shrink-0 text-center">Readiness</span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto border-t border-edge">
              {visible.length === 0 ? (
                <p className="px-5 py-10 text-center text-[13px] text-fg-faint">
                  No tickets match this filter.
                </p>
              ) : (
                <ul>
                  {visible.map((ticket) => (
                    <li key={ticket.id}>
                      <TicketRow
                        ticket={ticket}
                        selected={ticket.id === selected?.id}
                        onSelect={() => setSelectedId(ticket.id)}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

        </div>
      )}
    </AppShell>
  )
}

function TicketRow({
  ticket,
  selected,
  onSelect,
}: {
  ticket: Ticket
  selected: boolean
  onSelect: () => void
}) {
  const status = STATUS_STYLES[ticket.readiness.status]
  const badge =
    ticket.readiness.status === 'blocked'
      ? 'BLOCKED'
      : ticket.readiness.warningCount > 0
        ? `READY · ${ticket.readiness.warningCount}`
        : 'READY'

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected}
      className={`flex w-full cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 border-b border-l-2 border-b-[#151A1E] px-4 py-3 text-left transition-colors ${
        selected ? 'border-l-signal bg-ink-600' : 'border-l-transparent hover:bg-ink-800'
      }`}
    >
      <span className={`w-18 shrink-0 font-mono text-[11px] ${selected ? 'text-fg' : 'text-fg-dimmer'}`}>
        {ticket.identifier}
      </span>
      <span className="flex w-26 shrink-0 items-center gap-2">
        <span className={`size-1.75 shrink-0 rounded-full ${STATE_DOT[ticket.state.type] ?? 'bg-fg-ghost'}`} />
        <span className="truncate text-[11.5px] text-fg-dim">{ticket.state.name}</span>
      </span>
      <span className={`min-w-0 flex-1 truncate text-[13.5px] ${selected ? 'text-fg' : 'text-fg-muted'}`}>
        {ticket.title}
      </span>
      <span className="flex w-40 shrink-0 items-center gap-1.5 text-fg-faint">
        <BranchIcon size={12} className="shrink-0" />
        <span className="truncate font-mono text-[10.5px]">
          {pullRequestSummary(ticket)}
        </span>
      </span>
      <span
        className={`w-24 shrink-0 rounded-[3px] border py-0.5 text-center font-mono text-[10px] ${status.border} ${status.bg} ${status.text}`}
      >
        {badge}
      </span>
    </button>
  )
}

function TicketDetail({ ticket }: { ticket: Ticket }) {
  const blocked = ticket.readiness.status === 'blocked'
  const navigate = useNavigate()
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  // Links parsed out of comments can belong to another ticket, and nothing in
  // the text says so. Unticking one keeps it out of this run.
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  async function generate() {
    if (blocked || starting) return
    setStarting(true)
    setStartError(null)
    try {
      // Only the id goes to the server — it re-reads the ticket itself, so the
      // run is built from Linear's current content, not this page's copy.
      const { run } = await runsApi.start(ticket.id, ticket.identifier, [...excluded])
      navigate(`/runs/${run.id}`)
    } catch (err) {
      setStartError(err instanceof ApiError ? err.message : 'Could not start the run.')
      setStarting(false)
    }
  }

  return (
    <aside className="flex w-full shrink-0 flex-col border-t border-edge bg-ink-800 xl:w-105 xl:border-t-0 xl:border-l">
      <div className="min-h-0 flex-1 overflow-y-auto px-4.5 py-4.5">
        <div className="mb-3 flex items-center gap-2.5">
          <span className="rounded-[3px] border border-info-edge bg-info-bg px-1.5 py-0.5 font-mono text-[10px] text-info">
            {ticket.identifier}
          </span>
          <span className="flex items-center gap-1.5">
            <span className={`size-1.5 rounded-full ${STATE_DOT[ticket.state.type] ?? 'bg-fg-ghost'}`} />
            <span className="text-[11.5px] text-fg-dim">{ticket.state.name}</span>
          </span>
          <div className="flex-1" />
          <a
            href={ticket.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 font-mono text-[11px] text-fg-faint hover:text-fg-dim"
          >
            Open in Linear <ExternalLinkIcon size={11} />
          </a>
        </div>

        <h2 className="mb-3.5 font-display text-[18px] leading-snug font-semibold text-fg-bright text-pretty">
          {ticket.title}
        </h2>

        <dl className="mb-4 flex gap-5 border-b border-edge pb-4">
          <div>
            <dt className="label-micro mb-1">Assignee</dt>
            <dd className="text-[12px] text-fg-muted">{ticket.assigneeName || 'unassigned'}</dd>
          </div>
          <div>
            <dt className="label-micro mb-1">Sub-issues</dt>
            <dd className="font-mono text-[12px] text-fg-muted">{ticket.subIssues.length}</dd>
          </div>
          <div>
            <dt className="label-micro mb-1">Comments</dt>
            <dd className="font-mono text-[12px] text-fg-muted">{ticket.commentCount}</dd>
          </div>
        </dl>

        {ticket.description ? (
          <>
            <p className="label-micro mb-1.5">Description</p>
            <p className="mb-4 line-clamp-6 text-[12.5px] whitespace-pre-line text-fg-dim text-pretty">
              {ticket.description}
            </p>
          </>
        ) : (
          <p className="mb-4 rounded-md border border-danger-edge bg-danger-bg px-3 py-2 text-[12px] text-fg-dim">
            This ticket has no description. There is nothing to test against.
          </p>
        )}

        <p className="label-micro mb-2">
          Acceptance criteria detected
          <span className="ml-2 font-mono text-fg-ghost normal-case">{ticket.criteria.length}</span>
        </p>
        {ticket.criteria.length > 0 ? (
          <ul className="mb-4.5 flex flex-col gap-1.5">
            {ticket.criteria.map((criterion) => (
              <li key={criterion.key} className="flex items-start gap-2.5">
                <span className="mt-px shrink-0 rounded-[3px] border border-info-edge bg-info-bg px-1.5 font-mono text-[10px] text-info">
                  {criterion.key}
                </span>
                <span className="flex-1 text-[12.5px] text-fg-muted text-pretty">{criterion.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mb-4.5 text-[12.5px] text-fg-faint text-pretty">
            None found. The agent would be guessing what "done" means.
          </p>
        )}

        {ticket.pullRequests.length > 0 && (
          <>
            <p className="label-micro mb-2">
              Pull requests
              <span className="ml-2 font-mono text-fg-ghost normal-case">{ticket.pullRequests.length}</span>
            </p>
            <ul className="mb-2 flex flex-col gap-1.5">
              {ticket.pullRequests.map((pr) => {
                const on = !excluded.has(pr.url)
                return (
                  <li
                    key={pr.url}
                    className={`flex items-center gap-2.5 rounded-md border bg-ink-700 px-2.5 py-2 ${
                      on ? 'border-edge' : 'border-edge opacity-55'
                    }`}
                  >
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={on}
                      aria-label={`Include ${pr.number ? `#${pr.number}` : 'this pull request'} in the run`}
                      onClick={() =>
                        setExcluded((prev) => {
                          const next = new Set(prev)
                          if (next.has(pr.url)) next.delete(pr.url)
                          else next.add(pr.url)
                          return next
                        })
                      }
                      className={`flex size-3.75 shrink-0 cursor-pointer items-center justify-center rounded border ${
                        on ? 'border-signal bg-signal' : 'border-fg-ghost hover:border-fg-faint'
                      }`}
                    >
                      {on && <CheckIcon size={9} className="text-ink-900" />}
                    </button>
                    <BranchIcon size={12} className="shrink-0 text-fg-faint" />
                    <a
                      href={pr.url}
                      target="_blank"
                      rel="noreferrer"
                      className={`min-w-0 flex-1 truncate font-mono text-[11.5px] no-underline hover:text-fg ${
                        on ? 'text-fg-muted' : 'text-fg-faint line-through'
                      }`}
                    >
                      {pr.number ? `#${pr.number}` : 'PR'} · {pr.repository || 'unknown repo'}
                    </a>
                    {!pr.inConnectedRepository && (
                      <span className="shrink-0 font-mono text-[10px] text-warn">repo not connected</span>
                    )}
                    <span className="shrink-0 font-mono text-[10px] text-fg-faint">{pr.source}</span>
                    <ExternalLinkIcon size={11} className="shrink-0 text-fg-faint" />
                  </li>
                )
              })}
            </ul>
            <p className="mb-4.5 text-[11px] text-fg-faint text-pretty">
              {excluded.size > 0
                ? `${excluded.size} left out of this run.`
                : 'Untick one a comment picked up from another ticket.'}
            </p>
          </>
        )}

        <p className="label-micro mb-2">Readiness</p>
        <ul className="flex flex-col gap-1.5">
          {ticket.readiness.checks.map((check) => {
            const style = STATUS_STYLES[check.status]
            return (
              <li
                key={check.key}
                className={`flex items-center gap-2.5 rounded-md border bg-ink-700 px-2.5 py-2 ${
                  check.status === 'ok' ? 'border-edge' : style.border
                }`}
              >
                <span className={`size-1.5 shrink-0 rounded-full ${style.dot}`} />
                <span className="flex-1 text-[12px] text-fg-muted">{check.label}</span>
                <span className={`shrink-0 font-mono text-[10.5px] ${style.text}`}>{check.detail}</span>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="shrink-0 border-t border-edge px-4.5 py-4">
        <Button
          variant={blocked ? 'secondary' : 'primary'}
          size="lg"
          block
          disabled={blocked}
          busy={starting}
          icon={<PlayIcon size={15} />}
          onClick={() => void generate()}
        >
          {blocked ? 'Cannot generate yet' : `Generate test cases for ${ticket.identifier}`}
        </Button>
        <p className={`mt-2 text-center font-mono text-[10.5px] ${startError ? 'text-danger' : 'text-fg-faint'}`}>
          {startError ??
            (blocked
              ? ticket.readiness.checks.find((c) => c.status === 'blocked')?.label
              : 'Reads the ticket fresh from Linear when it starts')}
        </p>
      </div>
    </aside>
  )
}

function SetupPrompt({ error }: { error: ApiError }) {
  const setup: Record<string, { message: string; to: string; cta: string }> = {
    linear_not_connected: {
      message: 'Connect Linear to see tickets.',
      to: '/setup/project-management',
      cta: 'Connect Linear',
    },
    no_teams_selected: {
      message: 'No Linear teams are selected yet.',
      to: '/setup/project-management',
      cta: 'Choose teams',
    },
  }
  const action = error.code ? setup[error.code] : undefined

  return (
    <div className="flex flex-1 items-center justify-center px-5">
      <div className="max-w-100 text-center">
        <div className="mx-auto mb-4 flex size-10 items-center justify-center rounded-full border border-warn-edge bg-warn-bg text-warn">
          <AlertIcon size={18} />
        </div>
        <p className="mb-5 text-[13.5px] text-fg-dim text-pretty">
          {action?.message ?? error.message}
        </p>
        {action && (
          <Link to={action.to} className="no-underline">
            <Button variant="primary">{action.cta}</Button>
          </Link>
        )}
      </div>
    </div>
  )
}

/** "PR #12 · core-api", "3 PRs", or a plain statement that none was found. */
function pullRequestSummary(ticket: Ticket): string {
  const prs = ticket.pullRequests
  if (prs.length === 0) return 'no PR found'
  if (prs.length === 1) {
    const [pr] = prs
    return pr.number ? `PR #${pr.number} · ${pr.repository}` : 'linked PR'
  }
  return `${prs.length} PRs`
}
