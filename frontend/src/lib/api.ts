/**
 * Thin fetch wrapper for the Django API.
 *
 * Auth is an httpOnly session cookie, so nothing here reads or stores a token.
 * The only cookie JavaScript touches is the CSRF one, which Django expects
 * echoed back in a header on unsafe methods.
 */

// Production adds the browser-enforced __Host- prefix (Secure, no Domain,
// Path=/), which development cannot use because there is no TLS. Try both so
// the same bundle works against either backend.
const CSRF_COOKIE_NAMES = ['__Host-qaagent_csrftoken', 'qaagent_csrftoken']
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

export type FieldErrors = Record<string, string[]>

export class ApiError extends Error {
  readonly status: number
  /** Machine-readable code from the backend, e.g. `rate_limited`. */
  readonly code?: string
  /** Per-field validation messages from DRF serializers. */
  readonly fieldErrors: FieldErrors

  constructor(
    message: string,
    options: { status: number; code?: string; fieldErrors?: FieldErrors },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.fieldErrors = options.fieldErrors ?? {}
  }

  /** True when the request failed before reaching the server at all. */
  get isOffline(): boolean {
    return this.status === 0
  }

  /** First message for a field, if the backend rejected one. */
  fieldError(field: string): string | undefined {
    return this.fieldErrors[field]?.[0]
  }
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length))
  }
  return null
}

function readCsrfToken(): string | null {
  for (const name of CSRF_COOKIE_NAMES) {
    const value = readCookie(name)
    if (value) return value
  }
  return null
}

type ErrorBody = {
  detail?: unknown
  code?: unknown
  [key: string]: unknown
}

function parseErrorBody(body: ErrorBody, status: number): ApiError {
  const code = typeof body.code === 'string' ? body.code : undefined

  // DRF puts field errors at the top level next to `detail`.
  const fieldErrors: FieldErrors = {}
  for (const [key, value] of Object.entries(body)) {
    if (key === 'detail' || key === 'code') continue
    if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
      fieldErrors[key] = value
    }
  }

  const detail = typeof body.detail === 'string' ? body.detail : undefined
  const firstFieldError = Object.values(fieldErrors)[0]?.[0]
  const message = detail ?? firstFieldError ?? `Request failed (${status}).`

  return new ApiError(message, { status, code, fieldErrors })
}

let csrfPriming: Promise<unknown> | null = null

/**
 * Guarantee a CSRF cookie before an unsafe request.
 *
 * The backend enforces CSRF on the sign-in endpoints even while signed out, and
 * `/auth/options/` is what sets the cookie. Priming here rather than at a call
 * site removes the ordering hazard — a magic-link URL opened cold would
 * otherwise POST before anything had fetched options.
 */
