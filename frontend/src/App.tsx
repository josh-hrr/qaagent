import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'

import { AuthProvider } from './auth/AuthProvider'
import { useAuth } from './auth/AuthContext'
import { SpinnerIcon } from './components/icons'
import { ConnectionsPage } from './routes/ConnectionsPage'
import { ConnectProjectManagementPage } from './routes/ConnectProjectManagementPage'
import { ConnectRepositoryPage } from './routes/ConnectRepositoryPage'
import { HomePage } from './routes/HomePage'
import { MagicLinkPage } from './routes/MagicLinkPage'
import { RepositoriesPage } from './routes/RepositoriesPage'
import { ReviewWorkspacePage } from './routes/ReviewWorkspacePage'
import { RunProgressPage } from './routes/RunProgressPage'
import { RunsListPage } from './routes/RunsListPage'
import { SignInPage } from './routes/SignInPage'
import { TicketPickerPage } from './routes/TicketPickerPage'

function BootSplash() {
  return (
    <div className="flex min-h-dvh items-center justify-center text-fg-faint">
      <SpinnerIcon size={22} />
      <span className="sr-only">Loading</span>
    </div>
  )
}

function RequireAuth({ children }: { children: ReactElement }) {
  const { status } = useAuth()
  if (status === 'loading') return <BootSplash />
  if (status === 'signedOut') return <Navigate to="/sign-in" replace />
  return children
}

function RedirectIfSignedIn({ children }: { children: ReactElement }) {
  const { status } = useAuth()
  if (status === 'loading') return <BootSplash />
  if (status === 'signedIn') return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path="/sign-in"
            element={
              <RedirectIfSignedIn>
                <SignInPage />
              </RedirectIfSignedIn>
            }
          />
          <Route path="/auth/magic-link" element={<MagicLinkPage />} />
          <Route
            path="/setup/project-management"
            element={
              <RequireAuth>
                <ConnectProjectManagementPage />
              </RequireAuth>
            }
          />
          <Route
            path="/setup/source-code"
            element={
              <RequireAuth>
                <ConnectRepositoryPage />
              </RequireAuth>
            }
          />
          <Route
            path="/tickets"
            element={
              <RequireAuth>
                <TicketPickerPage />
              </RequireAuth>
            }
          />
          <Route
            path="/repositories"
            element={
              <RequireAuth>
                <RepositoriesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/connections"
            element={
              <RequireAuth>
                <ConnectionsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs"
            element={
              <RequireAuth>
                <RunsListPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:runId"
            element={
              <RequireAuth>
                <RunProgressPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:runId/review"
            element={
              <RequireAuth>
                <ReviewWorkspacePage />
              </RequireAuth>
            }
          />
          <Route
            path="/"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
