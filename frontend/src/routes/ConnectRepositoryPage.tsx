import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../components/Button";
import { WizardShell, setupSteps } from "../components/WizardShell";
import {
  AlertIcon,
  ArrowRightIcon,
  CheckIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  SpinnerIcon,
  TrashIcon,
} from "../components/icons";
import {
  ApiError,
  connectionsApi,
  type Connection,
  type DiffScopeStrategy,
  type Repository,
} from "../lib/api";

type ProviderKey = "azure_devops" | "github";

const DIFF_SCOPES: {
  key: DiffScopeStrategy;
  title: string;
  example: string;
  note: string;
  recommended?: boolean;
}[] = [
  {
    key: "linked_pr",
    title: "The pull request linked on the ticket",
    example: "PR !884",
    recommended: true,
    note: "Most reliable — the PR already knows its base, its head and every commit in between. Test cases inherit the reviewer context.",
  },
  {
    key: "branch_name",
    title: "A branch whose name contains the ticket ID",
    example: "feature/ENG-2481-*",
    note: "Works before a PR exists. Compares the branch against the repository default branch using the merge base.",
  },
  {
    key: "manual",
    title: "Ask me to pick a base and head each run",
    example: "main…HEAD",
    note: "For spikes, hotfix branches and tickets spanning more than one repository.",
  },
];

/** Read-only. One line each — the detail lives in the README. */
const CLONE_FACTS = [
  "Temporary copy of the repo, retrieves recent history only.",
  "Reads the files the ticket changed, plus what might be affected by them.",
  "Isolated sandbox. The copy is deleted when the run finishes.",
];

type AzureView =
  | { kind: "empty" }
  /** Token checked but not yet stored — the user is choosing repositories. */
  | { kind: "verified"; accountLabel: string; repositories: Repository[] }
  | { kind: "connected"; connection: Connection };

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const mb = bytes / 1_048_576;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