async function ensureCsrfCookie(): Promise<void> {
  if (readCsrfToken()) return
  csrfPriming ??= fetch('/api/auth/options/', {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  }).finally(() => {
    csrfPriming = null
  })
  await csrfPriming.catch(() => undefined)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!SAFE_METHODS.has(method)) {
    await ensureCsrfCookie()
    const csrf = readCsrfToken()
    if (csrf) headers.set('X-CSRFToken', csrf)
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      method,
      headers,
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError('Could not reach the server. Check that the backend is running.', {
      status: 0,
      code: 'network_error',
    })
  }

  if (response.status === 204) return undefined as T

  const isJson = response.headers.get('Content-Type')?.includes('application/json')
  const body: unknown = isJson ? await response.json().catch(() => ({})) : {}

  if (!response.ok) {
    throw parseErrorBody((body ?? {}) as ErrorBody, response.status)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

/* --- auth endpoints ------------------------------------------------------ */

export type User = {
  id: number
  email: string
  fullName: string
  displayName: string
  initials: string
  jobTitle: string
  avatarUrl: string
}

export type SsoProvider = {
  key: 'microsoft' | 'google' | string
  label: string
  /** False when the backend has no client id/secret for it yet. */
  configured: boolean
}

export type SignInOptions = {
  providers: SsoProvider[]
  magicLinkEnabled: boolean
  allowedEmailDomains: string[]
  magicLinkTtlMinutes: number
}

/* --- connections ---------------------------------------------------------- */

export type LinearTeam = {
  linear_id: string
  key: string
  name: string
  selected: boolean
}

export type Repository = {
  externalId: string
  name: string
  projectName: string
  defaultBranch: string
  webUrl: string
  sizeBytes: number | null
  selected: boolean
  /** Empty until the run pipeline has actually cloned it. */
  lastIndexedCommit: string
  isIndexed: boolean
}

/** How a ticket is mapped to the code change that implements it. */
export type DiffScopeStrategy = 'linked_pr' | 'branch_name' | 'manual'

export type Connection = {
  provider: string
  authMethod: string
  /** A stub like `lin_api_...7Kd2`. The credential itself never leaves the server. */
  credentialHint: string
  status: 'connected' | 'error'
  accountName: string
  accountEmail: string
  organizationName: string
  organizationRef: string
  diffScopeStrategy: DiffScopeStrategy
  lastVerifiedAt: string | null
  lastError: string
  connectedBy: string
  teams: LinearTeam[]
  repositories: Repository[]
}

export type ConnectionsResponse = {
  connections: Connection[]
  linearOAuthConfigured: boolean
  githubConfigured: boolean
}

export type AzureVerifyResponse = {
  account: { displayName: string; email: string; organization: string }
  repositories: Repository[]
}

export type LinearVerifyResponse = {
  account: { name: string; email: string; organizationName: string }
  teams: LinearTeam[]
}

export const connectionsApi = {
  list: () => api.get<ConnectionsResponse>('/connections/'),
  /** Checks the key and lists its teams. Stores nothing. */
  verifyLinear: (apiKey: string) =>
    api.post<LinearVerifyResponse>('/connections/linear/verify/', { apiKey }),
  connectLinear: (apiKey: string, teamIds: string[]) =>
    api.post<{ connection: Connection }>('/connections/linear/', { apiKey, teamIds }),
  /** Change which teams sync without re-sending the key. */
  updateLinearTeams: (teamIds: string[]) =>
    api.patch<{ connection: Connection }>('/connections/linear/teams/', { teamIds }),
  disconnectLinear: () => api.delete<void>('/connections/linear/disconnect/'),

  /** Checks the token and lists its repositories. Stores nothing. */
  verifyAzure: (organization: string, pat: string, project: string) =>
    api.post<AzureVerifyResponse>('/connections/azure/verify/', { organization, pat, project }),
  connectAzure: (input: {
    organization: string
    project: string
    pat: string
    repositoryIds: string[]
    diffScopeStrategy: DiffScopeStrategy
  }) => api.post<{ connection: Connection }>('/connections/azure/', input),
  /** Change repository selection or the diff-scope rule without the token. */
  updateAzureSettings: (input: {
    repositoryIds?: string[]
    diffScopeStrategy?: DiffScopeStrategy
  }) => api.patch<{ connection: Connection }>('/connections/azure/settings/', input),
  disconnectAzure: () => api.delete<void>('/connections/azure/disconnect/'),
}

/* --- tickets -------------------------------------------------------------- */

export type ReadinessStatus = 'ok' | 'warning' | 'blocked'

export type ReadinessCheck = {
  key: string
  label: string
  detail: string
  status: ReadinessStatus
}

export type Ticket = {
  id: string
  identifier: string
  title: string
  description: string
  url: string
  branchName: string
  updatedAt: string
  state: { name: string; type: string }
  assigneeName: string
  teamKey: string
  teamName: string
  criteria: { key: string; text: string }[]
  subIssues: { identifier: string; title: string }[]
  commentCount: number
  unresolvedCommentCount: number
  /** Deduplicated across attachments, the description and comments. */
  pullRequests: {
    provider: string
    organization: string
    project: string
    repository: string
    number: number
    url: string
    source: 'attachment' | 'description' | 'comment' | string
    /** False when the PR lives in a repository nobody has connected. */
    inConnectedRepository: boolean
  }[]
  readiness: {
    status: ReadinessStatus
    warningCount: number
    checks: ReadinessCheck[]
  }
}

export type TicketsResponse = {
  tickets: Ticket[]
  workspace: {
    organizationName: string
    teamNames: string[]
    repositoryCount: number
    diffScopeStrategy: string
    sourceConnected: boolean
  }
  fetchedAt: string
}

export const ticketsApi = {
  /** Read live from Linear — tickets change, and a stale copy would lie. */
  list: () => api.get<TicketsResponse>('/tickets/'),
}

/* --- runs ----------------------------------------------------------------- */

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type StageState = 'done' | 'running' | 'queued' | 'failed' | 'cancelled' | 'skipped'

export type RunSummary = {
  id: number
  ticketIdentifier: string
  ticketTitle: string
  ticketUrl: string
  status: RunStatus
  stage: string
  stages: { key: string; label: string; state: StageState }[]
  errorCode: string
  errorMessage: string
  model: string
  costUsd: string
  costCapUsd: string
  stoppedEarly: boolean
  stoppedEarlyReason: string
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  isTerminal: boolean
  counts: { testCases: number; findings: number; ambiguities: number; filesRead: number }
}

export type RunDetail = RunSummary & {
  snapshotHash: string
  pullRequests: { url: string; repository: string; number: number; title: string; status: string }[]
  skippedPullRequests: { url: string; reason: string }[]
  tokens: { input: number; output: number; cacheRead: number; cacheWrite: number }
  events: { stage: string; message: string; at: string }[]
  filesRead: {
    repository: string
    path: string
    source: 'diff' | 'agent'
    reason: string
    changeType: string
    linesAdded: number
    linesRemoved: number
  }[]
}

export const runsApi = {
  /** Only the ticket id is sent; the server re-reads the ticket from Linear. */
  start: (ticketId: string, identifier: string) =>
    api.post<{ run: RunSummary; existing: boolean }>('/runs/start/', { ticketId, identifier }),
  get: (runId: number | string) => api.get<{ run: RunDetail }>(`/runs/${runId}/`),
  cancel: (runId: number | string) => api.post<{ run: RunSummary }>(`/runs/${runId}/cancel/`),
}

export const authApi = {
  /** Also primes the CSRF cookie, so call it before any POST. */
  options: () => api.get<SignInOptions>('/auth/options/'),
  session: () => api.get<{ user: User }>('/auth/session/'),
  requestMagicLink: (email: string) =>
    api.post<{ detail: string; expiresInMinutes: number }>('/auth/magic-link/', { email }),
  verifyMagicLink: (token: string) =>
    api.post<{ user: User }>('/auth/magic-link/verify/', { token }),
  signOut: () => api.post<void>('/auth/sign-out/'),
  ssoStartUrl: (provider: string) => `/api/auth/sso/${provider}/start/`,
}
