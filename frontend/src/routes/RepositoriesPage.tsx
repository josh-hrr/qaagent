import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Button } from "../components/Button";
import {
  AlertIcon,
  BranchIcon,
  CheckIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
} from "../components/icons";
import {
  ApiError,
  connectionsApi,
  type Connection,
  type DiffScopeStrategy,
  type Repository,
} from "../lib/api";

const SCOPES: {
  key: DiffScopeStrategy;
  label: string;
  note: string;
  built: boolean;
}[] = [
  {
    key: "linked_pr",
    label: "The pull request linked on the ticket",
    note: "Attachments, the description and the comments are all read. Falls back to a matching branch.",
    built: true,
  },
  {
    key: "branch_name",
    label: "A branch whose name contains the ticket ID",
    note: "TES-8 matches josue/tes-8-login, not TES-80. Falls back to a linked pull request.",
    built: true,
  },
  {
    key: "manual",
    label: "Ask me to pick a base and head each run",
    note: "Designed, not built. Selecting it today behaves like the linked pull request rule.",
    built: false,
  },
];

type ProviderKey = "azure_devops" | "github";

const RUN_FACTS = [
  "Reads the changed files over the Azure DevOps API. The repo is never copied.",
  "Reads the files the ticket changed, plus what might be affected by them.",
  "Read-only, pinned to one commit. Code is not stored when the run finishes.",
];

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const mb = bytes / 1_048_576;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export function RepositoriesPage() {
  const navigate = useNavigate();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<"verify" | "save" | "disconnect" | null>(
    null,
  );
  const [selection, setSelection] = useState<Set<string> | null>(null);
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<ProviderKey>("azure_devops");
  const [githubConfigured, setGithubConfigured] = useState(false);

  const load = useCallback(async () => {
    try {
      const { connections, githubConfigured: github } =
        await connectionsApi.list();
      setGithubConfigured(github);
      setConnection(
        connections.find((item) => item.provider === "azure_devops") ?? null,
      );
      setError("");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not load the connection.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const repositories = useMemo(
    () => connection?.repositories ?? [],
    [connection],
  );
  const stored = useMemo(
    () =>
      new Set(
        repositories
          .filter((repo) => repo.selected)
          .map((repo) => repo.externalId),
      ),
    [repositories],
  );
  const chosen = selection ?? stored;
  const dirty =
    selection !== null &&
    (selection.size !== stored.size ||
      [...selection].some((id) => !stored.has(id)));

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return repositories;
    return repositories.filter(
      (repo) =>
        repo.name.toLowerCase().includes(needle) ||
        repo.projectName.toLowerCase().includes(needle),
    );
  }, [repositories, query]);

  function toggle(repo: Repository) {
    setSelection((current) => {
      const next = new Set(current ?? stored);
      if (next.has(repo.externalId)) next.delete(repo.externalId);
      else next.add(repo.externalId);
      return next;
    });
  }

  async function reverify() {
    setBusy("verify");
    setNotice("");
    try {
      const body = await connectionsApi.reverifyAzure();
      setConnection(body.connection);
      setSelection(null);
      setNotice(body.detail ? "" : "Token still works");
      if (body.detail) setError(body.detail);
      else setError("");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach Azure DevOps.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function saveSelection() {
    if (!dirty) return;
    setBusy("save");
    try {
      const { connection: updated } = await connectionsApi.updateAzureSettings({
        repositoryIds: [...chosen],
      });
      setConnection(updated);
      setSelection(null);
      setNotice("Selection saved");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save the selection.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function setScope(strategy: DiffScopeStrategy) {
    if (!connection || connection.diffScopeStrategy === strategy) return;
    try {
      const { connection: updated } = await connectionsApi.updateAzureSettings({
        diffScopeStrategy: strategy,
      });
      setConnection(updated);
      setNotice("Rule saved");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save the rule.",
      );
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Disconnect Azure DevOps? The token is deleted and runs will stop finding code.",
      )
    )
      return;
    setBusy("disconnect");
    try {
      await connectionsApi.disconnectAzure();
      navigate("/setup/source-code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect.");
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <AppShell title="Repositories">
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          <SpinnerIcon size={18} />
          <span className="text-[13px]">Loading…</span>
        </div>
      </AppShell>
    );
  }

  if (!connection) {
    return (
      <AppShell title="Repositories">
        <div className="flex flex-1 items-center justify-center px-5">
          <div className="w-120 text-center">
            <div className="mx-auto mb-5 flex size-13.5 items-center justify-center rounded-xl border border-edge-strong bg-ink-800">
              <BranchIcon size={24} className="text-fg-faint" />
            </div>
            <h2 className="mb-2 font-display text-[20px] font-semibold text-fg">
              No source code connected
            </h2>
            <p className="mb-5.5 text-[13px] text-fg-dimmer text-pretty">
              A run needs somewhere to read the diff from. Connect Azure DevOps
              with a read-only token and pick the repositories your team
              actually ships from.
            </p>
            <Link to="/setup/source-code" className="no-underline">
              <Button variant="primary">Connect Azure DevOps</Button>
            </Link>
          </div>
        </div>
      </AppShell>
    );
  }

  const failing = connection.status === "error";
  const selectedCount = chosen.size;

  return (
    <AppShell
      title="Repositories"
      subtitle={
        <span>
          {connection.organizationName}
          {connection.organizationRef ? ` · ${connection.organizationRef}` : ""}
        </span>
      }
      actions={
        // The pill describes the Azure connection, so it goes away while the
        // GitHub panel is showing rather than claiming something about GitHub.
        provider === "azure_devops" ? (
          <span
            className={`flex h-6.5 items-center gap-1.75 rounded-[5px] border px-2.25 font-mono text-[10.5px] ${
              failing
                ? "border-danger-edge bg-danger-bg text-danger"
                : "border-signal-edge bg-signal-bg text-signal"
            }`}
          >
            <span
              className={`size-1.25 rounded-full ${failing ? "bg-danger" : "bg-signal"}`}
            />
            {failing ? "token rejected" : "connected"}
          </span>
        ) : undefined
      }
    >
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4.5">
        <div className="flex max-w-250 flex-col gap-3.5">
          {/* provider switch — the same one the first-run screen uses, so the
              two screens do not disagree about what is available. */}
          <section>
            <h2 className="mb-1 font-display text-[15px] font-semibold text-fg">
              Source code provider
            </h2>
            <p className="mb-3 text-[12.5px] text-fg-dimmer">
              Where the code comes from. A run reads it over the API, never by
              cloning.
            </p>
            <div className="flex flex-wrap gap-2.5">
              {(
                [
                  { key: "azure_devops", name: "Azure DevOps", initial: "A" },
                  { key: "github", name: "GitHub", initial: "G" },
                ] as const
              ).map((item) => {
                const on = item.key === provider;
                const state =
                  item.key === "azure_devops"
                    ? failing
                      ? "token rejected"
                      : `connected · ${connection.organizationName}`
                    : githubConfigured
                      ? "available"
                      : "app not installed";
                return (
                  <button
                    key={item.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setProvider(item.key)}
                    className={`flex min-w-61.5 cursor-pointer items-center gap-2.5 rounded-lg border px-4 py-2.5 text-left transition-colors ${
                      on
                        ? "border-signal-edge bg-[#121710]"
                        : "border-edge bg-ink-800 hover:border-edge-strong"
                    }`}
                  >
                    <span
                      className={`flex size-7 shrink-0 items-center justify-center rounded-md font-mono text-[12px] ${
                        item.key === "azure_devops"
                          ? "bg-info-bg text-info"
                          : "bg-ink-500 text-fg-muted"
                      }`}
                    >
                      {item.initial}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block text-[13.5px] font-semibold ${on ? "text-fg" : "text-fg-muted"}`}
                      >
                        {item.name}
                      </span>
                      <span
                        className={`block truncate font-mono text-[10.5px] ${
                          item.key === "azure_devops" && failing
                            ? "text-danger"
                            : on
                              ? "text-signal-dim"
                              : "text-fg-faint"
                        }`}
                      >
                        {state}
                      </span>
                    </span>
                    <span
                      className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${
                        on ? "border-signal bg-signal" : "border-fg-ghost"
                      }`}
                    >
                      {on && (
                        <span className="size-1.5 rounded-full bg-ink-900" />
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {provider === "github" && (
            <div className="flex items-start gap-4 rounded-[10px] border border-dashed border-edge-strong bg-ink-800 px-5 py-7">
              <AlertIcon size={20} className="mt-0.5 shrink-0 text-warn" />
              <div>
                <h2 className="mb-1.5 font-display text-[16px] font-semibold text-fg">
                  GitHub needs an app installation
                </h2>
                <p className="max-w-140 text-[13px] text-fg-dimmer text-pretty">
                  Unlike a personal access token, a GitHub App is installed
                  against the organisation and scoped to chosen repositories —
                  better for shared use, but it has to be registered first.
                  Phase 1 ships Azure DevOps.
                </p>
              </div>
            </div>
          )}

          {provider === "azure_devops" && failing && (
            <div className="flex items-start gap-2.75 rounded-[9px] border border-danger-edge bg-danger-bg px-3.75 py-3.25">
              <AlertIcon size={16} className="mt-0.5 shrink-0 text-danger" />
              <div className="flex-1">
                <p className="mb-0.75 text-[13px] font-semibold text-fg">
                  Azure DevOps rejected this token
                </p>
                <p className="text-[12.5px] text-fg-muted text-pretty">
                  {connection.lastError ||
                    "Runs that need code will fail until the token is replaced."}
                </p>
              </div>
              <Link to="/setup/source-code" className="no-underline">
                <Button variant="primary" className="h-7 px-3 text-[12px]">
                  Replace token
                </Button>
              </Link>
            </div>
          )}

          {provider === "azure_devops" && (
            <>
              {/* connection */}
              <section className="rounded-[10px] border border-edge bg-ink-800 px-4.75 py-4.25">
                <div className="mb-4 flex flex-wrap items-center gap-2.75">
                  <span className="flex size-7 items-center justify-center rounded-[7px] border border-edge bg-ink-700">
                    <BranchIcon size={15} className="text-info" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] font-semibold text-fg">
                      Azure DevOps
                    </span>
                    <span className="block font-mono text-[11px] text-fg-faint">
                      Personal access token · read-only Code and Work Items
                    </span>
                  </span>
                  <span className="flex gap-2">
                    <Button
                      variant="secondary"
                      busy={busy === "verify"}
                      onClick={() => void reverify()}
                      icon={<RefreshIcon size={13} />}
                      className="h-7 px-2.75 text-[12px]"
                    >
                      Re-verify
                    </Button>
                    <Link to="/setup/source-code" className="no-underline">
                      <Button
                        variant="secondary"
                        className="h-7 px-2.75 text-[12px]"
                      >
                        Replace token
                      </Button>
                    </Link>
                    <button
                      type="button"
                      disabled={busy === "disconnect"}
                      onClick={() => void disconnect()}
                      className="flex h-7 cursor-pointer items-center rounded-md px-2.75 text-[12px] text-danger hover:bg-danger-bg disabled:opacity-60"
                    >
                      Disconnect
                    </button>
                  </span>
                </div>

                <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-edge bg-edge md:grid-cols-4">
                  {[
                    {
                      k: "Organisation",
                      v: connection.organizationName || "—",
                    },
                    {
                      k: "Project",
                      v: connection.organizationRef || "all projects",
                    },
                    { k: "Token", v: connection.credentialHint || "—" },
                    { k: "Connected by", v: connection.connectedBy || "—" },
                    {
                      k: "Last verified",
                      v: failing
                        ? `failed ${ago(connection.lastVerifiedAt)}`
                        : ago(connection.lastVerifiedAt),
                      tone: failing ? "text-danger" : "",
                    },
                    {
                      k: "Repositories",
                      v: `${stored.size} of ${repositories.length} in scope`,
                    },
                    { k: "Auth", v: connection.authMethod },
                    { k: "Provider", v: "azure_devops" },
                  ].map((fact) => (
                    <div key={fact.k} className="bg-ink-700 px-3.25 py-2.75">
                      <dt className="label-micro mb-1">{fact.k}</dt>
                      <dd
                        className={`truncate font-mono text-[11.5px] ${fact.tone || "text-fg-dim"}`}
                      >
                        {fact.v}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>

              {/* repositories */}
              <section className="overflow-hidden rounded-[10px] border border-edge bg-ink-800">
                <div className="flex flex-wrap items-center gap-2.5 border-b border-edge px-4.75 py-3.5">
                  <span className="text-[13.5px] font-semibold text-fg">
                    Repositories in scope
                  </span>
                  <span className="font-mono text-[11px] text-fg-faint">
                    {selectedCount} of {repositories.length} selected
                  </span>
                  <span className="flex-1" />
                  <label className="flex h-7 w-50 items-center gap-2 rounded-md border border-edge-field bg-ink-900 px-2.5 focus-within:border-fg-faint">
                    <SearchIcon size={12} className="shrink-0 text-fg-faint" />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Filter repositories…"
                      className="min-w-0 flex-1 bg-transparent text-[11.5px] text-fg-muted outline-none"
                    />
                  </label>
                </div>

                <div className="flex items-center gap-3 px-4.75 pt-2.75 pb-2">
                  <span className="w-3.75" />
                  <span className="label-micro flex-1">Repository</span>
                  <span className="label-micro hidden w-37.5 lg:block">
                    Project
                  </span>
                  <span className="label-micro hidden w-32.5 md:block">
                    Default branch
                  </span>
                  <span className="label-micro w-18.5 text-right">Size</span>
                  <span className="label-micro w-27 text-right">Last read</span>
                </div>

                {visible.length === 0 && (
                  <p className="px-4.75 py-6 text-center text-[12.5px] text-fg-faint">
                    No repositories match.
                  </p>
                )}

                {visible.map((repo) => {
                  const on = chosen.has(repo.externalId);
                  return (
                    <button
                      key={repo.externalId}
                      type="button"
                      role="checkbox"
                      aria-checked={on}
                      onClick={() => toggle(repo)}
                      className={`flex w-full cursor-pointer items-center gap-3 border-t border-ink-600 px-4.75 py-2.5 text-left ${
                        on ? "bg-[#0f1317]" : "hover:bg-ink-700"
                      }`}
                    >
                      <span
                        className={`flex size-3.75 shrink-0 items-center justify-center rounded border ${
                          on ? "border-signal bg-signal" : "border-fg-ghost"
                        }`}
                      >
                        {on && <CheckIcon size={9} className="text-ink-900" />}
                      </span>
                      <span
                        className={`min-w-0 flex-1 truncate font-mono text-[12px] ${on ? "text-fg" : "text-fg-dimmer"}`}
                      >
                        {repo.name}
                      </span>
                      <span className="hidden w-37.5 truncate font-mono text-[11px] text-fg-faint lg:block">
                        {repo.projectName || "—"}
                      </span>
                      <span className="hidden w-32.5 truncate font-mono text-[11px] text-fg-faint md:block">
                        {repo.defaultBranch || "—"}
                      </span>
                      <span className="w-18.5 text-right font-mono text-[11px] text-fg-faint">
                        {formatSize(repo.sizeBytes)}
                      </span>
                      <span className="w-27 text-right">
                        <span
                          className={`rounded-[3px] border px-1.5 font-mono text-[10px] ${
                            repo.isIndexed
                              ? "border-[#2c400f] bg-[#141c0c] text-signal-dim"
                              : "border-edge-strong text-fg-faint"
                          }`}
                        >
                          {repo.isIndexed
                            ? repo.lastIndexedCommit.slice(0, 7)
                            : "NOT READ YET"}
                        </span>
                      </span>
                    </button>
                  );
                })}

                <div
                  className={`flex items-center gap-3 border-t border-edge px-4.75 py-2.75 ${dirty ? "bg-[#121710]" : ""}`}
                >
                  <span
                    className={`font-mono text-[11px] ${dirty ? "text-fg-muted" : "text-fg-faint"}`}
                  >
                    {dirty
                      ? "Selection changed — a run only ever reads a repository in scope."
                      : "Only repositories in scope are read, and only the files a ticket touches."}
                  </span>
                  <span className="flex-1" />
                  {notice && !dirty && (
                    <span
                      role="status"
                      className="font-mono text-[11px] text-signal"
                    >
                      {notice}
                    </span>
                  )}
                  {dirty && (
                    <>
                      <Button
                        variant="secondary"
                        onClick={() => setSelection(null)}
                        className="h-7 px-2.75 text-[12px]"
                      >
                        Discard
                      </Button>
                      <Button
                        variant="primary"
                        busy={busy === "save"}
                        onClick={() => void saveSelection()}
                        className="h-7 px-3.25 text-[12px]"
                      >
                        Save selection
                      </Button>
                    </>
                  )}
                </div>
              </section>

              {/* diff scope */}
              <section className="rounded-[10px] border border-edge bg-ink-800 px-4.75 py-4.25">
                <h2 className="mb-1 text-[13.5px] font-semibold text-fg">
                  How a ticket finds its code
                </h2>
                <p className="mb-3.5 max-w-175 text-[12.5px] text-fg-dimmer text-pretty">
                  Get this wrong and every test case is written against the
                  wrong diff. The rule below is tried first; the other is the
                  fallback.
                </p>
                <div className="flex flex-col gap-2">
                  {SCOPES.map((scope) => {
                    const on =
                      connection.diffScopeStrategy === scope.key && scope.built;
                    return (
                      <button
                        key={scope.key}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        disabled={!scope.built}
                        onClick={() => void setScope(scope.key)}
                        className={`flex items-start gap-2.75 rounded-lg border px-3.5 py-3 text-left ${
                          scope.built ? "cursor-pointer" : "cursor-not-allowed"
                        } ${on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"}`}
                      >
                        <span
                          className={`mt-0.5 flex size-3.75 shrink-0 items-center justify-center rounded-full border ${
                            on ? "border-signal bg-signal" : "border-fg-ghost"
                          }`}
                        >
                          {on && (
                            <span className="size-1.25 rounded-full bg-ink-900" />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="mb-0.5 flex items-center gap-2">
                            <span
                              className={`text-[12.5px] font-medium ${scope.built ? (on ? "text-fg" : "text-fg-muted") : "text-fg-faint"}`}
                            >
                              {scope.label}
                            </span>
                            {!scope.built && (
                              <span className="rounded-[3px] border border-edge-strong px-1.25 font-mono text-[9.5px] text-fg-faint">
                                not built yet
                              </span>
                            )}
                          </span>
                          <span className="block text-[11.5px] text-fg-faint text-pretty">
                            {scope.note}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>

              {/* what a run reads */}
              <section className="rounded-[10px] border border-edge bg-ink-800 px-4.75 py-4.25">
                <p className="label-micro mb-2.75">
                  What a run does with the code
                </p>
                <ul className="flex flex-col gap-2.25">
                  {RUN_FACTS.map((fact) => (
                    <li key={fact} className="flex items-center gap-2.5">
                      <span className="size-1 shrink-0 rounded-full bg-fg-ghost" />
                      <span className="text-[12.5px] text-fg-dim">{fact}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </>
          )}

          {error && !failing && (
            <p className="text-[12.5px] text-danger">{error}</p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
