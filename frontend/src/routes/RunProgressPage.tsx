import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Button } from "../components/Button";
import {
  AlertIcon,
  BranchIcon,
  CheckIcon,
  ExternalLinkIcon,
  SpinnerIcon,
} from "../components/icons";
import { ApiError, runsApi, type RunDetail, type StageState } from "../lib/api";

/** Polls our own API, never Linear or Azure — the worker does those calls once. */
const POLL_INTERVAL_MS = 2000;

/** What a person can actually do about each failure. */
const REMEDIATION: Record<string, { hint: string; to?: string; cta?: string }> =
  {
    no_pull_request: {
      hint: "Paste the pull request link into a comment on the ticket in Linear, or put the ticket ID in the branch name, then run again.",
      to: "/tickets",
      cta: "Back to tickets",
    },
    no_usable_pull_request: {
      hint: "Every linked pull request was skipped. Connect the repository it lives in, or link a PR that is not abandoned.",
      to: "/repositories",
      cta: "Check repositories",
    },
    source_not_connected: {
      hint: "Connect Azure DevOps first.",
      to: "/repositories",
      cta: "Connect repository",
    },
    linear_not_connected: {
      hint: "Connect Linear first.",
      to: "/connections",
      cta: "Connect Linear",
    },
    invalid_token: {
      hint: "The Azure DevOps token was rejected or has expired. Replace it on the repository screen.",
      to: "/repositories",
      cta: "Replace token",
    },
    invalid_key: {
      hint: "The Linear API key was rejected. Replace it on the Linear screen.",
      to: "/connections",
      cta: "Replace key",
    },
    llm_auth: {
      hint: "QA Agent cannot reach the model it writes test cases with. Tell whoever looks after it.",
    },
    llm_not_configured: {
      hint: "Test case generation is not set up yet in this workspace. Tell whoever looks after QA Agent.",
    },
    llm_model_not_found: {
      hint: "The workspace is set to a model that no longer exists. Tell whoever looks after QA Agent.",
    },
    llm_rate_limited: {
      hint: "The model is rate limiting requests. Wait a minute and run again.",
    },
  };

const STAGE_STYLES: Record<
  StageState,
  { dot: string; ring: string; text: string }
> = {
  done: {
    dot: "bg-signal",
    ring: "border-signal-edge bg-signal-bg",
    text: "text-fg-muted",
  },
  running: {
    dot: "bg-signal animate-pulse",
    ring: "border-signal",
    text: "text-fg-bright font-semibold",
  },
  queued: {
    dot: "bg-fg-ghost",
    ring: "border-edge-strong",
    text: "text-fg-faint",
  },
  failed: {
    dot: "bg-danger",
    ring: "border-danger-edge bg-danger-bg",
    text: "text-fg-bright font-semibold",
  },
  cancelled: {
    dot: "bg-fg-faint",
    ring: "border-edge-strong",
    text: "text-fg-muted",
  },
  skipped: { dot: "bg-fg-ghost", ring: "border-edge", text: "text-fg-ghost" },
};

/** Right-hand state word per stage, coloured as in the mockup. */
const STATE_LABEL: Record<StageState, string> = {
  done: "text-fg-faint",
  running: "text-signal",
  queued: "text-fg-ghost",
  failed: "text-danger",
  cancelled: "text-fg-dim",
  skipped: "text-fg-ghost",
};