export function ConnectRepositoryPage() {
  const navigate = useNavigate();

  const [provider, setProvider] = useState<ProviderKey>("azure_devops");
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<AzureView>({ kind: "empty" });
  const [githubConfigured, setGithubConfigured] = useState(false);

  const [organization, setOrganization] = useState("");
  const [project, setProject] = useState("");
  const [pat, setPat] = useState("");
  const [revealPat, setRevealPat] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [strategy, setStrategy] = useState<DiffScopeStrategy>("linked_pr");

  const [busy, setBusy] = useState<
    "verify" | "connect" | "save" | "disconnect" | null
  >(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const { connections, githubConfigured: gh } = await connectionsApi.list();
      setGithubConfigured(gh);
      const azure = connections.find((c) => c.provider === "azure_devops");
      if (azure) {
        setView({ kind: "connected", connection: azure });
        setOrganization(azure.organizationName);
        setProject(azure.organizationRef);
        setStrategy(azure.diffScopeStrategy);
        setSelected(
          new Set(
            azure.repositories
              .filter((r) => r.selected)
              .map((r) => r.externalId),
          ),
        );
      }
    } catch {
      // Not fatal — the screen still works, the user just starts from empty.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function fail(err: unknown) {
    setError(
      err instanceof ApiError
        ? err
        : new ApiError("Something went wrong.", { status: 0 }),
    );
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (!organization.trim() || !pat.trim() || busy) return;
    setBusy("verify");
    setError(null);
    try {
      const { account, repositories } = await connectionsApi.verifyAzure(
        organization.trim(),
        pat.trim(),
        project.trim(),
      );
      setOrganization(account.organization);
      setView({
        kind: "verified",
        accountLabel: account.email || account.displayName,
        repositories,
      });
      setSelected(new Set());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function connect() {
    if (view.kind !== "verified" || selected.size === 0 || busy) return;
    setBusy("connect");
    setError(null);
    try {
      const { connection } = await connectionsApi.connectAzure({
        organization: organization.trim(),
        project: project.trim(),
        pat: pat.trim(),
        repositoryIds: [...selected],
        diffScopeStrategy: strategy,
      });
      setView({ kind: "connected", connection });
      setPat("");
      setRevealPat(false);
      setSavedAt(Date.now());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function saveSettings() {
    if (view.kind !== "connected" || selected.size === 0 || busy) return;
    setBusy("save");
    setError(null);
    try {
      const { connection } = await connectionsApi.updateAzureSettings({
        repositoryIds: [...selected],
        diffScopeStrategy: strategy,
      });
      setView({ kind: "connected", connection });
      setSavedAt(Date.now());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (busy) return;
    setBusy("disconnect");
    setError(null);
    try {
      await connectionsApi.disconnectAzure();
      setView({ kind: "empty" });
      setSelected(new Set());
      setPat("");
      setSavedAt(null);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  function toggleRepository(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const isAzure = provider === "azure_devops";
  const connected = view.kind === "connected";
  const repositories =
    view.kind === "verified"
      ? view.repositories
      : connected
        ? view.connection.repositories
        : [];

  const storedSelection = connected
    ? new Set(
        view.connection.repositories
          .filter((r) => r.selected)
          .map((r) => r.externalId),
      )
    : new Set<string>();
  const settingsChanged =
    connected &&
    (selected.size !== storedSelection.size ||
      [...selected].some((id) => !storedSelection.has(id)) ||
      strategy !== view.connection.diffScopeStrategy);

  const footerHint = !isAzure
    ? "Azure DevOps is the only Phase 1 option"
    : connected
      ? settingsChanged
        ? "Unsaved changes"
        : `${storedSelection.size} repositor${storedSelection.size === 1 ? "y" : "ies"} connected`
      : "Connect a repository to continue";

  return (
    <WizardShell
      steps={setupSteps(1)}
      contentWidth={900}
      footer={
        <div className="flex items-center justify-between gap-4">
          <Button
            variant="secondary"
            onClick={() => navigate("/setup/project-management")}
          >
            Back
          </Button>
          <div className="flex items-center gap-3.5">
            <span
              className={`hidden font-mono text-[11px] sm:inline ${
                connected && !settingsChanged ? "text-fg-faint" : "text-warn"
              }`}
            >
              {footerHint}
            </span>
            <Button
              variant={connected && !settingsChanged ? "primary" : "secondary"}
              disabled={!connected || settingsChanged}
              onClick={() => navigate("/")}
              icon={<ArrowRightIcon size={14} />}
            >
              Continue
            </Button>
          </div>
        </div>
      }
    >
      <h1 className="mb-2 font-display text-[28px] font-semibold tracking-tight text-fg-bright">
        Connect your source code
      </h1>
      <p className="mb-6 max-w-[680px] text-[14px] text-fg-dimmer text-pretty">
        Where the code comes from. Nothing is cloned until a run starts.
      </p>

      {/* --- provider --- */}
      <div className="mb-5 flex flex-col gap-2 sm:flex-row">
        {(
          [
            {
              key: "azure_devops",
              name: "Azure DevOps",
              initial: "A",
              available: true,
            },
            {
              key: "github",
              name: "GitHub",
              initial: "G",
              available: githubConfigured,
            },
          ] as const
        ).map((p) => {
          const on = p.key === provider;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => setProvider(p.key)}
              aria-pressed={on}
              className={`flex min-w-[246px] cursor-pointer items-center gap-2.5 rounded-[8px] border px-4 py-2.5 text-left transition-colors ${
                on
                  ? "border-signal-edge bg-[#121710]"
                  : "border-edge bg-ink-800 hover:border-edge-strong"
              }`}
            >
              <span
                className={`flex size-7 shrink-0 items-center justify-center rounded-[6px] font-mono text-[12px] ${
                  p.key === "azure_devops"
                    ? "bg-info-bg text-info"
                    : "bg-ink-500 text-fg-muted"
                }`}
              >
                {p.initial}
              </span>
              <span className="flex-1">
                <span
                  className={`block text-[13.5px] font-semibold ${on ? "text-fg" : "text-fg-muted"}`}
                >
                  {p.name}
                </span>
                <span
                  className={`block font-mono text-[10.5px] ${on ? "text-signal-dim" : "text-fg-faint"}`}
                >
                  {p.key === "azure_devops"
                    ? connected
                      ? `connected · ${view.connection.organizationName}`
                      : "available now"
                    : p.available
                      ? "available"
                      : "app not installed"}
                </span>
              </span>
              <span
                className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${
                  on ? "border-signal bg-signal" : "border-fg-ghost"
                }`}
              >
                {on && <span className="size-1.5 rounded-full bg-ink-900" />}
              </span>
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="flex items-center gap-3 rounded-[10px] border border-edge bg-ink-800 px-5 py-8 text-fg-faint">
          <SpinnerIcon size={18} />
          <span className="text-[13px]">Checking existing connections…</span>
        </div>
      ) : !isAzure ? (
        <div className="flex items-start gap-4 rounded-[10px] border border-dashed border-edge-strong bg-ink-800 px-5 py-7">
          <AlertIcon size={20} className="mt-0.5 shrink-0 text-warn" />
          <div>
            <h2 className="mb-1.5 font-display text-[16px] font-semibold text-fg">
              GitHub needs an app installation
            </h2>
            <p className="max-w-[560px] text-[13px] text-fg-dimmer text-pretty">
              Unlike a personal access token, a GitHub App is installed against
              the organisation and scoped to chosen repositories — better for
              shared use, but it has to be registered first. Phase 1 ships Azure
              DevOps.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* --- credentials --- */}
          <section className="mb-3.5 rounded-[10px] border border-edge bg-ink-800 px-5 py-5">
            <div className="mb-4 flex items-center justify-between">
              <p className="label-micro">
                {connected
                  ? "Azure DevOps connection"
                  : "Azure DevOps credentials"}
              </p>
              <p className="font-mono text-[11px] text-fg-faint">
                scopes: Code (read), Work Items (read)
              </p>
            </div>

            {connected ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <ReadOnlyField
                  label="Organisation"
                  value={view.connection.organizationName}
                />
                <ReadOnlyField
                  label="Project"
                  value={view.connection.organizationRef || "All projects"}
                />
                <ReadOnlyField
                  label="Personal access token"
                  value={view.connection.credentialHint}
                  verified
                />
              </div>
            ) : (
              <form onSubmit={verify}>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <TextField
                    label="Organisation"
                    value={organization}
                    onChange={setOrganization}
                    placeholder="dev.azure.com/yourcompany"
                    error={
                      error?.code === "invalid_organization"
                        ? error.message
                        : undefined
                    }
                  />
                  <TextField
                    label="Project (optional)"
                    value={project}
                    onChange={setProject}
                    placeholder="All projects"
                  />
                  <div>
                    <p className="label-micro mb-1.5">Personal access token</p>
                    <div className="flex h-[37px] items-center gap-2 rounded-[7px] border border-edge-field bg-ink-900 px-3 focus-within:border-signal-edge">
                      <input
                        type={revealPat ? "text" : "password"}
                        value={pat}
                        onChange={(e) => {
                          setPat(e.target.value);
                          if (error) setError(null);
                        }}
                        placeholder="••••••••"
                        aria-label="Azure DevOps personal access token"
                        autoComplete="off"
                        spellCheck={false}
                        className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-fg-muted outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => setRevealPat((v) => !v)}
                        aria-label={revealPat ? "Hide token" : "Show token"}
                        className="cursor-pointer text-fg-faint hover:text-fg-dim"
                      >
                        {revealPat ? (
                          <EyeOffIcon size={14} />
                        ) : (
                          <EyeIcon size={14} />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <Button
                    type="submit"
                    variant="secondary"
                    busy={busy === "verify"}
                    disabled={!organization.trim() || !pat.trim()}
                  >
                    Check token
                  </Button>
                  <span className="font-mono text-[11px] text-fg-faint">
                    Azure DevOps → User settings → Personal access tokens
                  </span>
                </div>
              </form>
            )}

            {error && error.code !== "invalid_organization" && (
              <Callout tone="danger" className="mt-4">
                {error.message}
              </Callout>
            )}
          </section>

          {/* --- repositories --- */}
          {repositories.length > 0 && (
            <section className="mb-3.5 rounded-[10px] border border-edge bg-ink-800 px-5 py-5">
              <div className="mb-3 flex items-center justify-between">
                <p className="label-micro">Repositories discovered</p>
                <p className="font-mono text-[11px] text-fg-faint">
                  {selected.size} of {repositories.length} selected
                </p>
              </div>
              <ul className="flex flex-col gap-1.5">
                {repositories.map((repo) => {
                  const on = selected.has(repo.externalId);
                  return (
                    <li key={repo.externalId}>
                      <button
                        type="button"
                        role="checkbox"
                        aria-checked={on}
                        onClick={() => toggleRepository(repo.externalId)}
                        className={`flex w-full cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-[7px] border px-3 py-2.5 text-left transition-colors ${
                          on
                            ? "border-signal-edge bg-[#121710]"
                            : "border-edge bg-ink-700 hover:border-edge-strong"
                        }`}
                      >
                        <span
                          className={`flex size-[15px] shrink-0 items-center justify-center rounded-[4px] border ${
                            on ? "border-signal bg-signal" : "border-fg-ghost"
                          }`}
                        >
                          {on && (
                            <CheckIcon size={9} className="text-ink-900" />
                          )}
                        </span>
                        <span
                          className={`w-40 shrink-0 truncate font-mono text-[13px] ${on ? "text-fg" : "text-fg-muted"}`}
                        >
                          {repo.name}
                        </span>
                        <span className="w-32 shrink-0 truncate font-mono text-[11px] text-fg-faint">
                          default {repo.defaultBranch || "—"}
                        </span>
                        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint">
                          {repo.projectName} · {formatSize(repo.sizeBytes)}
                        </span>
                        <span
                          className={`shrink-0 rounded-[3px] border px-1.5 font-mono text-[10px] ${
                            repo.isIndexed
                              ? "border-signal-edge bg-signal-bg text-signal"
                              : "border-edge-strong text-fg-faint"
                          }`}
                        >
                          {repo.isIndexed
                            ? repo.lastIndexedCommit.slice(0, 7)
                            : "NOT CLONED YET"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-3 text-[11.5px] text-fg-faint">
                Nothing is cloned now — the first run for a ticket clones what
                it needs into a throwaway container.
              </p>
            </section>
          )}

          {/* --- diff scope --- */}
          {repositories.length > 0 && (
            <section className="mb-3.5 rounded-[10px] border border-edge bg-ink-800 px-5 py-5">
              <p className="label-micro mb-1.5">
                How a ticket maps to a code change
              </p>
              <p className="mb-3.5 max-w-[660px] text-[12.5px] text-fg-dimmer text-pretty">
                The agent needs one diff per run. Pick the rule it should try
                first — it falls back down the list and asks you if nothing
                matches.
              </p>
              <div className="flex flex-col gap-2">
                {DIFF_SCOPES.map((scope) => {
                  const on = scope.key === strategy;
                  return (
                    <button
                      key={scope.key}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => setStrategy(scope.key)}
                      className={`flex cursor-pointer items-start gap-3 rounded-[8px] border px-3.5 py-3 text-left transition-colors ${
                        on
                          ? "border-signal-edge bg-[#121710]"
                          : "border-edge bg-ink-700 hover:border-edge-strong"
                      }`}
                    >
                      <span
                        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border ${
                          on ? "border-signal bg-signal" : "border-fg-ghost"
                        }`}
                      >
                        {on && (
                          <span className="size-1.5 rounded-full bg-ink-900" />
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="mb-1 flex flex-wrap items-center gap-2.5">
                          <span
                            className={`text-[13px] font-medium ${on ? "text-fg" : "text-fg-muted"}`}
                          >
                            {scope.title}
                          </span>
                          {scope.recommended && (
                            <span className="rounded-[3px] border border-signal-edge bg-signal-bg px-1.5 font-mono text-[9.5px] tracking-[0.06em] text-signal">
                              RECOMMENDED
                            </span>
                          )}
                        </span>
                        <span className="block text-[12px] text-fg-dimmer text-pretty">
                          {scope.note}
                        </span>
                      </span>
                      <span className="mt-0.5 shrink-0 font-mono text-[11px] text-info">
                        {scope.example}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* --- actions --- */}
          {view.kind === "verified" && (
            <div className="mb-3.5 flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                busy={busy === "connect"}
                disabled={selected.size === 0}
                onClick={() => void connect()}
              >
                Save connection
              </Button>
              <span className="font-mono text-[11px] text-fg-faint">
                {selected.size === 0
                  ? "Pick at least one repository"
                  : `Token verified as ${view.accountLabel}`}
              </span>
            </div>
          )}

          {connected && (
            <div className="mb-3.5 flex flex-wrap items-center gap-3">
              {settingsChanged && (
                <Button
                  variant="primary"
                  busy={busy === "save"}
                  onClick={() => void saveSettings()}
                >
                  Save changes
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => {
                  setView({ kind: "empty" });
                  setSelected(new Set());
                }}
              >
                Replace token
              </Button>
              <Button
                variant="ghost"
                busy={busy === "disconnect"}
                onClick={() => void disconnect()}
                icon={<TrashIcon size={14} />}
              >
                Disconnect
              </Button>
              <div className="flex-1" />
              {savedAt && !settingsChanged && (
                <span className="flex items-center gap-1.5 font-mono text-[11px] text-signal">
                  <CheckIcon size={12} /> Saved
                </span>
              )}
            </div>
          )}

          {/* --- clone container --- */}
          <section className="rounded-[10px] border border-edge bg-ink-800 px-5 py-5">
            <p className="label-micro mb-3">What happens on each run</p>
            {/* Plain lines, not bordered cards: every card on this screen is
                clickable, and this is read-only. */}
            <ul className="flex flex-col gap-2">
              {CLONE_FACTS.map((fact) => (
                <li key={fact} className="flex items-center gap-2.5">
                  <span className="size-1 shrink-0 rounded-full bg-fg-ghost" />
                  <span className="text-[13px] text-fg-dim">{fact}</span>
                </li>
              ))}
            </ul>
            <Callout
              tone="neutral"
              className="mt-4"
              icon={<LockIcon size={14} />}
            >
              Encrypted before storage, never sent back to the browser.
              Read-only scopes are enough — the agent never writes.
            </Callout>
          </section>
        </>
      )}
    </WizardShell>
  );
}

/* --- small field helpers -------------------------------------------------- */

function TextField({
  label,
  value,
  onChange,
  placeholder,
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  error?: string;
}) {
  return (
    <div>
      <p className="label-micro mb-1.5">{label}</p>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        spellCheck={false}
        className={`h-[37px] w-full rounded-[7px] border bg-ink-900 px-3 font-mono text-[12.5px] text-fg-muted outline-none ${
          error
            ? "border-danger-edge"
            : "border-edge-field focus:border-signal-edge"
        }`}
      />
      {error && (
        <p role="alert" className="mt-1.5 text-[11.5px] text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function ReadOnlyField({
  label,
  value,
  verified,
}: {
  label: string;
  value: string;
  verified?: boolean;
}) {
  // Deliberately not styled like the input it replaces: a bordered box on a
  // dark field reads as "type here", and this value cannot be edited. Use
  // "Replace token" to change it.
  return (
    <div className="min-w-0">
      <p className="label-micro mb-1.5">{label}</p>
      <div className="flex h-[37px] items-center gap-2">
        <span className="min-w-0 truncate font-mono text-[12.5px] text-fg-muted">
          {value}
        </span>
        {verified && (
          <span className="flex shrink-0 items-center gap-1 text-signal">
            <CheckIcon size={13} />
            <span className="font-mono text-[10.5px]">verified</span>
          </span>
        )}
      </div>
    </div>
  );
}

function Callout({
  tone,
  icon,
  className,
  children,
}: {
  tone: "danger" | "neutral";
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const tones = {
    danger: "border-danger-edge bg-danger-bg",
    neutral: "border-edge bg-ink-700",
  };
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={`flex gap-2.5 rounded-[7px] border px-3 py-2.5 ${tones[tone]} ${className ?? ""}`}
    >
      <span
        className={`mt-px shrink-0 ${tone === "danger" ? "text-danger" : "text-fg-faint"}`}
      >
        {icon ?? <AlertIcon size={14} />}
      </span>
      <span className="text-[12px] text-fg-dimmer text-pretty">{children}</span>
    </div>
  );
}
