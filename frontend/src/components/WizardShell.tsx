import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { BrandMark, CheckIcon } from './icons'

export type WizardStepState = 'done' | 'current' | 'upcoming'

export type WizardStep = {
  n: string
  label: string
  state: WizardStepState
}

/** Setup steps 01–03, shared by this screen and the repository screen. */
export const SETUP_STEPS: { n: string; label: string }[] = [
  { n: '01', label: 'Project management' },
  { n: '02', label: 'Source code' },
  { n: '03', label: 'First run' },
]

export function setupSteps(currentIndex: number): WizardStep[] {
  return SETUP_STEPS.map((step, i) => ({
    ...step,
    state: i < currentIndex ? 'done' : i === currentIndex ? 'current' : 'upcoming',
  }))
}

/**
 * Chrome for the onboarding flow: step rail on top, sticky action bar at the
 * bottom, scrolling content between. Keeps the two setup screens identical
 * without either owning the layout.
 */
export function WizardShell({
  steps,
  children,
  footer,
  contentWidth = 784,
}: {
  steps: WizardStep[]
  children: ReactNode
  footer: ReactNode
  /** Matches the design's column width; the repository screen is wider. */
  contentWidth?: number
}) {
  return (
    <div className="flex min-h-dvh flex-col bg-ink-900">
      <header className="flex h-15 shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-b border-edge px-6">
        <div className="flex items-center gap-2.5">
          <BrandMark size={26} />
          <span className="font-display text-sm font-bold">QA Agent</span>
        </div>
        <span className="hidden h-5 w-px bg-edge sm:block" />

        <ol className="flex items-center gap-5">
          {steps.map((step) => (
            <li key={step.n} className="flex items-center gap-2.5">
              <span
                className={`flex size-5.5 items-center justify-center rounded-[5px] border font-mono text-[10px] ${
                  step.state === 'current'
                    ? 'border-signal bg-signal text-ink-900'
                    : step.state === 'done'
                      ? 'border-signal-edge bg-signal-bg text-signal'
                      : 'border-edge-strong text-fg-faint'
                }`}
              >
                {step.state === 'done' ? <CheckIcon size={11} /> : step.n}
              </span>
              <span
                className={`hidden text-[12.5px] md:inline ${
                  step.state === 'current' ? 'font-semibold text-fg' : 'text-fg-faint'
                }`}
              >
                {step.label}
              </span>
            </li>
          ))}
        </ol>

        <div className="flex-1" />
        <Link to="/" className="font-mono text-[11px] text-fg-faint hover:text-fg-dim">
          Skip setup →
        </Link>
      </header>

      <div className="flex flex-1 justify-center overflow-y-auto px-6 py-9">
        <div className="w-full" style={{ maxWidth: contentWidth }}>
          {children}
        </div>
      </div>

      <footer className="shrink-0 border-t border-edge bg-ink-900 px-6 py-4">
        <div className="mx-auto w-full" style={{ maxWidth: contentWidth }}>
          {footer}
        </div>
      </footer>
    </div>
  )
}
