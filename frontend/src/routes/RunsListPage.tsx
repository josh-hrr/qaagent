import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Button } from "../components/Button";
import { AlertIcon, PlayIcon, SearchIcon, SpinnerIcon } from "../components/icons";
import { ApiError, runsApi, type RunListResponse, type RunStatus, type RunSummary } from "../lib/api";

/** Only while something is running: a finished list does not change on its own. */
const POLL_INTERVAL_MS = 5000;
const PAGE_SIZE = 50;

const STATUS_STYLE: Record<RunStatus, { pill: string; dot: string }> = {
  running: { pill: "border-signal-edge bg-signal-bg text-signal", dot: "bg-signal animate-pulse" },
  queued: { pill: "border-edge-strong bg-ink-500 text-fg-dim", dot: "bg-fg-dim animate-pulse" },
  succeeded: { pill: "border-[#2c400f] bg-[#141c0c] text-signal-dim", dot: "bg-signal-dim" },
  failed: { pill: "border-danger-edge bg-danger-bg text-danger", dot: "bg-danger" },
  cancelled: { pill: "border-edge-strong bg-ink-600 text-fg-dimmer", dot: "bg-fg-dimmer" },
};

const FILTERS: { key: RunStatus | ""; label: string }[] = [
  { key: "", label: "All" },
  { key: "running", label: "Running" },
  { key: "succeeded", label: "Succeeded" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

function when(run: RunSummary): string {
  const iso = run.finishedAt ?? run.startedAt ?? run.createdAt;
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  const days = Math.round(seconds / 86400);
  return days <= 6 ? `${days} d` : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function stageLabel(run: RunSummary): string {
  if (run.status === "succeeded") return "done";
  if (run.status === "queued") return "waiting for the worker";
  return run.stages.find((stage) => stage.key === run.stage)?.label ?? "—";
}

export function RunsListPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<RunListResponse | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const timer = useRef<number | null>(null);

  // Typing filters the list, but not on every keystroke.
  useEffect(() => {
    const id = window.setTimeout(() => setSearch(query.trim()), 250);
    return () => window.clearTimeout(id);
  }, [query]);

  const load = useCallback(async () => {
    try {
      const body = await runsApi.list({ status, q: search, limit });
      setData(body);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load runs.");
    } finally {
      setLoading(false);
    }
  }, [status, search, limit]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  // Keep the running rows honest without hammering the API when nothing moves.
  useEffect(() => {
    if (!data?.activeCount) return;
    timer.current = window.setTimeout(() => void load(), POLL_INTERVAL_MS);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [data, load]);

  const rows = data?.runs ?? [];
  const counts = data?.counts ?? {};
  const shownLine = useMemo(() => {
    if (!data) return "";
    const total = data.total;
    return rows.length >= total ? `${total} run${total === 1 ? "" : "s"}` : `${rows.length} of ${total} shown`;
  }, [data, rows.length]);

  const header = (
    <div className="flex items-center gap-2.5">
      {data && data.activeCount > 0 && (
        <span className="flex h-6 items-center gap-1.75 rounded border border-signal-edge bg-signal-bg px-2 font-mono text-[10.5px] text-signal">
          <span className="size-1.25 animate-pulse rounded-full bg-signal" />
          {data.activeCount} running
        </span>
      )}
      <label className="flex h-7.5 w-62 items-center gap-2 rounded-md border border-edge-field bg-ink-800 px-2.75 focus-within:border-fg-faint">
        <SearchIcon size={13} className="shrink-0 text-fg-faint" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by ticket or title…"
          className="min-w-0 flex-1 bg-transparent text-[12px] text-fg-muted outline-none"
        />
      </label>
      <Link to="/tickets" className="no-underline">
        <Button variant="primary" className="h-7.5 px-3.25 text-[12px]">
          New run
        </Button>
      </Link>
    </div>
  );

  if (!loading && rows.length === 0 && !search && !status) {
    return (
      <AppShell title="Runs" actions={header}>
        <div className="flex flex-1 items-center justify-center px-5">
          <div className="w-130 text-center">
            <div className="mx-auto mb-5 flex size-13.5 items-center justify-center rounded-xl border border-edge-strong bg-ink-800">
              <PlayIcon size={24} className="text-fg-faint" />
            </div>
            <h2 className="mb-2 font-display text-[20px] font-semibold text-fg">No runs yet</h2>
            <p className="mb-5.5 text-[13px] text-fg-dimmer text-pretty">
              A run reads one Linear ticket and the code that implements it, then writes the test cases. Pick a ticket
              to start the first one.
            </p>
            <div className="mb-7 flex items-center justify-center gap-2.5">
              <Link to="/tickets" className="no-underline">
                <Button variant="primary">Pick a ticket</Button>
              </Link>
              <Link to="/connections" className="no-underline">
                <Button variant="secondary">Check connections</Button>
              </Link>
            </div>
            <div className="flex gap-2.5 rounded-lg border border-edge bg-ink-800 px-3.75 py-3.25 text-left">
              <AlertIcon size={15} className="mt-0.5 shrink-0 text-warn" />
              <div>
                <p className="text-[12.5px] text-fg-muted">A run takes a couple of minutes</p>
                <p className="mt-1 text-[11.5px] text-fg-faint text-pretty">
                  It reads the ticket, then the code, then writes. If one stays at{" "}
                  <span className="font-mono text-fg-dim">queued</span> for longer than that, tell whoever looks
                  after QA Agent.
                </p>
              </div>
            </div>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Runs" actions={header}>
      <div className="flex min-h-0 flex-1 flex-col">
        {/* filters */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 px-5 pt-3 pb-2.75">
          {FILTERS.map((filter) => {
            const on = status === filter.key;
            const count = counts[filter.key || "all"];
            return (
              <button
                key={filter.key || "all"}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  setStatus(filter.key);
                  setLimit(PAGE_SIZE);
                }}
                className={`flex h-6.5 cursor-pointer items-center gap-1.75 rounded-[5px] border px-2.25 font-mono text-[11px] ${
                  on ? "border-signal-edge bg-signal-bg text-signal" : "border-edge-field text-fg-dimmer hover:text-fg-muted"
                }`}
              >
                {filter.label}
                <span className={on ? "text-signal" : "text-fg-faint"}>{count ?? "—"}</span>
              </button>
            );
          })}
          <span className="flex-1" />
          {error ? (
            <span className="font-mono text-[11px] text-danger">{error}</span>
          ) : (
            <span className="font-mono text-[11px] text-fg-faint">{shownLine}</span>
          )}
        </div>

        {/* table header */}
        <div className="flex shrink-0 items-center gap-2.5 border-b border-edge px-5 pb-2">
          <span className="label-micro w-11">Run</span>
          <span className="label-micro w-20">Ticket</span>
          <span className="label-micro flex-1">Title</span>
          <span className="label-micro w-23.5">Status</span>
          <span className="label-micro hidden w-32 xl:block">Stage</span>
          <span className="label-micro w-12 text-right">Cases</span>
          <span className="label-micro hidden w-15 text-right lg:block">Findings</span>
          <span className="label-micro w-14.5 text-right">Cost</span>
          <span className="label-micro hidden w-27 lg:block">Model</span>
          <span className="label-micro hidden w-19 xl:block">Started by</span>
          <span className="label-micro w-18 text-right">When</span>
        </div>

        {/* rows */}
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {loading && rows.length === 0 && (
            <div className="flex items-center justify-center gap-3 py-10 text-fg-faint">
              <SpinnerIcon size={16} />
              <span className="text-[13px]">Loading runs…</span>
            </div>
          )}
          {!loading && rows.length === 0 && (
            <p className="py-10 text-center text-[12.5px] text-fg-faint">No runs match that filter.</p>
          )}
          {rows.map((run) => {
            const style = STATUS_STYLE[run.status];
            return (
              <div
                key={run.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(run.status === "succeeded" ? `/runs/${run.id}/review` : `/runs/${run.id}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    navigate(run.status === "succeeded" ? `/runs/${run.id}/review` : `/runs/${run.id}`);
                  }
                }}
                className="flex cursor-pointer items-center gap-2.5 border-b border-b-ink-600 border-l-2 border-l-transparent py-2.75 pr-5 pl-4.5 hover:border-l-edge-strong hover:bg-ink-800"
              >
                <span className="w-11 shrink-0 font-mono text-[11px] text-fg-faint">#{run.id}</span>
                <span className="w-20 truncate font-mono text-[11px] text-info">{run.ticketIdentifier || "—"}</span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-fg-muted">
                  {run.ticketTitle || <span className="text-fg-faint">Reading the ticket…</span>}
                </span>
                <span className="w-23.5">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-[3px] border px-1.5 py-0.5 font-mono text-[10px] ${style.pill}`}
                  >
                    <span className={`size-1.25 rounded-full ${style.dot}`} />
                    {run.status}
                  </span>
                </span>
                <span
                  className={`hidden w-32 truncate font-mono text-[11px] xl:block ${
                    run.status === "running" ? "text-signal" : "text-fg-faint"
                  }`}
                >
                  {stageLabel(run)}
                </span>
                <span
                  className={`w-12 text-right font-mono text-[11.5px] ${run.counts.testCases ? "text-fg-muted" : "text-fg-ghost"}`}
                >
                  {run.counts.testCases || "—"}
                </span>
                <span
                  className={`hidden w-15 text-right font-mono text-[11.5px] lg:block ${
                    run.counts.findings ? "text-warn" : "text-fg-ghost"
                  }`}
                >
                  {run.status === "succeeded" ? run.counts.findings : "—"}
                </span>
                <span className="w-14.5 text-right font-mono text-[11.5px] text-fg-dim">
                  {Number(run.costUsd) > 0 ? `$${Number(run.costUsd).toFixed(2)}` : "—"}
                </span>
                <span className="hidden w-27 truncate font-mono text-[10.5px] text-fg-faint lg:block">{run.model}</span>
                <span className="hidden w-19 truncate font-mono text-[10.5px] text-fg-faint xl:block">
                  {run.createdBy.split("@")[0] || "—"}
                </span>
                <span className="w-18 text-right font-mono text-[10.5px] text-fg-faint">{when(run)}</span>
              </div>
            );
          })}

          {data && rows.length < data.total && (
            <div className="flex justify-center py-4">
              <Button variant="secondary" onClick={() => setLimit((current) => current + PAGE_SIZE)}>
                Load more
              </Button>
            </div>
          )}
        </div>

        {/* footer */}
        <div className="flex shrink-0 items-center gap-3 border-t border-edge bg-ink-800 px-5 py-2.5">
          <span className="font-mono text-[11px] text-fg-faint">
            Every run keeps what it read: ticket snapshot, diff scope, files and cost.
          </span>
          <span className="flex-1" />
          {data && (
            <span className="font-mono text-[11px] text-fg-faint">
              {data.counts.all ?? 0} runs · ${Number(data.spend.spentUsd).toFixed(2)} this month
            </span>
          )}
        </div>
      </div>
    </AppShell>
  );
}
