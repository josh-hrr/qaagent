import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import {
  AlertIcon,
  BranchIcon,
  CheckIcon,
  ChevronDownIcon,
  DownloadIcon,
  ExternalLinkIcon,
  QuestionIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
} from "../components/icons";
import {
  ApiError,
  reviewApi,
  runsApi,
  type BulkAction,
  type DriftResponse,
  type Priority,
  type ReviewAmbiguity,
  type ReviewFinding,
  type ReviewResponse,
  type ReviewTestCase,
  type TestCaseStatus,
  type TestCaseUpdate,
} from "../lib/api";

/* --- look-up tables, straight from the mockup ------------------------------ */

const PRIORITY_STYLE: Record<Priority, string> = {
  P1: "text-danger bg-danger-bg border-danger-edge",
  P2: "text-warn bg-warn-bg border-warn-edge",
  P3: "text-fg-dim bg-ink-500 border-edge-strong",
};

const STATUS_STYLE: Record<TestCaseStatus, { pill: string; dot: string; label: string }> = {
  ready: { pill: "text-signal bg-signal-bg border-signal-edge", dot: "bg-signal", label: "ready" },
  approved: { pill: "text-ink-900 bg-signal border-signal", dot: "bg-signal", label: "approved" },
  draft: { pill: "text-fg-dim bg-ink-500 border-edge-strong", dot: "bg-fg-dim", label: "draft" },
  needs_info: { pill: "text-warn bg-warn-bg border-warn-edge", dot: "bg-warn", label: "needs info" },
  rejected: { pill: "text-danger bg-danger-bg border-danger-edge", dot: "bg-danger", label: "rejected" },
};

const STATUSES: TestCaseStatus[] = ["draft", "ready", "needs_info", "approved", "rejected"];
const PRIORITIES: Priority[] = ["P1", "P2", "P3"];
const TEST_TYPES = ["functional", "negative", "edge", "regression", "security", "accessibility", "performance"];

const SEVERITY_STYLE: Record<ReviewFinding["severity"], { text: string; chip: string; border: string; dot: string }> = {
  high: { text: "text-danger", chip: "bg-danger-bg border-danger-edge", border: "border-danger-edge", dot: "bg-danger" },
  medium: { text: "text-warn", chip: "bg-warn-bg border-warn-edge", border: "border-warn-edge", dot: "bg-warn" },
  low: { text: "text-info", chip: "bg-info-bg border-info-edge", border: "border-info-edge", dot: "bg-info" },
};

type Tab = "cases" | "findings" | "questions";
type Chip = "all" | "p1" | "regression" | "needs_info";

/* --- small helpers --------------------------------------------------------- */

function ago(iso: string | null): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function money(value: string): string {
  const n = Number(value);
  return `$${n > 0 && n < 0.01 ? n.toFixed(3) : n.toFixed(2)}`;
}

/** "/api/auth/views.py:118" → "views.py:118" — the row has no room for paths. */
function shortTrace(label: string): string {
  return label.includes("/") ? label.slice(label.lastIndexOf("/") + 1) : label;
}

const tcId = (n: number) => `TC-${String(n).padStart(3, "0")}`;