function tokens(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

function elapsed(run: RunDetail): string {
  if (!run.startedAt) return "queued";
  const end = run.finishedAt ? new Date(run.finishedAt).getTime() : Date.now();
  const seconds = Math.max(
    0,
    Math.round((end - new Date(run.startedAt).getTime()) / 1000),
  );
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function RunProgressPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | null>(null);

  const poll = useCallback(async () => {
    try {
      const { run: latest } = await runsApi.get(runId);
      setRun(latest);
      setError(null);
      if (!latest.isTerminal) {
        timer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err
          : new ApiError("Could not load this run.", { status: 0 }),
      );
      // Keep trying — a dev server restart should not strand the page.
      timer.current = window.setTimeout(
        () => void poll(),
        POLL_INTERVAL_MS * 3,
      );
    }
  }, [runId]);

  useEffect(() => {
    void poll();
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [poll]);

  async function cancel() {
    if (!run || cancelling) return;
    setCancelling(true);
    try {
      await runsApi.cancel(run.id);
    } catch {
      // The next poll shows the real state either way.
    } finally {
      setCancelling(false);
    }
  }

  if (!run) {
    return (
      <AppShell title="Run">
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          {error ? (
            <span className="text-[13px] text-danger">{error.message}</span>
          ) : (
            <>
              <SpinnerIcon size={18} />
              <span className="text-[13px]">Loading run…</span>
            </>
          )}
        </div>
      </AppShell>
    );
  }

  const running = run.status === "running" || run.status === "queued";
  const cost = Number(run.costUsd);
  const cap = Number(run.costCapUsd) || 1;
  const remedy = REMEDIATION[run.errorCode];
  const agentFiles = run.filesRead.filter((f) => f.source === "agent");
  const doneStages = run.stages.filter(
    (stage) => stage.state === "done",
  ).length;
  const progress =
    run.status === "succeeded"
      ? 100
      : Math.round((doneStages / run.stages.length) * 100);
  const diffFiles = run.filesRead.filter((f) => f.source === "diff");

  // Full height beside the header, not under it — matches the design.
  const sidePanel = (
    <aside className="w-full shrink-0 overflow-y-auto border-t border-edge bg-ink-800 px-4.5 py-4.5 xl:w-80 xl:border-t-0 xl:border-l">
      <p className="label-micro mb-2.5">Produced</p>
      <div className="mb-5 grid grid-cols-2 gap-2">
        {[
          {
            k: "cases drafted",
            v: String(run.counts.testCases),
            color: run.counts.testCases ? "text-fg" : "text-fg-ghost",
          },
          {
            k: "ac covered",
            // Unknown until test cases exist — "— / 6", never a false 0.
            v:
              run.counts.criteriaTotal === 0
                ? "—"
                : `${run.counts.criteriaCovered ?? "—"} / ${run.counts.criteriaTotal}`,
            color:
              run.counts.criteriaCovered !== null &&
              run.counts.criteriaTotal > 0
                ? "text-signal"
                : "text-fg-ghost",
          },
          {
            k: "code findings",
            v: String(run.counts.findings),
            color: run.counts.findings ? "text-warn" : "text-fg-ghost",
          },
          {
            k: "questions",
            v: String(run.counts.ambiguities),
            color: run.counts.ambiguities ? "text-warn" : "text-fg-ghost",
          },
        ].map((item) => (
          <div
            key={item.k}
            className="rounded-lg border border-edge bg-ink-700 px-3 py-2.5"
          >
            <p
              className={`font-display text-[21px] font-semibold ${item.color}`}
            >
              {item.v}
            </p>
            <p className="font-mono text-[10px] tracking-[0.06em] text-fg-faint uppercase">
              {item.k}
            </p>
          </div>
        ))}
      </div>

      {run.pullRequests.length > 0 && (
        <>
          <p className="label-micro mb-2">Pull requests</p>
          <ul className="mb-5 flex flex-col gap-1.5">
            {run.pullRequests.map((pr) => (
              <li key={pr.url}>
                <a
                  href={pr.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 rounded-md border border-edge bg-ink-700 px-2.5 py-2 no-underline hover:border-edge-strong"
                >
                  <BranchIcon size={12} className="shrink-0 text-fg-faint" />
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted">
                    #{pr.number} · {pr.repository}
                  </span>
                  <span className="font-mono text-[10px] text-fg-faint">
                    {pr.status}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </>
      )}

      {(diffFiles.length > 0 || agentFiles.length > 0) && (
        <>
          <p className="label-micro mb-2">Reading</p>
          <ul className="mb-5 flex flex-col gap-1.5">
            {diffFiles.map((f) => (
              <li
                key={`d-${f.path}`}
                className="rounded-md border border-edge bg-ink-700 px-2.5 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="size-1.5 shrink-0 rounded-full bg-signal" />
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-dim">
                    {f.path}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-fg-faint">
                    +{f.linesAdded} −{f.linesRemoved}
                  </span>
                </div>
              </li>
            ))}
            {agentFiles.map((f) => (
              <li
                key={`a-${f.path}`}
                className="rounded-md border border-edge bg-ink-700 px-2.5 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="size-1.5 shrink-0 rounded-full bg-info" />
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-dim">
                    {f.path}
                  </span>
                </div>
                {/* Why the agent pulled this file in — see decision 0001. */}
                <p className="mt-1 text-[11px] text-fg-faint text-pretty">
                  {f.reason}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="label-micro mb-2">Budget</p>
      <div className="rounded-lg border border-edge bg-ink-700 px-3 py-3">
        <div className="mb-2 flex items-baseline gap-1.5">
          <span className="font-display text-[18px] font-semibold text-fg">
            ${cost.toFixed(3)}
          </span>
          <span className="font-mono text-[10px] text-fg-faint">
            of ${cap.toFixed(2)} per-run cap
          </span>
        </div>
        <div className="mb-2.5 h-0.75 overflow-hidden rounded-full bg-edge">
          <div
            className="h-0.75 bg-signal"
            style={{ width: `${Math.min(100, (cost / cap) * 100)}%` }}
          />
        </div>
        <dl className="flex flex-col gap-1 font-mono text-[11px]">
          <div className="flex justify-between">
            <dt className="text-fg-faint">model</dt>
            <dd className="text-fg-muted text-right">{run.model || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-faint">input</dt>
            <dd className="text-fg-muted">
              {tokens(
                run.tokens.input + run.tokens.cacheRead + run.tokens.cacheWrite,
              )}{" "}
              tokens
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-faint">cached</dt>
            <dd className="text-signal">
              {tokens(run.tokens.cacheRead)} reused
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-[11px] text-fg-faint">
          Cost is recorded when generation finishes.
        </p>
      </div>
    </aside>
  );

  return (
    <AppShell
      title="Run"
      subtitle={
        <span>
          <Link to="/tickets" className="text-fg-faint hover:text-fg-dim">
            tickets
          </Link>{" "}
          / {run.ticketIdentifier || "…"} / run #{run.id}
        </span>
      }
      actions={
        <div className="flex items-center gap-2.5">
          <StatusPill run={run} />
          {running && (
            <button
              type="button"
              onClick={() => void cancel()}
              disabled={cancelling}
              className="flex h-7 cursor-pointer items-center rounded-md border border-edge-strong px-2.75 text-[12px] text-fg-dim transition-colors hover:border-fg-faint hover:text-fg-muted disabled:cursor-default disabled:opacity-60"
            >
              {cancelling ? "Cancelling…" : "Cancel run"}
            </button>
          )}
        </div>
      }
      aside={sidePanel}
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {/* --- pipeline --- */}
        <div className="min-w-0 flex-1 overflow-y-auto px-6 py-8">
          <div className="mx-auto max-w-190">
            <h1 className="mb-1.5 font-display text-[24px] font-semibold text-fg-bright">
              {run.status === "succeeded"
                ? "Test cases ready"
                : run.status === "failed"
                  ? "This run could not finish"
                  : run.status === "cancelled"
                    ? "Run cancelled"
                    : "Generating test cases"}
            </h1>
            <p className="mb-2 flex flex-wrap items-center gap-x-2 text-[13.5px] text-fg-dimmer">
              <span>{run.ticketTitle || "Reading the ticket…"}</span>
              {run.ticketUrl && (
                <a
                  href={run.ticketUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 font-mono text-[11px] text-fg-faint hover:text-fg-dim"
                >
                  Linear <ExternalLinkIcon size={11} />
                </a>
              )}
            </p>

            <div className="mb-6.5 flex items-center gap-2.5">
              <div className="h-0.75 flex-1 overflow-hidden rounded-full bg-edge">
                <div
                  className={`h-0.75 transition-[width] duration-500 ${run.status === "failed" ? "bg-danger" : "bg-signal"}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="w-18.5 text-right font-mono text-[11px] text-fg-dimmer">
                {progress}%
              </span>
            </div>

            {run.status === "failed" && (
              <div className="mb-6 rounded-[10px] border border-danger-edge bg-danger-bg px-4 py-3.5">
                <div className="mb-1 flex items-center gap-2 text-danger">
                  <AlertIcon size={16} />
                  <span className="font-mono text-[11px] tracking-[0.06em] uppercase">
                    {run.errorCode.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="text-[13px] text-fg-muted text-pretty">
                  {run.errorMessage}
                </p>
                {remedy && (
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <p className="flex-1 text-[12.5px] text-fg-dim text-pretty">
                      {remedy.hint}
                    </p>
                    {remedy.to && (
                      <Link to={remedy.to} className="no-underline">
                        <Button variant="secondary">{remedy.cta}</Button>
                      </Link>
                    )}
                  </div>
                )}
              </div>
            )}

            {run.stoppedEarly && (
              <div className="mb-6 flex gap-2.5 rounded-[10px] border border-warn-edge bg-warn-bg px-4 py-3">
                <AlertIcon size={15} className="mt-0.5 shrink-0 text-warn" />
                <p className="text-[12.5px] text-fg-muted text-pretty">
                  Exploration stopped early ({run.stoppedEarlyReason}). The test
                  cases are built from what was read before that point —
                  coverage of code outside the diff may be incomplete.
                </p>
              </div>
            )}

            <ol className="mb-8">
              {run.stages.map((stage, index) => {
                const style = STAGE_STYLES[stage.state];
                const last = index === run.stages.length - 1;
                const stageEvents = run.events.filter(
                  (e) => e.stage === stage.key,
                );
                return (
                  <li key={stage.key} className="flex gap-3.5">
                    <div className="flex w-5.5 shrink-0 flex-col items-center">
                      <span
                        className={`flex size-5.5 items-center justify-center rounded-full border ${style.ring}`}
                      >
                        {stage.state === "done" ? (
                          <CheckIcon size={11} className="text-signal" />
                        ) : (
                          <span
                            className={`size-2 rounded-full ${style.dot}`}
                          />
                        )}
                      </span>
                      {!last && (
                        <span
                          className={`w-px flex-1 ${stage.state === "done" ? "bg-signal-edge" : "bg-edge"}`}
                        />
                      )}
                    </div>
                    <div className={`min-w-0 flex-1 ${last ? "" : "pb-5"}`}>
                      <div className="flex items-center gap-2">
                        <span className={`text-[13.5px] ${style.text}`}>
                          {stage.label}
                        </span>
                        <span className="flex-1" />
                        <span
                          className={`font-mono text-[11px] ${STATE_LABEL[stage.state]}`}
                        >
                          {stage.state}
                        </span>
                      </div>
                      {stageEvents.length > 0 && (
                        <ul className="mt-2 rounded-md border border-edge bg-ink-900 px-3 py-2">
                          {stageEvents.map((event, i) => (
                            <li
                              key={i}
                              className="font-mono text-[11px] leading-relaxed break-words text-fg-dimmer"
                            >
                              {event.message}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>

            {run.status === "succeeded" && (
              <div className="flex flex-wrap items-center gap-3 rounded-[10px] border border-signal-edge bg-[#121710] px-5 py-4">
                <p className="flex-1 text-[13px] text-fg-muted">
                  {run.counts.testCases} test cases · {run.counts.findings} code
                  findings · {run.counts.ambiguities} open questions
                </p>
                <Link to={`/runs/${run.id}/review`} className="no-underline">
                  <Button variant="primary">Review test cases</Button>
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function StatusPill({ run }: { run: RunDetail }) {
  const styles: Record<string, string> = {
    queued: "border-edge-strong text-fg-dim",
    running: "border-signal-edge bg-signal-bg text-signal",
    succeeded: "border-signal-edge bg-signal-bg text-signal",
    failed: "border-danger-edge bg-danger-bg text-danger",
    cancelled: "border-edge-strong text-fg-dim",
  };
  return (
    <span
      className={`flex h-7 items-center gap-1.75 rounded-md border px-2.75 font-mono text-[11px] ${styles[run.status]}`}
    >
      <span
        className={`size-1.5 rounded-full bg-current ${run.status === "running" || run.status === "queued" ? "animate-pulse" : ""}`}
      />
      {run.status === "queued"
        ? "queued — is the worker running?"
        : `${run.status} · ${elapsed(run)}`}
    </span>
  );
}
