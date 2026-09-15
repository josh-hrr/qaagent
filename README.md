# QA Agent

Internal tool that turns a Linear ticket **and the code diff that implements it**
into reviewed manual test cases — flagging code it doesn't trust and requirements
it can't pin down.

```
backend/    Django 6 + DRF API
frontend/   React 19 + TypeScript + Tailwind 4 (Vite)
design/     Design canvas — 11 screens of the Phase 1 flow
docs/       Notes, starting with the original brief
```

## Running it

Three terminals: backend, frontend, and the worker. The Vite dev server proxies `/api` to Django, so both apps share
an origin and the session cookie behaves exactly as it will in production.

**Backend** — http://127.0.0.1:8000

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

**Frontend** — http://localhost:5173

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and you land on the sign-in screen.

**Worker** — needed for test case generation (screen 05)

```bash
cd backend
.venv/Scripts/activate
python manage.py db_worker
```

Generation runs in this separate process, never inside a web request. Without
it, a run sits at *queued*. It also needs `ANTHROPIC_API_KEY` in `backend/.env`.

## Signing in during development

No SMTP server is needed. The quickest way in — skips email entirely and prints
one clean line:

```bash
cd backend
python manage.py signin_link you@yourcompany.com
```

Open the URL it prints. The account is created on first successful sign-in. The
command refuses to run unless `DJANGO_DEBUG=true`, so it can never become a back
door on a real deployment.

The full flow works too: type any address on the sign-in screen and
`EMAIL_URL=consolemail://` prints the email to the Django console. Note the URL
there is quoted-printable encoded and wraps across lines — `=` becomes `=3D` and
a trailing `=` is a soft line break — so join the pieces before opening it. Point
`EMAIL_URL` at a catcher like Mailpit to avoid that.

## Current state

| # | Screen | Status |
|---|--------|--------|
| 01 | Sign in | **built** — frontend + API + tests |
| 02 | Connect Linear | **built** — `/setup/project-management` |
| 03 | Connect repository | **built** — `/setup/source-code` |
| 04 | Pick a ticket | **built** — `/tickets` |
| 05 | Generation run | **built** — `/runs/:id` |
| 06 | Review workspace | **built** — `/runs/:id/review` |
| 07 | Export CSV / Markdown | designed |

Screens 02–07 and the empty/error states live in the design canvas
(`design/qa-agent-phase-1.html`, or the hosted version). Build order follows the
numbering.

## How auth works

An **httpOnly session cookie**, not a token in JavaScript. Chosen because this is
an internal tool that will sit behind SSO: the SSO callbacks land on Django and
can establish the session directly, and nothing sensitive is reachable from page
scripts.

- `GET  /api/auth/options/` — which sign-in methods work, plus the CSRF cookie
- `POST /api/auth/magic-link/` — request a link
- `POST /api/auth/magic-link/verify/` — exchange the link for a session
- `GET  /api/auth/session/` — the signed-in user, or 403
- `POST /api/auth/sign-out/`
- `GET  /api/auth/sso/<provider>/start/` — 501 until credentials are configured

Worth knowing:

- Magic-link tokens are stored **hashed**. The raw value exists only in the
  email, works once, and expires in 15 minutes. Requesting a new link
  invalidates the previous one.
- `POST /magic-link/` answers identically for known and unknown addresses, so it
  cannot be used to enumerate the team.
- Rate limited per address and per IP, counted from the token table so a restart
  does not reset it.
- CSRF is enforced on the unauthenticated sign-in POSTs. DRF marks `@api_view`
  handlers `csrf_exempt` and only re-checks CSRF inside `SessionAuthentication`,
  which never runs without a session — leaving login CSRF open by default. See
  `accounts/permissions.py`.
- The sign-in screen renders from `/options/`: with no SSO configured, the email
  form becomes the primary action instead of leaving a dead button on top. Add a
  client id and secret to `backend/.env` and the provider button turns on.

## Connecting Linear (screen 02)

`/setup/project-management`. Paste a Linear personal API key (Linear → Settings →
Security & access → Personal API keys), pick which teams to sync, connect.

