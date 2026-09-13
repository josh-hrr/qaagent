import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '../components/Button'
import { WizardShell, setupSteps } from '../components/WizardShell'
import {
  AlertIcon,
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  SpinnerIcon,
  TrashIcon,
} from '../components/icons'
import {
  ApiError,
  connectionsApi,
  type Connection,
  type LinearTeam,
} from '../lib/api'

type ProviderKey = 'linear' | 'jira' | 'azure_boards'

const PROVIDERS: {
  key: ProviderKey
  name: string
  initial: string
  markClass: string
  note: string
  available: boolean
}[] = [
  {
    key: 'linear',
    name: 'Linear',
    initial: 'L',
    markClass: 'bg-[#1E2436] text-[#8B9BF5]',
    note: 'Issues, sub-issues, comments and project docs. Ticket ID drives branch matching.',
    available: true,
  },
  {
    key: 'jira',
    name: 'Jira',
    initial: 'J',
    markClass: 'bg-info-bg text-info',
    note: 'Same adapter shape — issue fields, sub-tasks, comments. Not wired up yet.',
    available: false,
  },
  {
    key: 'azure_boards',
    name: 'Azure Boards',
    initial: 'A',
    markClass: 'bg-info-bg text-info',
    note: 'Useful if you already run work items next to the repos in the same org.',
    available: false,
  },
]

const PULLED_PER_TICKET = [
  'description',
  'acceptance criteria',
  'sub-issues',
  'comments',
  'labels',
  'linked PR / branch',
]

/** What the Linear panel is currently showing. */
type LinearView =
  | { kind: 'empty' }
  /** Key checked but not yet stored — the user is choosing teams. */
  | { kind: 'verified'; accountLabel: string; teams: LinearTeam[]; apiKey: string }
  | { kind: 'connected'; connection: Connection }

