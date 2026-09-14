import { Link } from 'react-router-dom'

import { Button } from '../components/Button'
import { BrandMark, CheckIcon } from '../components/icons'
import { useAuth } from '../auth/AuthContext'

/** The screens from the design canvas, in build order. */
const ROADMAP: { n: string; name: string; done: boolean; to?: string }[] = [
  { n: '01', name: 'Sign in', done: true },
  { n: '02', name: 'Connect Linear', done: true, to: '/setup/project-management' },
  { n: '03', name: 'Connect repository', done: true, to: '/setup/source-code' },
  { n: '04', name: 'Pick a ticket', done: true, to: '/tickets' },
  { n: '05', name: 'Generation run', done: true, to: '/tickets' },
  { n: '06', name: 'Review workspace', done: false },
  { n: '07', name: 'Export CSV / Markdown', done: false },
]

/**
 * Placeholder landing spot for a signed-in user.
 *
 * Deliberately not a mock dashboard — it exists so the sign-in flow has
 * somewhere real to land, and it is replaced by screen 04 when that is built.
 */
export function HomePage() {
  const { user, signOut } = useAuth()

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex h-13 shrink-0 items-center gap-3 border-b border-edge px-5">
        <BrandMark size={26} />
        <span className="font-display text-sm font-bold">QA Agent</span>
        <span className="rounded-[3px] border border-edge-strong px-1.5 py-px font-mono text-[9px] text-fg-faint">
          v0.1
        </span>
        <div className="flex-1" />
        {user && (
          <div className="flex items-center gap-2.5">
            <span className="flex size-6.5 items-center justify-center rounded-md bg-signal-bg-strong font-mono text-[10px] text-signal">
              {user.initials}
            </span>
            <span className="hidden font-mono text-[11px] text-fg-dim sm:inline">{user.email}</span>
          </div>
        )}
        <Button variant="ghost" onClick={() => void signOut()}>
          Sign out
        </Button>
      </header>

      <main className="mx-auto w-full max-w-[640px] px-5 py-16">
        <p className="label-micro mb-3">Signed in</p>
        <h1 className="mb-2 font-display text-[26px] font-semibold text-fg-bright">
          Welcome, {user?.displayName}
        </h1>
        <p className="mb-10 text-[13.5px] text-fg-dimmer text-pretty">
          Screen 01 is wired end to end. The rest of the Phase 1 flow is drawn in the design canvas
          and lands here as it gets built.
        </p>

        <ol className="divide-y divide-edge overflow-hidden rounded-lg border border-edge bg-ink-800">
          {ROADMAP.map((step) => {
            const row = (
              <>
                <span
                  className={`flex size-5 shrink-0 items-center justify-center rounded-full border ${
                    step.done
                      ? 'border-signal-edge bg-signal-bg text-signal'
                      : 'border-edge-strong text-fg-ghost'
                  }`}
                >
                  {step.done ? <CheckIcon size={11} /> : <span className="size-1 rounded-full bg-current" />}
                </span>
                <span className="font-mono text-[11px] text-fg-ghost">{step.n}</span>
                <span className={`flex-1 text-[13px] ${step.done ? 'text-fg-muted' : 'text-fg-faint'}`}>
                  {step.name}
                </span>
                <span className="font-mono text-[10.5px] text-fg-faint">
                  {step.to ? 'open →' : step.done ? 'built' : 'designed'}
                </span>
              </>
            )
            return (
              <li key={step.n}>
                {step.to ? (
                  <Link
                    to={step.to}
                    className="flex items-center gap-3.5 px-4 py-3 no-underline transition-colors hover:bg-ink-700"
                  >
                    {row}
                  </Link>
                ) : (
                  <div className="flex items-center gap-3.5 px-4 py-3">{row}</div>
                )}
              </li>
            )
          })}
        </ol>
      </main>
    </div>
  )
}