Check a key against real Linear without touching the app:

```bash
cd backend
python manage.py linear_check lin_api_xxx
```

How it is put together:

- **Verify and connect are separate calls.** Verify checks the key and lists its
  teams while storing nothing, so you choose teams from your real workspace and a
  typo never leaves a broken row behind. Connect re-verifies, because the two
  requests are minutes apart and a key can be revoked in between.
- **One connection per provider, shared by the team** — matching "stored per
  workspace, never per user". Revoking happens in one place. Add a `workspace`
  foreign key if this ever needs to be multi-tenant.
- **Teams are rows, not a list of ids**, so the ticket picker in screen 04 can
  join against names and keys without another Linear round trip.
- The GraphQL queries request only fields the code reads. Ticket-level fields
  arrive in screen 04, against a schema verifiable with a real key by then.

### Credential storage

The Linear key is a live credential for someone else's system — a leak hands an
attacker your ticket tracker, not just this app.

- **Encrypted at rest** with Fernet (`connections/crypto.py`) before it touches
  the database.
- **Keyed on `CREDENTIAL_ENCRYPTION_KEY`, not `SECRET_KEY`.** Deliberate:
  rotating `SECRET_KEY` is the break-glass that signs everyone out, and it must
  not also render every stored credential unreadable. Generate one with
  `python manage.py generate_encryption_key`; required outside development.
- **Write-only from the client's side.** The serializer has no field for it, so
  it cannot leak by someone adding one carelessly later. The API returns only a
  stub like `lin_api_...7Kd2`. You can replace the key, never read it back.
- The Django admin excludes the field entirely — no reason for a live
  third-party credential to travel to a browser page.

## Connecting a repository (screen 03)

`/setup/source-code`. Organisation, optional project, personal access token
(read-only Code + Work Items scopes), pick repositories, choose the diff-scope
rule.

Check a token against real Azure DevOps without touching the app:

```bash
cd backend
python manage.py azure_check yourcompany --pat xxx
python manage.py azure_check yourcompany --project "Core Platform" --pat xxx
```

**Diff scope is the decision that matters.** A ticket has no code scope until
something maps it to a diff, and getting it wrong means every test case is
generated against the wrong code. The rule is explicit rather than guessed:
linked PR first, then a branch carrying the ticket ID, then ask. Stored per
connection, because a GitHub org and an Azure org may genuinely differ in
whether their teams open pull requests before asking for tests.

**Nothing is cloned — at connect time or ever.** Runs read code through the
Azure DevOps API, file by file (see screen 05). `last_indexed_commit` stays
empty, so the UI says "not cloned yet" rather than claiming an index that does
not exist.

**How much code a run reads** is decided by the agent, not by a fixed rule — see
[`docs/decisions/0001-scope-expansion.md`](docs/decisions/0001-scope-expansion.md).
It starts from the diff and follows the change into whatever it affects, bounded
by hop, file and token limits. Repositories are deliberately not indexed ahead of
time, because scope depends on the diff.

### Azure DevOps auth traps

All confirmed against the live API, and all of them make an invalid token look
like a valid one:

- A bad PAT never returns 401. Depending on endpoint it is `203`, or a `302` to
  a sign-in page, or HTML with a 200.
- Worse, `connectionData` returns a clean **200 with an anonymous identity**
  (`aaaaaaaa-…`, display name `Anonymous`). The status code alone cannot tell
  you the token works — the identity has to be checked, or a dead credential is
  stored and only fails on the first real run.
- API versions are **per endpoint**: `connectionData` is preview-only and
  rejects `api-version=7.1`, needing `7.1-preview`; `git/repositories` is GA at
  `7.1`.

### Request forgery

The organisation and project names come from the user and land in a URL the
server calls. They are validated before use (`normalize_organization`) — bare
name, `dev.azure.com/<org>`, or legacy `<org>.visualstudio.com`, nothing else.
A value like `evil.com/yourcompany` or `yourcompany/../other` is refused rather
than silently trimmed, and redirects are never followed, because following one
would replay the `Authorization` header — and the PAT — at whatever host the
response names.

## Picking a ticket (screen 04)