export function ConnectProjectManagementPage() {
  const navigate = useNavigate()

  const [provider, setProvider] = useState<ProviderKey>('linear')
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<LinearView>({ kind: 'empty' })
  const [oauthConfigured, setOauthConfigured] = useState(false)

  const [apiKey, setApiKey] = useState('')
  const [revealKey, setRevealKey] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<'verify' | 'connect' | 'save' | 'disconnect' | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const loadConnections = useCallback(async () => {
    try {
      const { connections, linearOAuthConfigured } = await connectionsApi.list()
      setOauthConfigured(linearOAuthConfigured)
      const linear = connections.find((c) => c.provider === 'linear')
      if (linear) {
        setView({ kind: 'connected', connection: linear })
        setSelected(new Set(linear.teams.filter((t) => t.selected).map((t) => t.linear_id)))
      }
    } catch {
      // Not fatal — the screen still works, the user just starts from empty.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadConnections()
  }, [loadConnections])

  function fail(err: unknown) {
    setError(err instanceof ApiError ? err : new ApiError('Something went wrong.', { status: 0 }))
  }

  async function verify(event: FormEvent) {
    event.preventDefault()
    if (!apiKey.trim() || busy) return
    setBusy('verify')
    setError(null)
    try {
      const { account, teams } = await connectionsApi.verifyLinear(apiKey.trim())
      setView({
        kind: 'verified',
        accountLabel: account.email || account.name,
        teams,
        apiKey: apiKey.trim(),
      })
      // Nothing pre-selected: picking teams is a deliberate choice, and a wrong
      // default here means syncing tickets nobody asked for.
      setSelected(new Set())
    } catch (err) {
      fail(err)
    } finally {
      setBusy(null)
    }
  }

  async function connect() {
    if (view.kind !== 'verified' || selected.size === 0 || busy) return
    setBusy('connect')
    setError(null)
    try {
      const { connection } = await connectionsApi.connectLinear(view.apiKey, [...selected])
      setView({ kind: 'connected', connection })
      setApiKey('')
      setRevealKey(false)
      setSavedAt(Date.now())
    } catch (err) {
      fail(err)
    } finally {
      setBusy(null)
    }
  }

  async function saveTeams() {
    if (view.kind !== 'connected' || selected.size === 0 || busy) return
    setBusy('save')
    setError(null)
    try {
      const { connection } = await connectionsApi.updateLinearTeams([...selected])
      setView({ kind: 'connected', connection })
      setSavedAt(Date.now())
    } catch (err) {
      fail(err)
    } finally {
      setBusy(null)
    }
  }

  async function disconnect() {
    if (busy) return
    setBusy('disconnect')
    setError(null)
    try {
      await connectionsApi.disconnectLinear()
      setView({ kind: 'empty' })
      setSelected(new Set())
      setApiKey('')
      setSavedAt(null)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(null)
    }
  }

  function toggleTeam(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const isLinear = provider === 'linear'
  const connected = view.kind === 'connected'
  const teams = view.kind === 'verified' ? view.teams : connected ? view.connection.teams : []
  const storedSelection = connected
    ? new Set(view.connection.teams.filter((t) => t.selected).map((t) => t.linear_id))
    : new Set<string>()
  const selectionChanged =
    connected &&
    (selected.size !== storedSelection.size || [...selected].some((id) => !storedSelection.has(id)))

  const footerHint = !isLinear
    ? 'Linear is the only Phase 1 option'
    : connected
      ? selectionChanged
        ? 'Unsaved team changes'
        : `Connected to ${view.connection.organizationName || 'Linear'}`
      : 'Connect Linear to continue'

  return (
    <WizardShell
      steps={setupSteps(0)}
      footer={
        <div className="flex items-center justify-between gap-4">
          <Button variant="secondary" onClick={() => navigate('/')}>
            Back
          </Button>
          <div className="flex items-center gap-3.5">
            <span
              className={`hidden font-mono text-[11px] sm:inline ${
                connected && !selectionChanged ? 'text-fg-faint' : 'text-warn'
              }`}
            >
              {footerHint}
            </span>
            <Button
              variant={connected && !selectionChanged ? 'primary' : 'secondary'}
              disabled={!connected || selectionChanged}
              onClick={() => navigate('/setup/source-code')}
              icon={<ArrowRightIcon size={14} />}
            >
              Continue
            </Button>
          </div>
        </div>
      }
    >
      <h1 className="mb-2 font-display text-[28px] font-semibold tracking-tight text-fg-bright">
        Connect your project management tool
      </h1>
      <p className="mb-6 max-w-[620px] text-[14px] text-fg-dimmer text-pretty">
        This is where ticket scope comes from — description, acceptance criteria, sub-issues and
        comments. Without it the agent can only test what the diff implies, not what was asked for.
      </p>

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {PROVIDERS.map((p) => {
          const on = p.key === provider
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => setProvider(p.key)}
              aria-pressed={on}
              className={`flex cursor-pointer flex-col gap-2.5 rounded-[9px] border p-4 text-left transition-colors ${
                on ? 'border-signal-edge bg-[#121710]' : 'border-edge bg-ink-800 hover:border-edge-strong'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className={`flex size-7.5 shrink-0 items-center justify-center rounded-[7px] font-mono text-[13px] ${p.markClass}`}
                >
                  {p.initial}
                </span>
                <span
                  className={`flex-1 font-display text-[14.5px] font-semibold ${on ? 'text-fg' : 'text-fg-muted'}`}
                >
                  {p.name}
                </span>
                <span
                  className={`flex size-4 items-center justify-center rounded-full border ${
                    on ? 'border-signal bg-signal' : 'border-fg-ghost'
                  }`}
                >
                  {on && <span className="size-1.5 rounded-full bg-ink-900" />}
                </span>
              </div>
              <span className="text-[12px] text-fg-dimmer text-pretty">{p.note}</span>
              <span
                className={`font-mono text-[10px] tracking-[0.06em] ${p.available ? 'text-signal' : 'text-fg-faint'}`}
              >
                {p.available ? 'AVAILABLE NOW' : 'PHASE 2'}
              </span>
            </button>
          )
        })}
      </div>

      {loading ? (
        <div className="flex items-center gap-3 rounded-[10px] border border-edge bg-ink-800 px-5 py-8 text-fg-faint">
          <SpinnerIcon size={18} />
          <span className="text-[13px]">Checking existing connections…</span>
        </div>
      ) : isLinear ? (
        <div className="rounded-[10px] border border-edge bg-ink-800 px-5 py-5">
          {/* --- credential --- */}
          <div className="mb-5 flex flex-col gap-5 lg:flex-row">
            <div className="flex-1">
              <p className="label-micro mb-1.5">Personal API key</p>

              {connected ? (
                <>
                  {/* Not styled like the input it replaces — a bordered box on
                      a dark field reads as "type here", and this cannot be
                      edited. "Replace key" is the way to change it. */}
                  <div className="flex h-[38px] items-center gap-2">
                    <span className="min-w-0 truncate font-mono text-[12.5px] text-fg-muted">
                      {view.connection.credentialHint}
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-signal">
                      <CheckIcon size={13} />
                      <span className="font-mono text-[10.5px]">verified</span>
                    </span>
                  </div>
                  <p className="mt-1.5 text-[11.5px] text-fg-faint">
                    Verified as{' '}
                    <span className="font-mono text-fg-dim">
                      {view.connection.accountEmail || view.connection.accountName}
                    </span>{' '}
                    · read-only scopes
                  </p>
                </>
              ) : (
                <form onSubmit={verify}>
                  <div className="flex gap-2">
                    <div
                      className={`flex h-[38px] flex-1 items-center gap-2 rounded-[7px] border bg-ink-900 px-3 ${
                        error && !busy ? 'border-danger-edge' : 'border-edge-field focus-within:border-signal-edge'
                      }`}
                    >
                      <input
                        type={revealKey ? 'text' : 'password'}
                        value={apiKey}
                        onChange={(e) => {
                          setApiKey(e.target.value)
                          if (error) setError(null)
                        }}
                        placeholder="lin_api_…"
                        aria-label="Linear personal API key"
                        // A credential, not a saved form value.
                        autoComplete="off"
                        spellCheck={false}
                        className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-fg-muted outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => setRevealKey((v) => !v)}
                        aria-label={revealKey ? 'Hide key' : 'Show key'}
                        className="cursor-pointer text-fg-faint hover:text-fg-dim"
                      >
                        {revealKey ? <EyeOffIcon size={14} /> : <EyeIcon size={14} />}
                      </button>
                    </div>
                    <Button
                      type="submit"
                      variant="secondary"
                      busy={busy === 'verify'}
                      disabled={!apiKey.trim()}
                      className="h-[38px] shrink-0"
                    >
                      Check key
                    </Button>
                  </div>
                  <p className="mt-1.5 text-[11.5px] text-fg-faint">
                    Linear → Settings → Security &amp; access → Personal API keys.
                  </p>
                </form>
              )}
            </div>

            <div className="w-full shrink-0 lg:w-[214px]">
              <p className="label-micro mb-1.5">Or use OAuth</p>
              <div
                className={`flex h-[38px] items-center justify-center rounded-[7px] border text-[12.5px] ${
                  oauthConfigured
                    ? 'cursor-pointer border-edge-strong text-fg-muted hover:border-fg-faint'
                    : 'border-edge text-fg-faint'
                }`}
              >
                {oauthConfigured ? 'Authorise workspace' : 'Not configured'}
              </div>
              <p className="mt-1.5 text-[11.5px] text-fg-faint">
                {oauthConfigured
                  ? 'Recommended for shared team use.'
                  : 'Needs a registered Linear app. Phase 2.'}
              </p>
            </div>
          </div>

          {error && (
            <Callout tone="danger" className="mb-5">
              {error.message}
            </Callout>
          )}

          {/* --- teams --- */}
          {teams.length > 0 && (
            <>
              <div className="mb-4 h-px bg-edge" />
              <div className="mb-2.5 flex items-center justify-between">
                <p className="label-micro">Teams to sync</p>
                <p className="font-mono text-[11px] text-fg-faint">
                  {selected.size} of {teams.length} selected
                </p>
              </div>
              <div className="mb-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {teams.map((team) => {
                  const on = selected.has(team.linear_id)
                  return (
                    <button
                      key={team.linear_id}
                      type="button"
                      role="checkbox"
                      aria-checked={on}
                      onClick={() => toggleTeam(team.linear_id)}
                      className={`flex cursor-pointer items-center gap-3 rounded-[7px] border px-3 py-2.5 text-left transition-colors ${
                        on ? 'border-signal-edge bg-[#121710]' : 'border-edge bg-ink-700 hover:border-edge-strong'
                      }`}
                    >
                      <span
                        className={`flex size-[15px] shrink-0 items-center justify-center rounded-[4px] border ${
                          on ? 'border-signal bg-signal' : 'border-fg-ghost'
                        }`}
                      >
                        {on && <CheckIcon size={9} className="text-ink-900" />}
                      </span>
                      <span className={`flex-1 truncate text-[13px] ${on ? 'text-fg' : 'text-fg-muted'}`}>
                        {team.name}
                      </span>
                      <span className="shrink-0 rounded-[3px] border border-edge-strong px-1.5 font-mono text-[10px] text-fg-faint">
                        {team.key || '—'}
                      </span>
                    </button>
                  )
                })}
              </div>
            </>
          )}

          {/* --- actions --- */}
          {view.kind === 'verified' && (
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                busy={busy === 'connect'}
                disabled={selected.size === 0}
                onClick={() => void connect()}
              >
                Connect Linear
              </Button>
              <span className="font-mono text-[11px] text-fg-faint">
                {selected.size === 0 ? 'Pick at least one team' : `Key verified as ${view.accountLabel}`}
              </span>
            </div>
          )}

          {connected && (
            <div className="flex flex-wrap items-center gap-3">
              {selectionChanged && (
                <Button variant="primary" busy={busy === 'save'} onClick={() => void saveTeams()}>
                  Save team changes
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => {
                  setView({ kind: 'empty' })
                  setSelected(new Set())
                }}
              >
                Replace key
              </Button>
              <Button
                variant="ghost"
                busy={busy === 'disconnect'}
                onClick={() => void disconnect()}
                icon={<TrashIcon size={14} />}
              >
                Disconnect
              </Button>
              <div className="flex-1" />
              {savedAt && !selectionChanged && (
                <span className="flex items-center gap-1.5 font-mono text-[11px] text-signal">
                  <CheckIcon size={12} /> Saved
                </span>
              )}
            </div>
          )}

          {/* --- what gets pulled --- */}
          <div className="mt-6 border-t border-edge pt-4">
            <p className="label-micro mb-2.5">What gets pulled per ticket</p>
            <ul className="flex flex-wrap gap-2">
              {PULLED_PER_TICKET.map((item) => (
                <li key={item} className="flex h-6.5 items-center gap-1.5 pr-3">
                  <CheckIcon size={11} className="text-signal" />
                  <span className="font-mono text-[11px] text-fg-dim">{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <Callout tone="neutral" className="mt-4" icon={<LockIcon size={14} />}>
            The key is encrypted before it is stored and never sent back to the browser — you can
            replace it, but not read it. It belongs to the workspace, so everyone shares one
            connection and revoking it revokes it for all.
          </Callout>
        </div>
      ) : (
        <div className="flex items-start gap-4 rounded-[10px] border border-dashed border-edge-strong bg-ink-800 px-5 py-7">
          <ClockIcon size={20} className="mt-0.5 shrink-0 text-warn" />
          <div>
            <h2 className="mb-1.5 font-display text-[16px] font-semibold text-fg">
              {PROVIDERS.find((p) => p.key === provider)?.name} lands in Phase 2
            </h2>
            <p className="max-w-[560px] text-[13px] text-fg-dimmer text-pretty">
              The ticket adapter is deliberately thin — one interface returning description,
              acceptance criteria, sub-issues and comments — so adding it is a connector, not a
              rewrite. Phase 1 ships Linear only.
            </p>
          </div>
        </div>
      )}
    </WizardShell>
  )
}

function Callout({
  tone,
  icon,
  className,
  children,
}: {
  tone: 'danger' | 'neutral'
  icon?: ReactNode
  className?: string
  children: ReactNode
}) {
  const tones = {
    danger: 'border-danger-edge bg-danger-bg',
    neutral: 'border-edge bg-ink-700',
  }
  return (
    <div
      role={tone === 'danger' ? 'alert' : undefined}
      className={`flex gap-2.5 rounded-[7px] border px-3 py-2.5 ${tones[tone]} ${className ?? ''}`}
    >
      <span className={`mt-px shrink-0 ${tone === 'danger' ? 'text-danger' : 'text-fg-faint'}`}>
        {icon ?? <AlertIcon size={14} />}
      </span>
      <span className="text-[12px] text-fg-dimmer text-pretty">{children}</span>
    </div>
  )
}
