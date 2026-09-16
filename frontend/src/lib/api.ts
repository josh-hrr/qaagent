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
  /** Last export choices, so the dialog opens where this user left it. */
  exportPreferences: Partial<ExportSettings> | null
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
  /** Empty until a run has read this repository. */
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
  /** Ask Linear whether the stored key still works, and refresh the teams. */
  reverifyLinear: () =>
    api.post<{ connection: Connection; detail?: string; code?: string }>('/connections/linear/reverify/'),
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
  /** Ask Azure whether the stored token still works, and refresh the repositories. */
  reverifyAzure: () =>
    api.post<{ connection: Connection; detail?: string; code?: string }>('/connections/azure/reverify/'),
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
  createdBy: string
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  isTerminal: boolean
  counts: {
    testCases: number
    findings: number
    ambiguities: number
    filesRead: number
    criteriaTotal: number
    /** Null until test cases exist — unknown mid-run, not zero. */
    criteriaCovered: number | null
  }
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

/** What the workspace has spent this calendar month, against its cap. */
export type Spend = {
  spentUsd: string
  capUsd: string
  runCount: number
  model: string
  capReached: boolean
}

export type RunListParams = {
  status?: RunStatus | ''
  q?: string
  ticketId?: string
  limit?: number
  offset?: number
}

export type RunListResponse = {
  runs: RunSummary[]
  total: number
  offset: number
  /** Counts over the whole list, not the page — the filter chips show these. */
  counts: Record<string, number>
  activeCount: number
  spend: Spend
}

export const runsApi = {
  /** Only the ticket id is sent; the server re-reads the ticket from Linear.
   *  `excludePullRequests` carries links the user unticked on the ticket screen. */
  start: (ticketId: string, identifier: string, excludePullRequests: string[] = []) =>
    api.post<{ run: RunSummary; existing: boolean }>('/runs/start/', {
      ticketId,
      identifier,
      excludePullRequests,
    }),
  get: (runId: number | string) => api.get<{ run: RunDetail }>(`/runs/${runId}/`),
  list: (params: RunListParams = {}) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    const suffix = query.toString()
    return api.get<RunListResponse>(`/runs/${suffix ? `?${suffix}` : ''}`)
  },
  cancel: (runId: number | string) => api.post<{ run: RunSummary }>(`/runs/${runId}/cancel/`),
}

/* --- review (screen 06) --------------------------------------------------- */

export type Priority = 'P1' | 'P2' | 'P3'
export type TestCaseStatus = 'draft' | 'ready' | 'needs_info' | 'approved' | 'rejected'

export type Trace = {
  label: string
  kind: 'criterion' | 'code'
  /** The criterion's text, for criteria. */
  text: string
  /** Azure DevOps link pinned to the run's commit, for code. Empty when unknown. */
  url: string
}

export type ReviewTestCase = {
  number: number
  identifier: string
  title: string
  description: string
  preconditions: string
  steps: string[]
  expectedResult: string
  actualResult: string
  priority: Priority
  testType: string
  status: TestCaseStatus
  suite: string
  estimateMinutes: number | null
  origin: 'generated' | 'finding' | 'manual' | string
  edited: boolean
  reviewedBy: string | null
  tracesTo: Trace[]
}

export type ReviewFinding = {
  id: number
  severity: 'high' | 'medium' | 'low'
  title: string
  explanation: string
  location: string
  locationUrl: string
  dismissed: boolean
  testCaseNumber: number | null
}

export type ReviewAmbiguity = {
  id: number
  kind: string
  question: string
  explanation: string
  source: string
  blocksTestCases: number[]
  answer: string
  answeredBy: string | null
  answeredAt: string | null
}

export type ReviewRun = {
  id: number
  runNumber: number
  status: RunStatus
  ticketIdentifier: string
  ticketTitle: string
  ticketUrl: string
  ticketLinearId: string
  teamName: string
  createdAt: string
  finishedAt: string | null
  costUsd: string
  model: string
  stoppedEarly: boolean
  stoppedEarlyReason: string
  scope: {
    kind: 'pull_request' | 'branch'
    repository: string
    sourceRef: string
    targetRef: string
    headCommit: string
    baseCommit: string
    number: number | null
    url: string
  } | null
  diff: { files: number; linesAdded: number; linesRemoved: number }
  criteria: { key: string; text: string }[]
  criteriaTotal: number
  criteriaCovered: number | null
}

export type ExportRecord = {
  id: number
  filename: string
  fileFormat: FileFormat
  scope: ExportScope
  caseCount: number
  byteSize: number
  exportedBy: string | null
  createdAt: string
}

export type ReviewResponse = {
  run: ReviewRun
  testCases: ReviewTestCase[]
  findings: ReviewFinding[]
  ambiguities: ReviewAmbiguity[]
  /** Most recent downloads of this run, newest first. */
  exports: ExportRecord[]
}