`/tickets`. Reads live from Linear — nothing is stored. Tickets change, and
generating tests from a stale copy is worse than not generating them.

Every field in the query was confirmed against Linear's schema by introspection
rather than guessed, including `branchName` (Linear's suggested git branch, which
the branch-matching diff-scope rule needs) and `Comment.resolvedAt` (how an
unresolved review comment is detected).

### Acceptance criteria are parsed, not assumed

`tickets/criteria.py` is a deliberate heuristic. Nobody writes tickets to a
schema, so it recognises the shapes people actually use, in priority order:

1. An explicit heading — `## Acceptance criteria`, `**Requirements:**`,
   `### **Criteria**`. The hashes and the bold markers can both be present;
   Linear's editor emits that combination constantly.
2. `AC-1:` style labels anywhere in the body.
3. A checkbox list anywhere.

It tolerates common misspellings (`Accepance Criteria` appears in a real ticket
in this workspace) and refuses to treat an ordinary bullet list as requirements —
most tickets contain bullets that are notes, not criteria.

### Readiness has three levels, not two

Measured against real tickets, "no formal acceptance criteria" turned out to be
the *normal* case, not an error. Blocking on it would make the tool useless:

| Level | Means | Example |
|---|---|---|
| `ok` | Nothing in the way | Criteria found, PR linked, repo connected |
| `warning` | Will run, but a reviewer should know | No AC section (intent inferred), no linked PR (falls back to branch), unresolved comments, ticket already closed |
| `blocked` | Would produce nothing worth reading | No description at all, or no repository connected |

Inferring intent from a description and raising what is ambiguous *is* the
product. Only a ticket with nothing written down is genuinely untestable.

## Generating test cases (screen 05)

Press **Generate** on a ticket. A run is queued, the worker picks it up, and
`/runs/:id` shows it progress through five stages: fetch ticket, resolve diff
scope, read the changed files, draft test cases, cross-check.

- **The ticket is re-read on the server** when the run starts. Only its id
  comes from the browser — client-sent content could be stale or tampered with.
- **A snapshot and content hash** of what the run used (description, criteria,
  PR links) is stored, for the drift check in screen 06.
- **Code comes from the Azure DevOps API**, not a clone: each PR's changed files
  at its head commit, diffed against the merge base. Abandoned PRs are skipped;
  merged ones are kept.
- **The agent follows the change** with read-only `read_file` and
  `list_directory` tools, each call carrying a reason that is recorded and shown.
  See [decision 0001](docs/decisions/0001-scope-expansion.md).
- **Bounded**: 40 files, 12 model rounds, $1.00 per run by default. Hitting a
  bound marks the run *stopped early* rather than implying full coverage.
- **Cancel** is a flag the worker checks at stage and round boundaries, so a
  run stops cleanly rather than mid-write.
- **Which code**: linked pull requests first, then a **branch named after the
  ticket** (`TES-8`, `josue/tes-8-login`; not `TES-80`) diffed against the
  repository's default branch. The repository's diff-scope rule sets the order.
  Several matching branches are not guessed between (Linear's suggested branch
  name breaks a tie); a branch with nothing beyond main is skipped as probably
  merged.

## Reviewing (screen 06)

`/runs/:id/review`, opened from a finished run.

- **Test cases**: filter, select, edit inline, approve / reject, bulk priority,
  status and delete. Rewriting content marks a case *edited*; triage does not.
- **Code findings**: a location linked to Azure DevOps at the run's commit (no
  code is stored). Add one as a test case, copy a comment for the ticket, or
  dismiss it.
- **Ambiguities**: copy as a Linear comment, or answer here. Answers are fed to
  the next run of the same ticket as clarifications.
- **Nothing is written to Linear.** Comments go to the clipboard.
- **Drift** is checked when the page opens and on request, never on a timer:
  the live ticket's content hash against the run's snapshot (with what changed),
  and commits pushed to the PR or branch since the run read it.

### Choosing a model

`LLM_MODEL` in `backend/.env`. It defaults to `claude-opus-5`; the cheaper
options are one line away:

