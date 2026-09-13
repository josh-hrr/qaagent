import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { authApi, type User } from '../lib/api'
import { AuthContext, type AuthState } from './AuthContext'

/**
 * Restores the session on boot by asking the server who we are.
 *
 * The session lives in an httpOnly cookie, so the client cannot inspect it —
 * one request on mount is the only way to know, and it is also the only place
 * that decides between "still loading" and "signed out".
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading', user: null })

  useEffect(() => {
    let cancelled = false

    async function restore() {
      try {
        // Priming options first also sets the CSRF cookie for later POSTs.
        await authApi.options().catch(() => undefined)
        const { user } = await authApi.session()
        if (!cancelled) setState({ status: 'signedIn', user })
      } catch {
        // 401/403 is the normal "not signed in" answer; anything else (server
        // down) lands here too and is surfaced by the screens that call out.
        //
        // Never downgrade an established session: opening a magic-link URL
        // starts this check and a verify at the same time, and the verify can
        // win. Losing to a stale 403 would bounce the user straight back out.
        if (!cancelled) {
          setState((prev) => (prev.status === 'signedIn' ? prev : { status: 'signedOut', user: null }))
        }
      }
    }

    void restore()
    return () => {
      cancelled = true
    }
  }, [])

  const setUser = useCallback((user: User) => {
    setState({ status: 'signedIn', user })
  }, [])

  const signOut = useCallback(async () => {
    try {
      await authApi.signOut()
    } finally {
      setState({ status: 'signedOut', user: null })
    }
  }, [])

  const value = useMemo(() => ({ ...state, setUser, signOut }), [state, setUser, signOut])

  return <AuthContext value={value}>{children}</AuthContext>
}
