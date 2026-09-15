import { createContext, use } from 'react'

import type { User } from '../lib/api'

export type AuthState =
  | { status: 'loading'; user: null }
  | { status: 'signedIn'; user: User }
  | { status: 'signedOut'; user: null }

export type AuthContextValue = AuthState & {
  /** Record a user returned by a sign-in call. */
  setUser: (user: User) => void
  /** Re-read the user after the server changed something on it. */
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = use(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.')
  return value
}
