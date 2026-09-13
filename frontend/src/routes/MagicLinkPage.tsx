import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'

import { Button } from '../components/Button'
import { AlertIcon, BrandMark, SpinnerIcon } from '../components/icons'
import { useAuth } from '../auth/AuthContext'
import { ApiError, authApi } from '../lib/api'

/** Human wording for each refusal the backend can return. */
const MESSAGES: Record<string, { title: string; body: string }> = {
  expired: {
    title: 'This link has expired',
    body: 'Sign-in links are short-lived on purpose. Request a fresh one — it only takes a moment.',
  },
  already_used: {
    title: 'This link has already been used',
    body: 'Each link works exactly once. If you did not just sign in somewhere, request a new link and tell your admin.',
  },
  invalid: {
    title: 'This link is not valid',
    body: 'It may have been cut short by your email client. Request a new one and open it in a single click.',
  },
  domain_not_allowed: {
    title: 'That address cannot sign in',
    body: 'This workspace only accepts company accounts. Ask an admin if you think that is wrong.',
  },
  inactive: {
    title: 'This account is deactivated',
    body: 'An admin needs to reactivate it before you can sign in.',
  },
}

const FALLBACK = {
  title: 'Could not sign you in',
  body: 'Something went wrong while checking the link. Request a new one and try again.',
}

export function MagicLinkPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { setUser, status } = useAuth()

  const token = params.get('token')
  const [error, setError] = useState<{ title: string; body: string } | null>(null)
  // Guards the double-invoke of effects under StrictMode: the token is single
  // use, so a second verify would fail with `already_used`.
  const attempted = useRef(false)

  useEffect(() => {
    if (!token || attempted.current) return
    attempted.current = true

    authApi
      .verifyMagicLink(token)
      .then(({ user }) => {
        setUser(user)
        navigate('/', { replace: true })
      })
      .catch((err: unknown) => {
        const code = err instanceof ApiError ? err.code : undefined
        setError((code && MESSAGES[code]) || FALLBACK)
      })
  }, [token, setUser, navigate])

  if (!token) return <Navigate to="/sign-in" replace />
  if (status === 'signedIn') return <Navigate to="/" replace />

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-5">
      <div className="w-full max-w-[400px] text-center">
        <div className="mb-7 flex justify-center">
          <BrandMark size={34} />
        </div>

        {error ? (
          <>
            <div className="mx-auto mb-5 flex size-11 items-center justify-center rounded-full border border-danger-edge bg-danger-bg text-danger">
              <AlertIcon size={20} />
            </div>
            <h1 className="mb-2 font-display text-[22px] font-semibold text-fg-bright">
              {error.title}
            </h1>
            <p className="mb-7 text-[13.5px] text-fg-dimmer text-pretty">{error.body}</p>
            <Button variant="primary" size="lg" block onClick={() => navigate('/sign-in')}>
              Request a new link
            </Button>
          </>
        ) : (
          <>
            <div className="mx-auto mb-5 flex size-11 items-center justify-center rounded-full border border-edge-strong text-signal">
              <SpinnerIcon size={20} />
            </div>
            <h1 className="mb-2 font-display text-[22px] font-semibold text-fg-bright">
              Signing you in
            </h1>
            <p className="text-[13.5px] text-fg-dimmer">Checking your link…</p>
          </>
        )}
      </div>
    </main>
  )
}
