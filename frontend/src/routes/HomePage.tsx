import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { Button } from '../components/Button'
import { useAuth } from '../auth/AuthContext'
import { ArrowRightIcon, CheckIcon, SpinnerIcon } from '../components/icons'
import { ApiError, runsApi, type SetupState } from '../lib/api'

/**
 * The front door. Somebody who has finished setting up wants the dashboard,
 * not a welcome page, so this only ever renders while something is missing.
 */
export function HomePage() {
  const { user } = useAuth()
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    runsApi
      .list({ limit: 1 })
      .then(({ setup: state }) => !cancelled && setSetup(state))
      .catch((err) =>
        !cancelled && setError(err instanceof ApiError ? err.message : 'Could not reach QA Agent.'),
      )
    return () => {
      cancelled = true
    }
  }, [])

  if (setup?.ready) return <Navigate to="/runs" replace />

  if (!setup) {
    return (
      <AppShell title="QA Agent">
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          {error ? (
            <span className="text-[13px] text-danger">{error}</span>
          ) : (
            <>
              <SpinnerIcon size={18} />
              <span className="text-[13px]">Loading…</span>
            </>
          )}
        </div>
      </AppShell>
    )
  }

  const steps = [
    {
      key: 'linear',
      title: 'Connect Linear',
      note: 'Where the tickets come from — description, acceptance criteria, sub-issues and comments.',
      to: '/setup/project-management',
      cta: 'Connect Linear',
      done: setup.linearConnected && setup.teamsSelected > 0,
      detail: setup.linearConnected
        ? setup.teamsSelected > 0
          ? `${setup.teamsSelected} team${setup.teamsSelected === 1 ? '' : 's'} syncing`
          : 'Connected, but no team is syncing yet'
        : '',
    },
    {
      key: 'repo',
      title: 'Connect a repository',
      note: 'Where the code comes from. A run reads the diff that implements the ticket.',
      to: '/setup/source-code',
      cta: 'Connect Azure DevOps',
      done: setup.sourceConnected && setup.repositoriesSelected > 0,
      detail: setup.sourceConnected
        ? setup.repositoriesSelected > 0
          ? `${setup.repositoriesSelected} repositor${setup.repositoriesSelected === 1 ? 'y' : 'ies'} in scope`
          : 'Connected, but no repository is in scope yet'
        : '',
    },
    {
      key: 'run',
      title: 'Run your first ticket',
      note: 'Pick a ticket and QA Agent writes the manual test cases for the change behind it.',
      to: '/tickets',
      cta: 'Pick a ticket',
      done: setup.hasRun,
      detail: '',
    },
  ]
  const next = steps.find((step) => !step.done)

  return (
    <AppShell title="QA Agent">
      <div className="flex flex-1 items-start justify-center px-5 py-10">
        <div className="w-full max-w-160">
          <p className="label-micro mb-2.5">Getting started</p>
          <h1 className="mb-2 font-display text-[28px] leading-tight font-semibold text-fg-bright">
            Welcome, {user?.displayName ?? 'there'}
          </h1>
          <p className="mb-7 text-[13.5px] text-fg-dimmer text-pretty">
            QA Agent turns a ticket and the code that implements it into manual test cases you review.
            Two connections and it is ready.
          </p>

          <ul className="mb-6 flex flex-col gap-2">
            {steps.map((step, index) => (
              <li
                key={step.key}
                className={`flex items-start gap-3.5 rounded-[10px] border px-4 py-3.5 ${
                  step.done
                    ? 'border-edge bg-ink-800'
                    : step.key === next?.key
                      ? 'border-signal-edge bg-[#121710]'
                      : 'border-edge bg-ink-800'
                }`}
              >
                <span
                  className={`mt-0.5 flex size-5.5 shrink-0 items-center justify-center rounded-full border ${
                    step.done ? 'border-signal-edge bg-signal-bg' : 'border-edge-strong'
                  }`}
                >
                  {step.done ? (
                    <CheckIcon size={11} className="text-signal" />
                  ) : (
                    <span className="font-mono text-[10px] text-fg-faint">{index + 1}</span>
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block text-[13.5px] font-medium ${step.done ? 'text-fg-dim' : 'text-fg'}`}>
                    {step.title}
                  </span>
                  <span className="block text-[12.5px] text-fg-dimmer text-pretty">{step.note}</span>
                  {step.detail && (
                    <span className="mt-1 block font-mono text-[11px] text-fg-faint">{step.detail}</span>
                  )}
                </span>
                {step.done ? (
                  <span className="shrink-0 self-center font-mono text-[11px] text-signal-dim">done</span>
                ) : (
                  <Link to={step.to} className="shrink-0 self-center no-underline">
                    <Button
                      variant={step.key === next?.key ? 'primary' : 'secondary'}
                      className="h-control-sm px-3 text-[12px]"
                      icon={<ArrowRightIcon size={13} />}
                    >
                      {step.cta}
                    </Button>
                  </Link>
                )}
              </li>
            ))}
          </ul>

          <p className="text-[12px] text-fg-faint text-pretty">
            Both connections are shared by the whole workspace, so this is done once for everybody — not
            once per person.
          </p>
        </div>
      </div>
    </AppShell>
  )
}
