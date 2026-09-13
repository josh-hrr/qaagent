import { useEffect, useRef, useState, type FormEvent } from 'react'

import { BrandPanel } from '../components/BrandPanel'
import { Button, ButtonLink } from '../components/Button'
import { Field } from '../components/Field'
import { AlertIcon, LockIcon, MailIcon, providerMarks } from '../components/icons'
import { ApiError, authApi, type SignInOptions } from '../lib/api'

const RESEND_COOLDOWN_SECONDS = 30

export function SignInPage() {
  const [options, setOptions] = useState<SignInOptions | null>(null)
  const [optionsFailed, setOptionsFailed] = useState(false)

  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    let cancelled = false
    authApi
      .options()
      .then((value) => !cancelled && setOptions(value))
      .catch(() => !cancelled && setOptionsFailed(true))
    return () => {
      cancelled = true
    }
  }, [])

  // Resend cooldown, so an impatient click cannot burn the hourly rate limit.
  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((n) => n - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const configuredProviders = options?.providers.filter((p) => p.configured) ?? []
  const unconfiguredProviders = options?.providers.filter((p) => !p.configured) ?? []
  // With no SSO wired up yet, the email form is the only thing that works — so
  // it becomes the primary action instead of leaving a dead button on top.
  const emailIsPrimary = options !== null && configuredProviders.length === 0

  async function submit(event: FormEvent) {
    event.preventDefault()
    const address = email.trim()
    if (!address || submitting) return

    setSubmitting(true)
    setError(null)
    try {
      await authApi.requestMagicLink(address)
      setSentTo(address)
      setCooldown(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Something went wrong.', { status: 0 }))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-dvh">
      <BrandPanel />

      <div className="flex flex-1 flex-col items-center justify-center border-l border-edge bg-ink-800 px-5 py-10 sm:px-10">
        <div className="w-full max-w-[384px]">
          {sentTo ? (
            <LinkSentPanel
              email={sentTo}
              ttlMinutes={options?.magicLinkTtlMinutes ?? 15}
              cooldown={cooldown}
              resending={submitting}
              error={error}
              onResend={submit}
              onUseAnotherAddress={() => {
                setSentTo(null)
                setError(null)
              }}
            />
          ) : (
            <>
              <h2 className="mb-1.5 font-display text-[26px] leading-tight font-semibold text-fg-bright">
                Sign in
              </h2>
              <p className="mb-7 text-[13.5px] text-fg-dimmer">
                Use the account you already use for Azure DevOps.
              </p>

              {optionsFailed && (
                <Callout tone="danger" className="mb-5">
                  Could not reach the API. Start the backend with{' '}
                  <code className="font-mono text-fg-muted">python manage.py runserver</code> and
                  reload.
                </Callout>
              )}

              {configuredProviders.map((provider, index) => {
                const Mark = providerMarks[provider.key]
                return (
                  <ButtonLink
                    key={provider.key}
                    href={authApi.ssoStartUrl(provider.key)}
                    size="lg"
                    block
                    variant={index === 0 ? 'primary' : 'secondary'}
                    icon={Mark ? <Mark size={16} /> : undefined}
                    className="mb-2.5"
                  >
                    Continue with {provider.label}
                  </ButtonLink>
                )
              })}

              {configuredProviders.length > 0 && <Divider className="my-5.5" />}

              <form onSubmit={submit} noValidate>
                <Field
                  label="Work email"
                  type="email"
                  name="email"
                  autoComplete="email"
                  placeholder="you@yourcompany.com"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    if (error) setError(null)
                  }}
                  disabled={submitting}
                  error={error?.fieldError('email') ?? undefined}
                  hint={
                    options?.allowedEmailDomains.length
                      ? `Accounts on ${formatDomains(options.allowedEmailDomains)} only.`
                      : undefined
                  }
                  required
                />

                {error && !error.fieldError('email') && (
                  <Callout tone="danger" className="mt-3">
                    {error.message}
                  </Callout>
                )}

                <Button
                  type="submit"
                  size="lg"
                  block
                  variant={emailIsPrimary ? 'primary' : 'secondary'}
                  busy={submitting}
                  disabled={!email.trim()}
                  icon={emailIsPrimary ? <MailIcon size={16} /> : undefined}
                  className="mt-3"
                >
                  {submitting ? 'Sending…' : 'Send sign-in link'}
                </Button>
              </form>

              {unconfiguredProviders.length > 0 && (
                <>
                  <Divider className="my-5.5" />
                  <ul className="space-y-2">
                    {unconfiguredProviders.map((provider) => {
                      const Mark = providerMarks[provider.key]
                      return (
                        <li
                          key={provider.key}
                          className="flex h-control-lg items-center gap-2.5 rounded-[7px] border border-edge px-3 text-fg-faint"
                        >
                          {Mark && <Mark size={16} />}
                          <span className="flex-1 text-[13px]">
                            Continue with {provider.label}
                          </span>
                          <span className="rounded-[3px] border border-edge-strong px-1.5 py-0.5 font-mono text-[9.5px] tracking-[0.06em]">
                            NOT CONFIGURED
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                  <p className="mt-2.5 text-[11.5px] text-fg-faint">
                    Add the client id and secret to{' '}
                    <code className="font-mono text-fg-dimmer">backend/.env</code> to turn these on.
                  </p>
                </>
              )}

              <SecurityNote />
            </>
          )}
        </div>
      </div>
    </main>
  )
}

/* --- sub-views ----------------------------------------------------------- */

function LinkSentPanel({
  email,
  ttlMinutes,
  cooldown,
  resending,
  error,
  onResend,
  onUseAnotherAddress,
}: {
  email: string
  ttlMinutes: number
  cooldown: number
  resending: boolean
  error: ApiError | null
  onResend: (event: FormEvent) => void
  onUseAnotherAddress: () => void
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)

  // Move focus to the confirmation so a screen reader announces the change.
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  return (
    <div>
      <div className="mb-5 flex size-11 items-center justify-center rounded-full border border-signal-edge bg-signal-bg text-signal">
        <MailIcon size={20} />
      </div>

      <h2
        ref={headingRef}
        tabIndex={-1}
        className="mb-1.5 font-display text-[26px] leading-tight font-semibold text-fg-bright outline-none"
      >
        Check your inbox
      </h2>
      <p className="mb-7 text-[13.5px] text-fg-dimmer text-pretty">
        If <span className="font-mono text-fg-muted">{email}</span> can sign in, a link is on its
        way. It works once and expires in {ttlMinutes} minutes.
      </p>

      {error && (
        <Callout tone="danger" className="mb-4">
          {error.message}
        </Callout>
      )}

      <Button
        size="lg"
        block
        variant="secondary"
        busy={resending}
        disabled={cooldown > 0}
        onClick={onResend}
      >
        {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend the link'}
      </Button>

      <button
        type="button"
        onClick={onUseAnotherAddress}
        className="mt-3 w-full cursor-pointer text-center text-[12.5px] text-fg-dimmer transition-colors hover:text-fg-muted"
      >
        Use a different address
      </button>

      <Callout tone="neutral" className="mt-7" icon={<MailIcon size={14} />}>
        No email in development? The link is printed in the Django console that runs{' '}
        <code className="font-mono text-fg-dimmer">runserver</code>.
      </Callout>
    </div>
  )
}

function SecurityNote() {
  return (
    <div className="mt-6 flex gap-2.5 rounded-[7px] border border-edge bg-ink-700 px-3 py-3">
      <LockIcon size={14} className="mt-0.5 shrink-0 text-fg-faint" />
      <p className="text-[12px] text-fg-dimmer text-pretty">
        Repository and ticket credentials are stored per workspace, never per user. Cloned source is
        deleted when the run finishes.
      </p>
    </div>
  )
}

function Divider({ className }: { className?: string }) {
  return (
    <div className={`flex items-center gap-3 ${className ?? ''}`}>
      <span className="h-px flex-1 bg-edge" />
      <span className="font-mono text-[10px] tracking-[0.1em] text-fg-faint">OR</span>
      <span className="h-px flex-1 bg-edge" />
    </div>
  )
}

function Callout({
  tone,
  icon,
  className,
  children,
}: {
  tone: 'danger' | 'neutral'
  icon?: React.ReactNode
  className?: string
  children: React.ReactNode
}) {
  const tones = {
    danger: 'border-danger-edge bg-danger-bg text-danger',
    neutral: 'border-edge bg-ink-700 text-fg-dimmer',
  }
  return (
    <div
      role={tone === 'danger' ? 'alert' : undefined}
      className={`flex gap-2.5 rounded-[7px] border px-3 py-2.5 text-[12px] text-pretty ${tones[tone]} ${className ?? ''}`}
    >
      <span className="mt-px shrink-0">{icon ?? (tone === 'danger' ? <AlertIcon size={14} /> : null)}</span>
      <span className={tone === 'danger' ? 'text-fg-muted' : ''}>{children}</span>
    </div>
  )
}

function formatDomains(domains: string[]): string {
  if (domains.length === 1) return `@${domains[0]}`
  return domains.map((d) => `@${d}`).join(', ')
}