function byPriority(a: ReviewTestCase, b: ReviewTestCase): number {
  return a.priority.localeCompare(b.priority) || a.number - b.number;
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/* --- page ------------------------------------------------------------------ */

export function ReviewWorkspacePage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState<ReviewResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [drift, setDrift] = useState<DriftResponse | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftError, setDriftError] = useState("");

  const [tab, setTab] = useState<Tab>("cases");
  const [chip, setChip] = useState<Chip>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState("");
  const [rerunning, setRerunning] = useState(false);
  const noticeTimer = useRef<number | null>(null);

  const flash = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(""), 3500);
  }, []);

  const checkDrift = useCallback(async () => {
    setDriftLoading(true);
    setDriftError("");
    try {
      setDrift(await reviewApi.drift(runId));
    } catch (err) {
      setDriftError(errorText(err, "Could not check for changes."));
    } finally {
      setDriftLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    reviewApi
      .get(runId)
      .then((body) => {
        if (cancelled) return;
        setData(body);
        setSelected([...body.testCases].sort(byPriority)[0]?.number ?? null);
        // Once on open. Never on a timer: each check calls Linear and Azure.
        if (body.run.status === "succeeded") void checkDrift();
      })
      .catch((err) => !cancelled && setLoadError(errorText(err, "Could not load this run.")));
    return () => {
      cancelled = true;
    };
  }, [runId, checkDrift]);

  /* --- derived --- */

  const cases = useMemo(() => [...(data?.testCases ?? [])].sort(byPriority), [data]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cases.filter((c) => {
      if (chip === "p1" && c.priority !== "P1") return false;
      if (chip === "regression" && c.testType !== "regression") return false;
      if (chip === "needs_info" && c.status !== "needs_info") return false;
      if (!q) return true;
      return (
        c.title.toLowerCase().includes(q) ||
        c.identifier.toLowerCase().includes(q) ||
        c.tracesTo.some((t) => t.label.toLowerCase().includes(q))
      );
    });
  }, [cases, chip, query]);

  if (!data) {
    return (
      <AppShell subtitle={<span>runs / run #{runId}</span>}>
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          {loadError ? (
            <span className="text-[13px] text-danger">{loadError}</span>
          ) : (
            <>
              <SpinnerIcon size={18} />
              <span className="text-[13px]">Loading review…</span>
            </>
          )}
        </div>
      </AppShell>
    );
  }

  const { run } = data;
  const finished = run.status === "succeeded";
  const current = cases.find((c) => c.number === selected) ?? null;
  const openFindings = data.findings.filter((f) => !f.dismissed);
  const openQuestions = data.ambiguities.filter((a) => !a.answer);
  const needsInfo = cases.filter((c) => c.status === "needs_info").length;

  /* --- mutations --- */

  function replaceCase(updated: ReviewTestCase) {
    setData((prev) =>
      prev && {
        ...prev,
        testCases: prev.testCases.map((c) => (c.number === updated.number ? updated : c)),
      },
    );
  }

  async function updateCase(number: number, changes: TestCaseUpdate): Promise<boolean> {
    try {
      const { testCase } = await reviewApi.updateTestCase(run.id, number, changes);
      replaceCase(testCase);
      return true;
    } catch (err) {
      flash(errorText(err, "Could not save the change."));
      return false;
    }
  }

  async function bulk(numbers: number[], action: BulkAction) {
    if (numbers.length === 0) return;
    if (action.action === "delete" && !window.confirm(`Delete ${numbers.length} test case(s)? This cannot be undone.`)) return;
    try {
      const body = await reviewApi.bulk(run.id, numbers, action);
      setData(body);
      if (action.action === "delete") {
        setChecked(new Set());
        if (selected !== null && numbers.includes(selected)) setSelected(null);
      }
      flash(`${body.updated} test case(s) updated`);
    } catch (err) {
      flash(errorText(err, "Bulk action failed."));
    }
  }

  async function addFinding(finding: ReviewFinding) {
    try {
      const body = await reviewApi.findingToTestCase(run.id, finding.id);
      setData(body);
      setSelected(body.testCase.number);
      setTab("cases");
      setChip("all");
      setQuery("");
      flash(`Added as ${body.testCase.identifier}`);
    } catch (err) {
      flash(errorText(err, "Could not add the test case."));
    }
  }

  async function dismissFinding(finding: ReviewFinding, dismissed: boolean) {
    try {
      const { finding: updated } = await reviewApi.dismissFinding(run.id, finding.id, dismissed);
      setData((prev) => prev && { ...prev, findings: prev.findings.map((f) => (f.id === updated.id ? updated : f)) });
    } catch (err) {
      flash(errorText(err, "Could not update the finding."));
    }
  }

  async function answerQuestion(item: ReviewAmbiguity, answer: string): Promise<boolean> {
    try {
      const { ambiguity } = await reviewApi.answer(run.id, item.id, answer);
      setData((prev) => prev && { ...prev, ambiguities: prev.ambiguities.map((a) => (a.id === ambiguity.id ? ambiguity : a)) });
      return true;
    } catch (err) {
      flash(errorText(err, "Could not save the answer."));
      return false;
    }
  }

  async function rerun() {
    setRerunning(true);
    try {
      const { run: next } = await runsApi.start(run.ticketLinearId, run.ticketIdentifier);
      navigate(`/runs/${next.id}`);
    } catch (err) {
      flash(errorText(err, "Could not start a new run."));
      setRerunning(false);
    }
  }

  async function copyText(text: string, what: string) {
    flash((await copy(text)) ? `${what} copied — paste it into Linear` : "Copy failed — your browser blocked the clipboard");
  }

  function toggle(number: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      return next;
    });
  }

  /* --- drift summary --- */

  const ticketDrift = drift?.ticket && !("error" in drift.ticket) && drift.ticket.changed ? drift.ticket : null;
  const ticketDriftParts = ticketDrift
    ? [
        ticketDrift.titleChanged && "title edited",
        ticketDrift.descriptionChanged && "description edited",
        ticketDrift.criteriaAdded.length > 0 && `${ticketDrift.criteriaAdded.join(", ")} added`,
        ticketDrift.criteriaRemoved.length > 0 && `${ticketDrift.criteriaRemoved.join(", ")} removed`,
        ticketDrift.criteriaEdited.length > 0 && `${ticketDrift.criteriaEdited.join(", ")} reworded`,
        ticketDrift.pullRequestsAdded.length > 0 && `${ticketDrift.pullRequestsAdded.length} pull request(s) linked`,
        ticketDrift.pullRequestsRemoved.length > 0 && `${ticketDrift.pullRequestsRemoved.length} pull request(s) unlinked`,
      ].filter(Boolean)
    : [];
  const commitsAhead = (drift?.code ?? []).reduce((sum, c) => sum + ("commitsAhead" in c ? c.commitsAhead : 0), 0);
  const codeErrors = (drift?.code ?? []).filter((c): c is { label?: string; error: string } => "error" in c);
  const ticketError = drift?.ticket && "error" in drift.ticket ? drift.ticket.error : "";

  const countLine =
    tab === "cases"
      ? `${shown.length} of ${cases.length} shown · sorted by priority`
      : tab === "findings"
        ? `${openFindings.length} finding${openFindings.length === 1 ? "" : "s"} · ${openFindings.filter((f) => f.severity === "high").length} high`
        : `${openQuestions.length} open question${openQuestions.length === 1 ? "" : "s"}`;

  const checkedList = [...checked].filter((n) => cases.some((c) => c.number === n));

  /* --- render --- */

  return (
    <AppShell
      fill
      subtitle={
        <span className="flex items-center gap-2.5">
          <span className="text-fg-faint">runs</span>
          <span className="text-fg-ghost">/</span>
          <span className="text-fg-muted">{run.ticketIdentifier}</span>
          <span className="text-fg-ghost">/</span>
          <Link to={`/runs/${run.id}`} className="text-fg-faint hover:text-fg-dim" title="Open the run log">
            run #{run.runNumber}
          </Link>
        </span>
      }
      actions={
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => void rerun()}
            disabled={rerunning}
            className="flex h-7.5 cursor-pointer items-center gap-1.5 rounded-md border border-edge-strong px-2.75 text-[12px] text-fg-dim transition-colors hover:border-fg-faint hover:text-fg-muted disabled:cursor-default disabled:opacity-60"
          >
            {rerunning ? <SpinnerIcon size={14} /> : <RefreshIcon size={14} />}
            Re-run on latest commit
          </button>
          {/* Export is screen 07 — drawn disabled, not as a dead button. */}
          <button
            type="button"
            disabled
            title="Export arrives with screen 07"
            className="flex h-7.5 cursor-not-allowed items-center gap-1.75 rounded-md bg-edge px-3.25 text-[12px] font-semibold text-fg-faint"
          >
            <DownloadIcon size={14} />
            Export
          </button>
        </div>
      }
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {/* --- run header --- */}
        <div className="shrink-0 px-5 pt-4.5">
          <div className="flex flex-wrap items-start gap-3.5">
            <div className="min-w-0 flex-1">
              <div className="mb-1.75 flex flex-wrap items-center gap-2.25">
                {run.ticketUrl ? (
                  <a
                    href={run.ticketUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-[3px] border border-info-edge bg-info-bg px-1.5 py-0.5 font-mono text-[10px] text-info hover:text-info"
                  >
                    {run.ticketIdentifier}
                  </a>
                ) : (
                  <span className="rounded-[3px] border border-info-edge bg-info-bg px-1.5 py-0.5 font-mono text-[10px] text-info">
                    {run.ticketIdentifier}
                  </span>
                )}
                <span className="font-mono text-[11px] text-fg-faint">Linear{run.teamName ? ` · ${run.teamName}` : ""}</span>
                <span className="size-0.75 rounded-full bg-fg-ghost" />
                <span className="font-mono text-[11px] text-fg-faint">generated {ago(run.finishedAt ?? run.createdAt)}</span>
              </div>
              <h1 className="font-display text-[21px] font-semibold tracking-[-0.015em] text-fg">{run.ticketTitle}</h1>
            </div>
            <div className="flex shrink-0 gap-2">
              <Stat label="Coverage" tone={run.criteriaTotal > 0 && run.criteriaCovered !== null ? "text-signal" : "text-fg-faint"}>
                {run.criteriaTotal === 0 ? "no AC" : `${run.criteriaCovered ?? "—"} / ${run.criteriaTotal} AC`}
              </Stat>
              <Stat label="Diff scope">{run.diff.files} files</Stat>
              <Stat label="Cost">{money(run.costUsd)}</Stat>
            </div>
          </div>

          {/* --- ticket drift banner --- */}
          {ticketDrift && (
            <div className="mt-3.5 flex flex-wrap items-center gap-3 rounded-[7px] border border-warn-edge bg-warn-bg px-3.25 py-2.25">
              <AlertIcon size={15} className="shrink-0 text-warn" />
              <p className="min-w-0 flex-1 text-[12.5px] text-fg-muted">
                {run.ticketIdentifier} changed since this run{ticketDriftParts.length ? `: ${ticketDriftParts.join(", ")}` : ""}.
              </p>
              <button
                type="button"
                onClick={() => void rerun()}
                disabled={rerunning}
                className="h-6.5 cursor-pointer rounded-[5px] border border-warn-edge px-2.5 text-[11.5px] text-warn hover:border-warn disabled:cursor-default disabled:opacity-60"
              >
                Re-run with latest ticket
              </button>
            </div>
          )}

          {run.stoppedEarly && (
            <div className="mt-3.5 flex items-center gap-2.5 rounded-[7px] border border-warn-edge bg-warn-bg px-3.25 py-2.25">
              <AlertIcon size={15} className="shrink-0 text-warn" />
              <p className="text-[12.5px] text-fg-muted">
                Stopped early ({run.stoppedEarlyReason}). Coverage outside the diff may be incomplete.
              </p>
            </div>
          )}

          {/* --- source strip --- */}
          {run.scope && (
            <div className="mt-3.5 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 rounded-[7px] border border-edge bg-ink-800 px-3.25 py-2.25 font-mono text-[11px]">
              <span className="flex min-w-0 items-center gap-1.75">
                <BranchIcon size={14} className="shrink-0 text-fg-faint" />
                <span className="truncate text-fg-muted">{run.scope.sourceRef || `PR #${run.scope.number}`}</span>
              </span>
              {run.scope.targetRef && (
                <>
                  <span className="text-fg-ghost">→</span>
                  <span className="text-fg-faint">{run.scope.targetRef}</span>
                </>
              )}
              {run.scope.kind === "pull_request" && run.scope.number !== null && run.scope.sourceRef && (
                <span className="text-fg-faint">PR #{run.scope.number}</span>
              )}
              <Divider />
              <span className="text-fg-faint">azure-devops · {run.scope.repository}</span>
              <Divider />
              <span>
                <span className="text-signal">+{run.diff.linesAdded}</span>{" "}
                <span className="text-danger">−{run.diff.linesRemoved}</span>
              </span>
              <Divider />
              <span className="text-fg-faint">head {run.scope.headCommit.slice(0, 7)}</span>
              <span className="flex-1" />
              {driftLoading ? (
                <span className="flex items-center gap-1.5 text-fg-faint">
                  <SpinnerIcon size={12} /> checking for changes…
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  {driftError || ticketError || codeErrors.length > 0 ? (
                    <span
                      className="text-danger"
                      title={[driftError, ticketError && `Linear: ${ticketError}`, ...codeErrors.map((e) => `${e.label ?? "Azure"}: ${e.error}`)]
                        .filter(Boolean)
                        .join("\n")}
                    >
                      {driftError || ticketError || codeErrors[0]?.error}
                    </span>
                  ) : drift ? (
                    commitsAhead > 0 ? (
                      <span className="text-warn">
                        {commitsAhead} commit{commitsAhead === 1 ? "" : "s"} ahead of this run
                      </span>
                    ) : (
                      <span className="text-fg-faint">up to date</span>
                    )
                  ) : null}
                  {finished && (
                    <button
                      type="button"
                      onClick={() => void checkDrift()}
                      title="Check Linear and Azure DevOps again"
                      aria-label="Check for changes again"
                      className="flex size-5.5 cursor-pointer items-center justify-center rounded text-fg-faint hover:bg-ink-500 hover:text-fg-muted"
                    >
                      <RefreshIcon size={12} />
                    </button>
                  )}
                </span>
              )}
            </div>
          )}

          {/* --- tabs --- */}
          <div role="tablist" className="mt-4 flex gap-6.5 border-b border-edge">
            {(
              [
                { key: "cases", label: "Test cases", count: cases.length },
                { key: "findings", label: "Code findings", count: openFindings.length },
                { key: "questions", label: "Ambiguities", count: openQuestions.length },
              ] as const
            ).map((t) => {
              const on = t.key === tab;
              return (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px flex cursor-pointer items-center gap-2 border-b-2 px-px pb-2.75 text-[13px] ${
                    on ? "border-signal font-semibold text-fg" : "border-transparent text-fg-dimmer hover:text-fg-muted"
                  }`}
                >
                  {t.label}
                  <span
                    className={`rounded-[3px] px-1.25 py-px font-mono text-[10px] font-normal ${
                      on ? "bg-signal text-ink-900" : "bg-edge text-fg-dimmer"
                    }`}
                  >
                    {t.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* --- split body --- */}
        <div className="flex min-h-0 flex-1 flex-col xl:flex-row">
          {/* centre */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {/* toolbar */}
            <div className="flex shrink-0 flex-wrap items-center gap-2.5 px-5 pt-3 pb-2.5">
              {tab === "cases" && (
                <>
                  <label className="flex h-7.5 w-58 items-center gap-2 rounded-md border border-edge-field bg-ink-800 px-2.75 focus-within:border-fg-faint">
                    <SearchIcon size={13} className="shrink-0 text-fg-faint" />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Filter test cases…"
                      className="min-w-0 flex-1 bg-transparent text-[12px] text-fg-muted outline-none"
                    />
                  </label>
                  {(
                    [
                      { key: "all", label: `All ${cases.length}` },
                      { key: "p1", label: "P1 only" },
                      { key: "regression", label: "Regression" },
                      { key: "needs_info", label: `Needs info ${needsInfo}` },
                    ] as const
                  ).map((c) => (
                    <button
                      key={c.key}
                      type="button"
                      aria-pressed={chip === c.key}
                      onClick={() => setChip(c.key)}
                      className={`flex h-6.5 cursor-pointer items-center rounded-[5px] border px-2.25 font-mono text-[11px] ${
                        chip === c.key
                          ? "border-signal-edge bg-signal-bg text-signal"
                          : "border-edge-field text-fg-dimmer hover:text-fg-muted"
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                </>
              )}
              <span className="flex-1" />
              <span className="font-mono text-[11px] text-fg-faint">{countLine}</span>
            </div>

            {tab === "cases" && (
              <CasesTable
                cases={shown}
                selected={selected}
                checked={checked}
                onSelect={setSelected}
                onToggle={toggle}
                onToggleAll={() =>
                  setChecked((prev) =>
                    shown.every((c) => prev.has(c.number)) ? new Set() : new Set(shown.map((c) => c.number)),
                  )
                }
              />
            )}

            {tab === "findings" && (
              <div className="scrollbar-thin flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-5 pt-1 pb-5">
                {data.findings.length === 0 && <Empty>No code findings on this run.</Empty>}
                {[...openFindings, ...data.findings.filter((f) => f.dismissed)].map((finding) => (
                  <FindingCard
                    key={finding.id}
                    finding={finding}
                    ticket={run.ticketIdentifier}
                    editable={finished}
                    onAdd={() => void addFinding(finding)}
                    onOpenCase={(n) => {
                      setSelected(n);
                      setTab("cases");
                    }}
                    onCopy={() =>
                      void copyText(
                        [
                          `QA review of ${run.ticketIdentifier} flagged a possible issue:`,
                          "",
                          `**${finding.title}** (${finding.severity})`,
                          finding.location && `Location: ${finding.locationUrl || finding.location}`,
                          "",
                          finding.explanation,
                        ]
                          .filter((line) => typeof line === "string")
                          .join("\n"),
                        "Comment",
                      )
                    }
                    onDismiss={(dismissed) => void dismissFinding(finding, dismissed)}
                  />
                ))}
              </div>
            )}

            {tab === "questions" && (
              <div className="scrollbar-thin flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-5 pt-1 pb-5">
                {data.ambiguities.length === 0 && <Empty>No open questions — the ticket and the code agree.</Empty>}
                {data.ambiguities.map((item) => (
                  <QuestionCard
                    key={item.id}
                    item={item}
                    editable={finished}
                    onCopy={() =>
                      void copyText(
                        [
                          `QA question on ${run.ticketIdentifier}:`,
                          "",
                          `**${item.question}**`,
                          item.explanation && "",
                          item.explanation,
                          item.blocksTestCases.length > 0 && "",
                          item.blocksTestCases.length > 0 && `Blocks ${item.blocksTestCases.map(tcId).join(", ")} until answered.`,
                        ]
                          .filter((line) => typeof line === "string")
                          .join("\n"),
                        "Question",
                      )
                    }
                    onAnswer={(answer) => answerQuestion(item, answer)}
                  />
                ))}
                <div className="rounded-lg border border-dashed border-edge-strong px-3.75 py-3.25 text-[12.5px] text-fg-faint">
                  Ambiguities are raised when the ticket and the diff disagree, or when an acceptance criterion has no
                  observable outcome. Answers here are used by the next run of this ticket.
                </div>
              </div>
            )}

            {/* selection bar */}
            <SelectionBar
              total={cases.length}
              checked={checkedList}
              editable={finished}
              notice={notice}
              onBulk={(action) => void bulk(checkedList, action)}
              onApproveAll={() =>
                void bulk(
                  cases.filter((c) => c.status !== "rejected" && c.status !== "approved").map((c) => c.number),
                  { action: "set_status", value: "approved" },
                )
              }
            />
          </div>

          {/* right detail */}
          <aside className="scrollbar-thin w-full shrink-0 overflow-y-auto border-t border-edge bg-ink-800 xl:w-107 xl:border-t-0 xl:border-l">
            {current ? (
              <CaseDetail
                key={current.number}
                testCase={current}
                ticket={run.ticketIdentifier}
                ticketUrl={run.ticketUrl}
                editable={finished}
                onUpdate={(changes) => updateCase(current.number, changes)}
              />
            ) : (
              <p className="px-4.5 py-4 text-[12.5px] text-fg-faint">
                {cases.length ? "Select a test case to see its steps." : "This run produced no test cases."}
              </p>
            )}
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

/* --- pieces ---------------------------------------------------------------- */

function Stat({ label, tone = "text-fg-muted", children }: { label: string; tone?: string; children: ReactNode }) {
  return (
    <div className="min-w-23 rounded-[7px] border border-edge bg-ink-800 px-3 py-2">
      <p className="label-micro mb-0.75">{label}</p>
      <p className={`font-mono text-[14px] ${tone}`}>{children}</p>
    </div>
  );
}

function Divider() {
  return <span className="h-3.5 w-px bg-edge" />;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-[12.5px] text-fg-faint">{children}</p>;
}

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`rounded-[3px] border px-1.25 py-px font-mono text-[10px] whitespace-nowrap ${className}`}>{children}</span>;
}

function Checkbox({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`flex size-3.75 shrink-0 cursor-pointer items-center justify-center rounded border ${
        on ? "border-signal bg-signal" : "border-fg-ghost hover:border-fg-faint"
      }`}
    >
      {on && <CheckIcon size={9} className="text-ink-900" />}
    </button>
  );
}

function CasesTable({
  cases,
  selected,
  checked,
  onSelect,
  onToggle,
  onToggleAll,
}: {
  cases: ReviewTestCase[];
  selected: number | null;
  checked: Set<number>;
  onSelect: (n: number) => void;
  onToggle: (n: number) => void;
  onToggleAll: () => void;
}) {
  const allOn = cases.length > 0 && cases.every((c) => checked.has(c.number));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-edge px-5 pb-2">
        <Checkbox on={allOn} onClick={onToggleAll} label="Select all shown" />
        <span className="label-micro w-14">TC</span>
        <span className="label-micro w-8.5">Pri</span>
        <span className="label-micro flex-1">Test title</span>
        <span className="label-micro hidden w-21 md:block">Type</span>
        <span className="label-micro hidden w-32 lg:block">Traces to</span>
        <span className="label-micro w-21.5">Status</span>
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        {cases.length === 0 && <Empty>No test cases match.</Empty>}
        {cases.map((c) => {
          const on = c.number === selected;
          const status = STATUS_STYLE[c.status];
          return (
            <div
              key={c.number}
              role="button"
              tabIndex={0}
              aria-current={on || undefined}
              onClick={() => onSelect(c.number)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(c.number);
                }
              }}
              className={`flex cursor-pointer items-center gap-3 border-b border-l-2 border-b-[#151a1e] py-3 pr-5 pl-4.5 ${
                on ? "border-l-signal bg-ink-600" : "border-l-transparent hover:bg-ink-800"
              }`}
            >
              <Checkbox on={checked.has(c.number)} onClick={() => onToggle(c.number)} label={`Select ${c.identifier}`} />
              <span className={`w-14 font-mono text-[11px] ${on ? "text-fg-bright" : "text-fg-dimmer"}`}>{c.identifier}</span>
              <span className="w-8.5">
                <Badge className={PRIORITY_STYLE[c.priority]}>{c.priority}</Badge>
              </span>
              <span className={`min-w-0 flex-1 truncate text-[13px] ${on ? "text-fg" : "text-fg-muted"} ${c.status === "rejected" ? "line-through opacity-60" : ""}`}>
                {c.title}
              </span>
              <span className="hidden w-21 font-mono text-[10px] tracking-[0.06em] text-fg-faint uppercase md:block">{c.testType}</span>
              <span className="hidden w-32 truncate font-mono text-[11px] text-info lg:block">
                {c.tracesTo.map((t) => shortTrace(t.label)).join(" · ") || "—"}
              </span>
              <span className="w-21.5">
                <Badge className={`px-1.5 py-0.5 ${status.pill}`}>{status.label}</Badge>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SelectionBar({
  total,
  checked,
  editable,
  notice,
  onBulk,
  onApproveAll,
}: {
  total: number;
  checked: number[];
  editable: boolean;
  notice: string;
  onBulk: (action: BulkAction) => void;
  onApproveAll: () => void;
}) {
  const none = checked.length === 0 || !editable;
  const select =
    "h-6.5 cursor-pointer rounded-[5px] border border-edge-strong bg-ink-800 px-1.5 font-mono text-[11px] text-fg-muted " +
    "disabled:cursor-not-allowed disabled:border-edge disabled:text-fg-ghost";
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-edge bg-ink-800 px-5 py-2.5">
      <span className="font-mono text-[11px] text-fg-muted">
        {checked.length} of {total} selected
      </span>
      <Divider />
      <span className="font-mono text-[11px] text-fg-faint">Bulk:</span>
      <select
        aria-label="Set priority"
        disabled={none}
        value=""
        onChange={(e) => e.target.value && onBulk({ action: "set_priority", value: e.target.value as Priority })}
        className={select}
      >
        <option value="">set priority</option>
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <select
        aria-label="Set status"
        disabled={none}
        value=""
        onChange={(e) => e.target.value && onBulk({ action: "set_status", value: e.target.value as TestCaseStatus })}
        className={select}
      >
        <option value="">set status</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_STYLE[s].label}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={none}
        onClick={() => onBulk({ action: "delete" })}
        className="h-6.5 cursor-pointer rounded-[5px] px-1.5 font-mono text-[11px] text-danger hover:bg-danger-bg disabled:cursor-not-allowed disabled:text-fg-ghost disabled:hover:bg-transparent"
      >
        delete
      </button>
      <span className="flex-1" />
      {notice && (
        <span role="status" className="font-mono text-[11px] text-signal">
          {notice}
        </span>
      )}
      <button
        type="button"
        disabled={!editable || total === 0}
        onClick={onApproveAll}
        className="flex h-7 cursor-pointer items-center rounded-md border border-edge-strong px-2.75 text-[12px] text-fg-muted hover:border-fg-faint hover:text-fg disabled:cursor-not-allowed disabled:border-edge disabled:text-fg-ghost"
      >
        Approve all
      </button>
      <button
        type="button"
        disabled
        title="Export arrives with screen 07"
        className="flex h-7 cursor-not-allowed items-center rounded-md bg-edge px-2.75 text-[12px] font-semibold text-fg-faint"
      >
        {checked.length > 0 ? `Export ${checked.length} selected` : `Export all ${total}`}
      </button>
    </div>
  );
}

function FindingCard({
  finding,
  ticket,
  editable,
  onAdd,
  onOpenCase,
  onCopy,
  onDismiss,
}: {
  finding: ReviewFinding;
  ticket: string;
  editable: boolean;
  onAdd: () => void;
  onOpenCase: (n: number) => void;
  onCopy: () => void;
  onDismiss: (dismissed: boolean) => void;
}) {
  const style = SEVERITY_STYLE[finding.severity] ?? SEVERITY_STYLE.low;
  const action =
    "flex h-6.5 cursor-pointer items-center rounded-[5px] border border-edge-strong px-2.5 text-[11.5px] text-fg-muted hover:border-fg-faint hover:text-fg disabled:cursor-not-allowed disabled:text-fg-ghost";

  if (finding.dismissed) {
    return (
      <div className="flex items-center gap-2.5 rounded-lg border border-edge px-3.75 py-2.5">
        <span className={`size-1.75 shrink-0 rounded-full ${style.dot} opacity-50`} />
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-faint line-through">{finding.title}</span>
        {editable && (
          <button type="button" onClick={() => onDismiss(false)} className="cursor-pointer text-[11.5px] text-fg-faint hover:text-fg-muted">
            Restore
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`rounded-lg border bg-ink-800 px-3.75 py-3.5 ${style.border}`}>
      <div className="mb-2.25 flex flex-wrap items-center gap-2.25">
        <span className={`size-1.75 shrink-0 rounded-full ${style.dot}`} />
        <Badge className={`tracking-[0.06em] uppercase ${style.text} ${style.chip}`}>{finding.severity}</Badge>
        <span className="min-w-0 flex-1 text-[13px] font-semibold text-fg">{finding.title}</span>
        {finding.location &&
          (finding.locationUrl ? (
            <a
              href={finding.locationUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-mono text-[11px] text-info hover:text-fg-muted"
            >
              {finding.location} <ExternalLinkIcon size={11} />
            </a>
          ) : (
            <span className="font-mono text-[11px] text-fg-dim">{finding.location}</span>
          ))}
      </div>
      <p className="mb-3 max-w-180 text-[12.5px] whitespace-pre-line text-fg-dim text-pretty">{finding.explanation}</p>
      <div className="flex flex-wrap gap-2">
        {finding.testCaseNumber ? (
          <button type="button" onClick={() => onOpenCase(finding.testCaseNumber!)} className={action}>
            Open {tcId(finding.testCaseNumber)}
          </button>
        ) : (
          <button type="button" disabled={!editable} onClick={onAdd} className={action}>
            Add as test case
          </button>
        )}
        <button
          type="button"
          onClick={onCopy}
          title={`Copies a comment about this finding to paste into ${ticket}`}
          className="flex h-6.5 cursor-pointer items-center rounded-[5px] bg-signal px-2.5 text-[11.5px] font-semibold text-ink-900 hover:bg-signal-bright"
        >
          Copy as Linear comment
        </button>
        {editable && (
          <button
            type="button"
            onClick={() => onDismiss(true)}
            className="flex h-6.5 cursor-pointer items-center rounded-[5px] px-2.5 text-[11.5px] text-fg-faint hover:text-fg-muted"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}

function QuestionCard({
  item,
  editable,
  onCopy,
  onAnswer,
}: {
  item: ReviewAmbiguity;
  editable: boolean;
  onCopy: () => void;
  onAnswer: (answer: string) => Promise<boolean>;
}) {
  const [answering, setAnswering] = useState(false);
  const [draft, setDraft] = useState(item.answer);
  const [saving, setSaving] = useState(false);

  async function save(value: string) {
    setSaving(true);
    const ok = await onAnswer(value.trim());
    setSaving(false);
    if (ok) setAnswering(false);
  }

  return (
    <div className={`rounded-lg border bg-ink-800 px-3.75 py-3.5 ${item.answer ? "border-edge" : "border-warn-edge"}`}>
      <div className="mb-2.5 flex flex-wrap items-center gap-2.25">
        <QuestionIcon size={15} className={item.answer ? "text-fg-faint" : "text-warn"} />
        <Badge
          className={`tracking-[0.06em] uppercase ${
            item.answer ? "border-edge-strong bg-ink-500 text-fg-dim" : "border-warn-edge bg-warn-bg text-warn"
          }`}
        >
          {item.answer ? "answered" : item.kind}
        </Badge>
        <span className="flex-1" />
        {item.source && <span className="font-mono text-[11px] text-info">{item.source}</span>}
      </div>
      <p className="mb-2.25 max-w-185 text-[14px] font-medium text-fg">{item.question}</p>
      {item.explanation && <p className="mb-3 max-w-185 text-[12.5px] text-fg-dim text-pretty">{item.explanation}</p>}

      {item.answer && !answering && (
        <div className="mb-3 max-w-185 rounded-[7px] border border-signal-edge bg-[#141c0c] px-3 py-2.5">
          <p className="text-[12.5px] whitespace-pre-line text-[#cfe8a0]">{item.answer}</p>
          {item.answeredBy && <p className="mt-1 font-mono text-[10px] text-fg-faint">{item.answeredBy}</p>}
        </div>
      )}

      {answering && (
        <div className="mb-3 max-w-185">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            maxLength={4000}
            placeholder="The decision, as the next run should treat it"
            className="w-full resize-y rounded-md border border-edge-strong bg-ink-900 px-2.75 py-2 text-[12.5px] text-fg-muted outline-none focus:border-fg-faint"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={saving || !draft.trim()}
              onClick={() => void save(draft)}
              className="h-6.5 cursor-pointer rounded-[5px] bg-signal px-2.75 text-[11.5px] font-semibold text-ink-900 disabled:cursor-not-allowed disabled:bg-edge disabled:text-fg-faint"
            >
              Save answer
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(item.answer);
                setAnswering(false);
              }}
              className="h-6.5 cursor-pointer px-2 text-[11.5px] text-fg-faint hover:text-fg-muted"
            >
              Cancel
            </button>
            {item.answer && (
              <button
                type="button"
                disabled={saving}
                onClick={() => void save("")}
                className="ml-auto h-6.5 cursor-pointer px-2 text-[11.5px] text-danger hover:text-danger"
              >
                Clear answer
              </button>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onCopy}
          title="Copies the question to paste into Linear"
          className="flex h-6.75 cursor-pointer items-center rounded-[5px] bg-signal px-2.75 text-[11.5px] font-semibold text-ink-900 hover:bg-signal-bright"
        >
          Copy as Linear comment
        </button>
        {editable && !answering && (
          <button
            type="button"
            onClick={() => setAnswering(true)}
            className="flex h-6.75 cursor-pointer items-center rounded-[5px] border border-edge-strong px-2.5 text-[11.5px] text-fg-muted hover:border-fg-faint hover:text-fg"
          >
            {item.answer ? "Edit answer" : "Answer here"}
          </button>
        )}
        <span className="flex-1" />
        {item.blocksTestCases.length > 0 && (
          <span className="font-mono text-[11px] text-fg-faint">blocks {item.blocksTestCases.map(tcId).join(", ")}</span>
        )}
      </div>
    </div>
  );
}

type Draft = {
  title: string;
  testType: string;
  suite: string;
  estimateMinutes: string;
  description: string;
  preconditions: string;
  steps: string;
  expectedResult: string;
};

function toDraft(c: ReviewTestCase): Draft {
  return {
    title: c.title,
    testType: c.testType,
    suite: c.suite,
    estimateMinutes: c.estimateMinutes ? String(c.estimateMinutes) : "",
    description: c.description,
    preconditions: c.preconditions,
    steps: c.steps.join("\n"),
    expectedResult: c.expectedResult,
  };
}

function CaseDetail({
  testCase: c,
  ticket,
  ticketUrl,
  editable,
  onUpdate,
}: {
  testCase: ReviewTestCase;
  ticket: string;
  ticketUrl: string;
  editable: boolean;
  onUpdate: (changes: TestCaseUpdate) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => toDraft(c));
  const [saving, setSaving] = useState(false);
  const status = STATUS_STYLE[c.status];

  async function save() {
    const minutes = Number.parseInt(draft.estimateMinutes, 10);
    setSaving(true);
    const ok = await onUpdate({
      title: draft.title.trim() || c.title,
      testType: draft.testType,
      suite: draft.suite.trim(),
      estimateMinutes: Number.isFinite(minutes) && minutes > 0 ? Math.min(minutes, 600) : null,
      description: draft.description,
      preconditions: draft.preconditions,
      steps: draft.steps
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      expectedResult: draft.expectedResult,
    });
    setSaving(false);
    if (ok) setEditing(false);
  }

  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const input =
    "w-full rounded-md border border-edge-strong bg-ink-900 px-2.5 py-1.75 text-[12.5px] text-fg-muted outline-none focus:border-fg-faint";

  return (
    <div className="px-4.5 py-4">
      <div className="mb-3.25 flex items-center gap-2.25">
        <span className="font-mono text-[12px] text-fg">{c.identifier}</span>
        {editable ? (
          <select
            aria-label="Priority"
            value={c.priority}
            onChange={(e) => void onUpdate({ priority: e.target.value as Priority })}
            className={`cursor-pointer appearance-none rounded-[3px] border px-1.25 py-px font-mono text-[10px] outline-none ${PRIORITY_STYLE[c.priority]}`}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p} className="bg-ink-800 text-fg-muted">
                {p}
              </option>
            ))}
          </select>
        ) : (
          <Badge className={PRIORITY_STYLE[c.priority]}>{c.priority}</Badge>
        )}
        {c.edited && <span className="font-mono text-[10px] text-fg-faint">edited</span>}
        <span className="flex-1" />
        {editable ? (
          <label className="relative flex h-6.5 cursor-pointer items-center gap-1.5 rounded-[5px] border border-edge-strong pr-2 pl-2.25 hover:border-fg-faint">
            <span className={`size-1.5 rounded-full ${status.dot}`} />
            <span className="font-mono text-[11px] text-fg-muted">{status.label}</span>
            <ChevronDownIcon size={11} className="text-fg-faint" />
            <select
              aria-label="Status"
              value={c.status}
              onChange={(e) => void onUpdate({ status: e.target.value as TestCaseStatus })}
              className="absolute inset-0 cursor-pointer opacity-0"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_STYLE[s].label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <Badge className={status.pill}>{status.label}</Badge>
        )}
      </div>

      {editing ? (
        <input value={draft.title} onChange={set("title")} maxLength={300} aria-label="Title" className={`${input} mb-4 font-display text-[15px] font-semibold`} />
      ) : (
        <h2 className="mb-4 font-display text-[17px] leading-[1.35] font-semibold text-fg text-pretty">{c.title}</h2>
      )}

      <div className="mb-3.75 flex gap-6.5 border-b border-edge pb-3.75">
        <Meta label="Type">
          {editing ? (
            <select value={draft.testType} onChange={set("testType")} className={`${input} py-1 font-mono text-[11.5px]`}>
              {[...new Set([...TEST_TYPES, draft.testType].filter(Boolean))].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          ) : (
            c.testType || "—"
          )}
        </Meta>
        <Meta label="Suite">
          {editing ? <input value={draft.suite} onChange={set("suite")} maxLength={120} className={`${input} py-1 font-mono text-[11.5px]`} /> : c.suite || "—"}
        </Meta>
        <Meta label="Est.">
          {editing ? (
            <input
              value={draft.estimateMinutes}
              onChange={set("estimateMinutes")}
              inputMode="numeric"
              placeholder="min"
              className={`${input} w-16 py-1 font-mono text-[11.5px]`}
            />
          ) : c.estimateMinutes ? (
            `${c.estimateMinutes} min`
          ) : (
            "—"
          )}
        </Meta>
      </div>

      <Section label="Test description">
        {editing ? <textarea value={draft.description} onChange={set("description")} rows={3} className={input} /> : <Prose text={c.description} />}
      </Section>

      <Section label="Preconditions">
        {editing ? <textarea value={draft.preconditions} onChange={set("preconditions")} rows={2} className={input} /> : <Prose text={c.preconditions} />}
      </Section>

      <p className="label-micro mb-2">Test steps</p>
      {editing ? (
        <div className="mb-4.5">
          <textarea value={draft.steps} onChange={set("steps")} rows={Math.max(4, c.steps.length + 1)} className={input} />
          <p className="mt-1 font-mono text-[10px] text-fg-faint">one step per line</p>
        </div>
      ) : c.steps.length ? (
        <ol className="mb-4.5 flex flex-col gap-2">
          {c.steps.map((step, i) => (
            <li key={i} className="flex items-start gap-2.5">
              <span className="mt-px flex size-4.25 shrink-0 items-center justify-center rounded bg-ink-500 font-mono text-[10px] text-fg-dimmer">
                {i + 1}
              </span>
              <span className="flex-1 text-[12.5px] text-fg-muted text-pretty">{step}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mb-4.5 text-[12.5px] text-fg-ghost">No steps yet.</p>
      )}

      <p className="label-micro mb-1.5">Expected result</p>
      {editing ? (
        <textarea value={draft.expectedResult} onChange={set("expectedResult")} rows={3} className={`${input} mb-3.75`} />
      ) : (
        <div className="mb-3.75 rounded-[7px] border border-signal-edge bg-[#141c0c] px-3 py-2.75 text-[12.5px] whitespace-pre-line text-[#cfe8a0] text-pretty">
          {c.expectedResult || "—"}
        </div>
      )}

      <p className="label-micro mb-1.5">Actual result</p>
      <div className="mb-4.5 rounded-[7px] border border-dashed border-edge-strong px-3 py-2.75 text-[12.5px] text-fg-faint">
        {c.actualResult || "Recorded at execution time — exported blank."}
      </div>

      {c.tracesTo.length > 0 && (
        <>
          <p className="label-micro mb-2">Traceability</p>
          <ul className="mb-4.5 flex flex-col gap-1.75">
            {c.tracesTo.map((t) => {
              const url = t.kind === "criterion" ? ticketUrl : t.url;
              const body = (
                <>
                  <span className="w-12 shrink-0 font-mono text-[10px] text-fg-faint">{t.kind === "criterion" ? "ticket" : "code"}</span>
                  <span
                    className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-info"
                    title={t.text || undefined}
                  >
                    {t.kind === "criterion" ? `${ticket} · ${t.label}` : t.label}
                  </span>
                  {url && <ExternalLinkIcon size={12} className="shrink-0 text-fg-faint" />}
                </>
              );
              const box = "flex items-center gap-2.25 rounded-md border border-edge bg-ink-700 px-2.5 py-2";
              return (
                <li key={t.label}>
                  {url ? (
                    <a href={url} target="_blank" rel="noreferrer" className={`${box} no-underline hover:border-edge-strong`}>
                      {body}
                    </a>
                  ) : (
                    <div className={box}>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {editable &&
        (editing ? (
          <div className="flex gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void save()}
              className="flex h-7.5 flex-1 cursor-pointer items-center justify-center gap-2 rounded-md bg-signal text-[12px] font-semibold text-ink-900 hover:bg-signal-bright disabled:opacity-60"
            >
              {saving && <SpinnerIcon size={13} />} Save
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(toDraft(c));
                setEditing(false);
              }}
              className="flex h-7.5 flex-1 cursor-pointer items-center justify-center rounded-md border border-edge-strong text-[12px] text-fg-muted hover:border-fg-faint"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              disabled={c.status === "approved"}
              onClick={() => void onUpdate({ status: "approved" })}
              className="flex h-7.5 flex-1 cursor-pointer items-center justify-center rounded-md bg-signal text-[12px] font-semibold text-ink-900 hover:bg-signal-bright disabled:cursor-default disabled:bg-signal-bg disabled:text-signal"
            >
              {c.status === "approved" ? "Approved" : "Approve"}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(toDraft(c));
                setEditing(true);
              }}
              className="flex h-7.5 flex-1 cursor-pointer items-center justify-center rounded-md border border-edge-strong text-[12px] text-fg-muted hover:border-fg-faint hover:text-fg"
            >
              Edit
            </button>
            <button
              type="button"
              disabled={c.status === "rejected"}
              onClick={() => void onUpdate({ status: "rejected" })}
              className="flex h-7.5 cursor-pointer items-center justify-center rounded-md border border-edge-strong px-2.75 text-[12px] text-danger hover:border-danger-edge disabled:cursor-default disabled:opacity-60"
            >
              {c.status === "rejected" ? "Rejected" : "Reject"}
            </button>
          </div>
        ))}
    </div>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="label-micro mb-1">{label}</p>
      <div className="font-mono text-[11.5px] text-fg-muted">{children}</div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4.25">
      <p className="label-micro mb-1.5">{label}</p>
      {children}
    </div>
  );
}

function Prose({ text }: { text: string }) {
  return text ? (
    <p className="text-[12.5px] whitespace-pre-line text-fg-dim text-pretty">{text}</p>
  ) : (
    <p className="text-[12.5px] text-fg-ghost">—</p>
  );
}
