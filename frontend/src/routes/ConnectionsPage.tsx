import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Button } from "../components/Button";
import { AlertIcon, CheckIcon, LockIcon, PlugIcon, RefreshIcon, SpinnerIcon } from "../components/icons";
import { ApiError, connectionsApi, type Connection } from "../lib/api";

/** Ticket trackers we intend to support. Phase 2 — drawn as facts, not buttons. */
const PLANNED = [
  { name: "Jira", note: "Cloud sites first, with the same read-only scope as Linear." },
  { name: "Azure Boards", note: "Reuses the Azure DevOps token that already reads the code." },
];

const CREDENTIAL_FACTS = [
  "Encrypted at rest with a key kept apart from the Django secret, so rotating one does not break the other.",
  "Write-only from the browser's side: you can replace a key, never read one back. The API returns a stub.",
  "One connection per provider, shared by the workspace — revoking happens in a single place.",
  "Read-only scopes are enough. Nothing here ever writes to Linear or to a repository.",
];

function ago(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export function ConnectionsPage() {
  const navigate = useNavigate();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<"verify" | "save" | "disconnect" | null>(null);
  const [selection, setSelection] = useState<Set<string> | null>(null);

  const load = useCallback(async () => {
    try {
      const { connections } = await connectionsApi.list();
      setConnection(connections.find((item) => item.provider === "linear") ?? null);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load connections.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const teams = useMemo(() => connection?.teams ?? [], [connection]);
  const stored = useMemo(
    () => new Set(teams.filter((team) => team.selected).map((team) => team.linear_id)),
    [teams],
  );
  const chosen = selection ?? stored;
  const dirty = selection !== null && (selection.size !== stored.size || [...selection].some((id) => !stored.has(id)));

  async function reverify() {
    setBusy("verify");
    setNotice("");
    try {
      const body = await connectionsApi.reverifyLinear();
      setConnection(body.connection);
      setSelection(null);
      if (body.detail) setError(body.detail);
      else {
        setError("");
        setNotice("Key still works");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach Linear.");
    } finally {
      setBusy(null);
    }
  }

  async function saveTeams() {
    if (!dirty) return;
    setBusy("save");
    try {
      const { connection: updated } = await connectionsApi.updateLinearTeams([...chosen]);
      setConnection(updated);
      setSelection(null);
      setNotice("Teams saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the teams.");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Linear? The API key is deleted and tickets stop loading.")) return;
    setBusy("disconnect");
    try {
      await connectionsApi.disconnectLinear();
      navigate("/setup/project-management");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect.");
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <AppShell title="Connections">
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          <SpinnerIcon size={18} />
          <span className="text-[13px]">Loading…</span>
        </div>
      </AppShell>
    );
  }

  if (!connection) {
    return (
      <AppShell title="Connections">
        <div className="flex flex-1 items-center justify-center px-5">
          <div className="w-120 text-center">
            <div className="mx-auto mb-5 flex size-13.5 items-center justify-center rounded-xl border border-edge-strong bg-ink-800">
              <PlugIcon size={24} className="text-fg-faint" />
            </div>
            <h2 className="mb-2 font-display text-[20px] font-semibold text-fg">No ticket tracker connected</h2>
            <p className="mb-5.5 text-[13px] text-fg-dimmer text-pretty">
              Everything starts from a ticket: the description, its acceptance criteria and the pull requests linked on
              it. Connect Linear with a personal API key to list them.
            </p>
            <Link to="/setup/project-management" className="no-underline">
              <Button variant="primary">Connect Linear</Button>
            </Link>
          </div>
        </div>
      </AppShell>
    );
  }

  const failing = connection.status === "error";

  return (
    <AppShell
      title="Connections"
      subtitle={<span>Shared by the whole workspace</span>}
      actions={
        <span
          className={`flex h-6.5 items-center gap-1.75 rounded-[5px] border px-2.25 font-mono text-[10.5px] ${
            failing ? "border-danger-edge bg-danger-bg text-danger" : "border-signal-edge bg-signal-bg text-signal"
          }`}
        >
          <span className={`size-1.25 rounded-full ${failing ? "bg-danger" : "bg-signal"}`} />
          {failing ? "key rejected" : "connected"}
        </span>
      }
    >
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4.5">
        <div className="flex max-w-250 flex-col gap-3.5">
          {failing && (
            <div className="flex items-start gap-2.75 rounded-[9px] border border-danger-edge bg-danger-bg px-3.75 py-3.25">
              <AlertIcon size={16} className="mt-0.5 shrink-0 text-danger" />
              <div className="flex-1">
                <p className="mb-0.75 text-[13px] font-semibold text-fg">Linear rejected this API key</p>
                <p className="text-[12.5px] text-fg-muted text-pretty">
                  {connection.lastError ||
                    "Tickets cannot be listed and no run can start until the key is replaced."}
                </p>
              </div>
              <Link to="/setup/project-management" className="no-underline">
                <Button variant="primary" className="h-7 px-3 text-[12px]">
                  Replace key
                </Button>
              </Link>
            </div>
          )}

          {/* Linear */}
          <section className="overflow-hidden rounded-[10px] border border-edge bg-ink-800">
            <div className="flex flex-wrap items-center gap-2.75 px-4.75 py-4">
              <span className="flex size-7 items-center justify-center rounded-[7px] border border-edge bg-ink-700">
                <PlugIcon size={15} className="text-info" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold text-fg">Linear</span>
                <span className="block font-mono text-[11px] text-fg-faint">Personal API key · ticket context</span>
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
                <Link to="/setup/project-management" className="no-underline">
                  <Button variant="secondary" className="h-7 px-2.75 text-[12px]">
                    Replace key
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

            <dl className="grid grid-cols-2 gap-px border-y border-edge bg-edge md:grid-cols-4">
              {[
                { k: "Workspace", v: connection.organizationName || "—" },
                { k: "API key", v: connection.credentialHint || "—" },
                { k: "Connected by", v: connection.connectedBy || "—" },
                {
                  k: "Last verified",
                  v: failing ? `failed ${ago(connection.lastVerifiedAt)}` : ago(connection.lastVerifiedAt),
                  tone: failing ? "text-danger" : "",
                },
              ].map((fact) => (
                <div key={fact.k} className="bg-ink-700 px-3.25 py-2.75">
                  <dt className="label-micro mb-1">{fact.k}</dt>
                  <dd className={`truncate font-mono text-[11.5px] ${fact.tone || "text-fg-dim"}`}>{fact.v}</dd>
                </div>
              ))}
            </dl>

            <div className="flex flex-wrap items-center gap-2.5 px-4.75 pt-3.5 pb-2.5">
              <span className="label-micro">Teams synced</span>
              <span className="font-mono text-[11px] text-fg-faint">
                {chosen.size} of {teams.length} · only synced teams appear in the ticket picker
              </span>
              <span className="flex-1" />
              {notice && !dirty && (
                <span role="status" className="font-mono text-[11px] text-signal">
                  {notice}
                </span>
              )}
              {dirty && (
                <>
                  <Button variant="secondary" onClick={() => setSelection(null)} className="h-6.5 px-2.5 text-[11.5px]">
                    Discard
                  </Button>
                  <Button
                    variant="primary"
                    busy={busy === "save"}
                    onClick={() => void saveTeams()}
                    className="h-6.5 px-3 text-[11.5px]"
                  >
                    Save teams
                  </Button>
                </>
              )}
            </div>

            <div className="grid gap-2 px-4.75 pb-4.5 sm:grid-cols-2">
              {teams.map((team) => {
                const on = chosen.has(team.linear_id);
                return (
                  <button
                    key={team.linear_id}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    onClick={() =>
                      setSelection((current) => {
                        const next = new Set(current ?? stored);
                        if (next.has(team.linear_id)) next.delete(team.linear_id);
                        else next.add(team.linear_id);
                        return next;
                      })
                    }
                    className={`flex cursor-pointer items-center gap-2.5 rounded-[7px] border px-2.75 py-2.25 text-left ${
                      on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"
                    }`}
                  >
                    <span
                      className={`flex size-3.75 shrink-0 items-center justify-center rounded border ${
                        on ? "border-signal bg-signal" : "border-fg-ghost"
                      }`}
                    >
                      {on && <CheckIcon size={9} className="text-ink-900" />}
                    </span>
                    <span className="shrink-0 rounded-[3px] border border-info-edge bg-info-bg px-1.25 font-mono text-[10px] text-info">
                      {team.key}
                    </span>
                    <span className={`min-w-0 flex-1 truncate text-[12.5px] ${on ? "text-fg" : "text-fg-dimmer"}`}>
                      {team.name}
                    </span>
                  </button>
                );
              })}
              {teams.length === 0 && (
                <p className="text-[12.5px] text-fg-faint">
                  This key can see no teams. Re-verify after granting it access in Linear.
                </p>
              )}
            </div>
          </section>

          {/* planned trackers */}
          <section className="overflow-hidden rounded-[10px] border border-edge bg-ink-800">
            <div className="border-b border-edge px-4.75 py-3.5">
              <h2 className="text-[13.5px] font-semibold text-fg">Other ticket trackers</h2>
              <p className="mt-0.5 font-mono text-[11px] text-fg-faint">Planned for phase 2 — nothing to configure yet.</p>
            </div>
            {PLANNED.map((tracker) => (
              <div key={tracker.name} className="flex items-center gap-3 border-t border-[#151a1e] px-4.75 py-3.25">
                <span className="flex size-6.5 shrink-0 items-center justify-center rounded-md border border-edge bg-ink-700">
                  <PlugIcon size={13} className="text-fg-ghost" />
                </span>
                <span className="w-32 shrink-0 text-[12.5px] text-fg-dimmer">{tracker.name}</span>
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-fg-faint">{tracker.note}</span>
                <span className="shrink-0 rounded-[3px] border border-edge-strong px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
                  planned
                </span>
              </div>
            ))}
          </section>

          {/* how credentials are held */}
          <section className="rounded-[10px] border border-edge bg-ink-800 px-4.75 py-4.25">
            <div className="mb-3 flex items-center gap-2.25">
              <LockIcon size={14} className="text-fg-faint" />
              <p className="label-micro">How these credentials are held</p>
            </div>
            <div className="grid gap-2.5 md:grid-cols-2">
              {CREDENTIAL_FACTS.map((fact) => (
                <p key={fact} className="text-[12.5px] text-fg-dim text-pretty">
                  {fact}
                </p>
              ))}
            </div>
          </section>

          {error && !failing && <p className="text-[12.5px] text-danger">{error}</p>}
        </div>
      </div>
    </AppShell>
  );
}