export type TicketDrift =
  | { error: string }
  | {
      changed: boolean
      updatedAt: string
      titleChanged: boolean
      descriptionChanged: boolean
      criteriaAdded: string[]
      criteriaRemoved: string[]
      criteriaEdited: string[]
      pullRequestsAdded: string[]
      pullRequestsRemoved: string[]
    }

export type CodeDrift =
  | { label?: string; error: string }
  | { label: string; headCommit: string; commitsAhead: number; status: string }

export type DriftResponse = { ticket: TicketDrift | null; code: CodeDrift[]; checkedAt: string }

export type TestCaseUpdate = Partial<{
  title: string
  description: string
  preconditions: string
  steps: string[]
  expectedResult: string
  actualResult: string
  priority: Priority
  status: TestCaseStatus
  testType: string
  suite: string
  estimateMinutes: number | null
}>

export type BulkAction =
  | { action: 'set_priority'; value: Priority }
  | { action: 'set_status'; value: TestCaseStatus }
  | { action: 'delete' }

export const reviewApi = {
  get: (runId: number | string) => api.get<ReviewResponse>(`/runs/${runId}/review/`),
  /** Asks Linear and Azure DevOps what changed since the run. Call on open and on request only. */
  drift: (runId: number | string) => api.get<DriftResponse>(`/runs/${runId}/drift/`),
  updateTestCase: (runId: number, number: number, changes: TestCaseUpdate) =>
    api.patch<{ testCase: ReviewTestCase }>(`/runs/${runId}/test-cases/${number}/`, changes),
  bulk: (runId: number, numbers: number[], action: BulkAction) =>
    api.post<ReviewResponse & { updated: number }>(`/runs/${runId}/test-cases/bulk/`, { numbers, ...action }),
  findingToTestCase: (runId: number, findingId: number) =>
    api.post<ReviewResponse & { testCase: ReviewTestCase }>(`/runs/${runId}/findings/${findingId}/test-case/`),
  dismissFinding: (runId: number, findingId: number, dismissed: boolean) =>
    api.post<{ finding: ReviewFinding }>(`/runs/${runId}/findings/${findingId}/dismiss/`, { dismissed }),
  answer: (runId: number, ambiguityId: number, answer: string) =>
    api.post<{ ambiguity: ReviewAmbiguity }>(`/runs/${runId}/ambiguities/${ambiguityId}/answer/`, { answer }),
}

/* --- export (screen 07) ---------------------------------------------------- */

export type FileFormat = 'csv' | 'md'
export type MarkdownLayout = 'table' | 'sections'
export type ExportScope = 'all' | 'selected' | 'approved'

export type ExportSettings = {
  fileFormat: FileFormat
  layout: MarkdownLayout
  scope: ExportScope
  columns: string[]
  caseNumbers: number[]
  numberedSteps: boolean
  blankActual: boolean
  runHeader: boolean
}

export type ExportColumn = { key: string; header: string; required: boolean }

export type ExportPreview = {
  preview: string
  filename: string
  byteSize: number
  caseCount: number
  counts: { all: number; approved: number; rejectedExcluded: number }
  columns: ExportColumn[]
}

function exportQuery(settings: ExportSettings): string {
  return new URLSearchParams({
    fileFormat: settings.fileFormat,
    layout: settings.layout,
    scope: settings.scope,
    columns: settings.columns.join(','),
    caseNumbers: settings.caseNumbers.join(','),
    numberedSteps: settings.numberedSteps ? '1' : '0',
    blankActual: settings.blankActual ? '1' : '0',
    runHeader: settings.runHeader ? '1' : '0',
  }).toString()
}

/** Reads the name the server chose, so the saved file matches the preview. */
function filenameFrom(header: string | null, fallback: string): string {
  const match = header?.match(/filename="([^"]+)"/)
  return match ? match[1] : fallback
}

export const exportApi = {
  preview: (runId: number | string, settings: ExportSettings) =>
    api.get<ExportPreview>(`/runs/${runId}/export/preview/?${exportQuery(settings)}`),

  /** Fetches the bytes, then hands them to the browser as a save. */
  download: async (runId: number | string, settings: ExportSettings, fallbackName: string) => {
    const response = await fetch(`/api/runs/${runId}/export/download/?${exportQuery(settings)}`, {
      credentials: 'same-origin',
    })
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => ({}))
      throw parseErrorBody((body ?? {}) as ErrorBody, response.status)
    }
    const name = filenameFrom(response.headers.get('Content-Disposition'), fallbackName)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = name
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    // Freed on the next tick: revoking immediately cancels the save in Safari.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    return { filename: name, byteSize: blob.size }
  },
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