| Model | Input / output per 1M tokens | Notes |
|---|---|---|
| `claude-opus-5` | $5 / $25 | Default. Strongest at following a change across files |
| `claude-sonnet-5` | $2 / $10 | Middle ground |
| `claude-haiku-4-5` | $1 / $5 | Cheapest. No adaptive thinking or effort control |

`LLM_EFFORT` (`low`…`max`) trades depth for cost on the first two. On Opus,
server-side **refusal fallbacks** are enabled: if a safety classifier declines
a request, it is retried on a fallback model inside the same call instead of
failing the run. The conversation prefix is **prompt-cached**, so each round
re-reads the diff at a tenth of the input price.

### Generation security

- **Prompt injection is expected, not hoped away.** Ticket text, comments and
  code are written by other people and can contain instructions aimed at the
  model. The system prompt says so, and the tools make it survivable: they can
  only *read*, only inside the PR's repository, only at the PR's commit. Paths
  are validated (no `..`, no URLs), so the worst an injection can do is waste
  budget or write bad test cases — which a human reviews in screen 06.
- **Secrets are masked before code leaves.** `runs/redaction.py` masks known
  token formats (AWS, GitHub, Anthropic, Linear, Slack, JWTs, private keys,
  credentials in connection strings) and secret-named assignments. A heuristic
  net, not a guarantee.
- **`ANTHROPIC_API_KEY` lives only in the environment** — never in settings,
  the database, or a response.

### Session hardening

A session cookie is a bearer credential — whoever holds it is the user. These
narrow that:

- **CSP.** `script-src 'self'` on the built SPA, injected at build time by
  `frontend/vite.config.ts`. This is the one that matters: the app renders text
  it did not write (ticket descriptions, review comments, code from diffs), and
  CSP means injected markup cannot execute. `HttpOnly` alone would not help —
  script on the page can call the API without ever reading the cookie.
- **`__Host-` cookie prefix** in production. Browser-enforced: Secure, no
  `Domain`, `Path=/`, so a compromised sibling subdomain cannot write our
  cookies. Dev keeps the unprefixed names because the prefix requires TLS; the
  client reads either.
- **Absolute session lifetime** (`accounts/middleware.py`). Idle expiry slides
  with activity, which alone means a session that keeps being used never
  ends — including one an attacker keeps warm. The cap counts from sign-in:
  12 h idle, 7 days absolute, both configurable.

**Deployment must add** `frame-ancestors` as a real response header on whatever
serves `index.html` — it is ignored inside a `<meta>` tag, so clickjacking
protection cannot come from the bundle. Django already sends it for its own
responses.

### Before deploying anywhere real

Run `python manage.py check --deploy`. It fails on the two settings that
otherwise open the door silently:

- **`accounts.E001`** — `DJANGO_SECRET_KEY` still the default. That value is in
  this repository, and it signs session cookies: anyone who has read the source
  could mint one.
- **`accounts.W001`** — `ALLOWED_EMAIL_DOMAINS` empty. Sign-in provisions a user
  on first use, so an empty list means anyone who can reach the server can sign
  themselves in, and every account sees the Linear key's data, the connected
  repositories and the model spend. Set it to your company domains.
- **`connections.E001`–`E003`** — the credential encryption key is missing,
  invalid, or the development fallback.

`X-Forwarded-For` is only trusted for rate limiting when `TRUST_PROXY_SSL_HEADER`
says a proxy sets it; without that, a caller could invent an address per request
and walk past the per-IP limit on sign-in links.

Still open, worth doing once there are stored credentials to protect: a session
inventory with "sign out everywhere", and re-authentication before revealing or
changing the workspace's Azure DevOps PAT and Linear key.

## Tests

```bash
cd backend && python manage.py test        # 192 tests
```

Frontend typecheck and production build:

```bash
cd frontend && npm run build
```

## Design tokens

Colours, type and control sizes live once in
`frontend/src/index.css` under `@theme`, lifted from the design canvas. Use the
token utilities (`bg-ink-800`, `text-fg-dim`, `border-edge`, `text-signal`,
`h-control`) rather than raw hex, so a palette change stays a one-file edit.
