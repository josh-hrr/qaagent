import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import {
  ApiError,
  exportApi,
  type ExportPreview,
  type ExportScope,
  type ExportSettings,
  type FileFormat,
  type MarkdownLayout,
  type ReviewRun,
} from "../lib/api";
import { CheckIcon, DownloadIcon, InfoIcon, SpinnerIcon } from "./icons";

/** The columns the dialog opens with — what a manual tester fills in on a run. */
const DEFAULT_COLUMNS = ["id", "status", "priority", "title", "description", "steps", "expected", "actual"];
const REQUIRED_COLUMNS = ["id", "title"];

const FORMATS: { key: FileFormat; label: string; note: string }[] = [
  {
    key: "csv",
    label: ".csv",
    note: "One row per test case. Best for importing into a test management tool, or a spreadsheet the team edits during execution.",
  },
  {
    key: "md",
    label: ".md",
    note: "Best for review inside a pull request or a team wiki — the file stays diffable in git.",
  },
];

const LAYOUTS: { key: MarkdownLayout; label: string; note: string }[] = [
  { key: "table", label: "One table", note: "A single pipe table — closest to the CSV." },
  { key: "sections", label: "One section per case", note: "Readable in a PR description or wiki." },
];

type OptionKey = "numberedSteps" | "blankActual" | "runHeader";

const OPTIONS: {
  key: OptionKey;
  label: string;
  note: string;
  /** Hidden where it would change nothing — an inert toggle is a lie. */
  applies?: (settings: ExportSettings) => boolean;
}[] = [
  {
    key: "numberedSteps",
    label: "Keep steps numbered in one cell",
    note: "One numbered step per line. Off joins them with semicolons on a single line.",
    // The section layout writes steps as a real Markdown list; there is no
    // single cell for this to change.
    applies: (settings) => !(settings.fileFormat === "md" && settings.layout === "sections"),
  },
  { key: "blankActual", label: "Leave actual_result blank", note: 'Off pre-fills every row with "Not run".' },
  { key: "runHeader", label: "Prepend a run summary header", note: "Ticket, source, commit and coverage above the rows." },
];

const PREVIEW_DEBOUNCE_MS = 250;

function previewNote(settings: ExportSettings): string {
  if (settings.fileFormat === "md" && settings.layout === "sections")
    return "Readable as a PR comment or a wiki page — one heading per case, steps as a real list.";
  if (settings.fileFormat === "md")
    return "Pipe tables get wide fast with long steps — the section layout reads better past about six columns.";
  return "UTF-8 with a BOM, CRLF line endings — opens cleanly in Excel and imports into TestRail and Xray.";
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
}

function initialSettings(remembered: Partial<ExportSettings> | null, selected: number[], preferSelection: boolean): ExportSettings {
  return {
    fileFormat: remembered?.fileFormat === "md" ? "md" : "csv",
    layout: remembered?.layout ?? "table",
    scope: preferSelection && selected.length > 0 ? "selected" : (remembered?.scope ?? "all"),
    columns: remembered?.columns?.length ? remembered.columns : DEFAULT_COLUMNS,
    caseNumbers: selected,
    numberedSteps: remembered?.numberedSteps ?? true,
    blankActual: remembered?.blankActual ?? true,
    runHeader: remembered?.runHeader ?? false,
  };
}

export function ExportDialog({
  run,
  selected,
  preferSelection = false,
  onClose,
  onExported,
}: {
  run: ReviewRun;
  /** Test case numbers ticked in the table behind the dialog. */
  selected: number[];
  /** Open on "Selected in the table" — true when opened from the selection bar. */
  preferSelection?: boolean;
  onClose: () => void;
  onExported: (filename: string) => void;
}) {
  const { user, refresh } = useAuth();
  const [settings, setSettings] = useState<ExportSettings>(() =>
    initialSettings(user?.exportPreferences ?? null, selected, preferSelection),
  );
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const closeButton = useRef<HTMLButtonElement | null>(null);

  const set = useCallback(<K extends keyof ExportSettings>(key: K, value: ExportSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  }, []);

  // Escape closes, as in every other dialog the team uses.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    closeButton.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The preview is rendered by the same server code as the file, so what is on
  // screen is the download. Debounced because every toggle asks for it again.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      exportApi
        .preview(run.id, settings)
        .then((body) => {
          if (cancelled) return;
          setPreview(body);
          setError("");
        })
        .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not build the preview."))
        .finally(() => !cancelled && setLoading(false));
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [run.id, settings]);

  const columns = preview?.columns ?? [];
  const counts = preview?.counts ?? { all: 0, approved: 0, rejectedExcluded: 0 };
  const scopes: { key: ExportScope; label: string; count: number }[] = useMemo(
    () => [
      { key: "all", label: "All cases in this run", count: counts.all },
      { key: "selected", label: "Selected in the table", count: selected.length },
      { key: "approved", label: "Approved only", count: counts.approved },
    ],
    [counts.all, counts.approved, selected.length],
  );

  const caseCount = preview?.caseCount ?? 0;
  const activeColumns = new Set([...settings.columns, ...REQUIRED_COLUMNS]);

  async function download() {
    setDownloading(true);
    try {
      const { filename } = await exportApi.download(run.id, settings, preview?.filename ?? "test-cases.csv");
      // The server remembered these settings; pull the user row so the next
      // dialog opens with them.
      void refresh();
      onExported(filename);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The download failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Export test cases"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(6,8,10,0.82)] p-4"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="flex max-h-[92vh] w-full max-w-250 flex-col overflow-hidden rounded-xl border border-edge-strong bg-ink-800 shadow-[0_32px_80px_rgba(0,0,0,0.6)]">
        {/* header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-edge px-5.5 py-4">
          <h2 className="font-display text-[17px] font-semibold text-fg-bright">Export test cases</h2>
          <span className="font-mono text-[11px] text-fg-faint">
            {run.ticketIdentifier} · run #{run.runNumber}
          </span>
          <span className="flex-1" />
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-6 cursor-pointer items-center justify-center rounded text-fg-faint hover:bg-ink-500 hover:text-fg-muted"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
            </svg>
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {/* options */}
          <div className="scrollbar-thin w-full shrink-0 overflow-y-auto border-b border-edge px-5 py-4.5 lg:w-103.5 lg:border-r lg:border-b-0">
            <p className="label-micro mb-2.25">File format</p>
            <div className="mb-2.25 flex gap-1.5 rounded-lg border border-edge-field bg-ink-900 p-1">
              {FORMATS.map((format) => {
                const on = settings.fileFormat === format.key;
                return (
                  <button
                    key={format.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set("fileFormat", format.key)}
                    className={`h-8 flex-1 cursor-pointer rounded-md font-mono text-[12px] ${
                      on ? "bg-signal font-semibold text-ink-900" : "text-fg-dimmer hover:text-fg-muted"
                    }`}
                  >
                    {format.label}
                  </button>
                );
              })}
            </div>
            <p className="mb-5 text-[11.5px] text-fg-faint text-pretty">
              {FORMATS.find((f) => f.key === settings.fileFormat)?.note}
            </p>

            {settings.fileFormat === "md" && (
              <div className="mb-5">
                <p className="label-micro mb-2.25">Markdown layout</p>
                <div className="flex gap-2">
                  {LAYOUTS.map((layout) => {
                    const on = settings.layout === layout.key;
                    return (
                      <button
                        key={layout.key}
                        type="button"
                        aria-pressed={on}
                        onClick={() => set("layout", layout.key)}
                        className={`flex-1 cursor-pointer rounded-[7px] border px-3 py-2.5 text-left ${
                          on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"
                        }`}
                      >
                        <span className={`block text-[12.5px] font-medium ${on ? "text-fg" : "text-fg-muted"}`}>
                          {layout.label}
                        </span>
                        <span className="block text-[11px] text-fg-faint text-pretty">{layout.note}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="mb-2.25 flex items-center justify-between">
              <p className="label-micro">Columns</p>
              <span className="font-mono text-[10.5px] text-fg-faint">
                {activeColumns.size} of {columns.length || 14}
              </span>
            </div>
            <div className="mb-5 grid grid-cols-2 gap-1.5">
              {columns.map((column) => {
                const on = activeColumns.has(column.key);
                return (
                  <button
                    key={column.key}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    disabled={column.required}
                    onClick={() =>
                      set(
                        "columns",
                        on
                          ? settings.columns.filter((key) => key !== column.key)
                          : [...settings.columns, column.key],
                      )
                    }
                    className={`flex items-center gap-2.25 rounded-md border px-2.25 py-1.75 text-left ${
                      column.required ? "cursor-default" : "cursor-pointer"
                    } ${on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"}`}
                  >
                    <span
                      className={`flex size-3.5 shrink-0 items-center justify-center rounded border ${
                        on ? "border-signal bg-signal" : "border-fg-ghost"
                      }`}
                    >
                      {on && <CheckIcon size={8} className="text-ink-900" />}
                    </span>
                    <span className={`min-w-0 flex-1 truncate font-mono text-[11px] ${on ? "text-fg-bright" : "text-fg-dimmer"}`}>
                      {column.header}
                    </span>
                    {column.required && <span className="font-mono text-[9px] text-fg-faint">req</span>}
                  </button>
                );
              })}
            </div>

            <p className="label-micro mb-2.25">Which cases</p>
            <div className="mb-5 flex flex-col gap-1.5">
              {scopes.map((scope) => {
                const on = settings.scope === scope.key;
                const empty = scope.count === 0;
                return (
                  <button
                    key={scope.key}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    disabled={empty}
                    onClick={() => set("scope", scope.key)}
                    className={`flex items-center gap-2.5 rounded-[7px] border px-2.75 py-2.25 text-left ${
                      empty ? "cursor-not-allowed opacity-50" : "cursor-pointer"
                    } ${on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"}`}
                  >
                    <span
                      className={`flex size-3.75 shrink-0 items-center justify-center rounded-full border ${
                        on ? "border-signal bg-signal" : "border-fg-ghost"
                      }`}
                    >
                      {on && <span className="size-1.25 rounded-full bg-ink-900" />}
                    </span>
                    <span className={`flex-1 text-[12.5px] ${on ? "text-fg" : "text-fg-muted"}`}>{scope.label}</span>
                    <span className="font-mono text-[11px] text-fg-faint">{scope.count}</span>
                  </button>
                );
              })}
            </div>
            {counts.rejectedExcluded > 0 && (
              <p className="mb-5 -mt-3.5 text-[11px] text-fg-faint">
                {counts.rejectedExcluded} rejected case{counts.rejectedExcluded === 1 ? "" : "s"} never exported.
              </p>
            )}

            <p className="label-micro mb-2.25">Options</p>
            <div className="flex flex-col gap-1.5">
              {OPTIONS.filter((option) => option.applies?.(settings) ?? true).map((option) => {
                const on = settings[option.key];
                return (
                  <button
                    key={option.key}
                    type="button"
                    role="switch"
                    aria-checked={on}
                    onClick={() => set(option.key, !on)}
                    className="flex cursor-pointer items-center gap-2.5 rounded-[7px] border border-edge bg-ink-700 px-2.75 py-2.25 text-left hover:border-edge-strong"
                  >
                    <span
                      className={`flex h-4.25 w-7.5 shrink-0 items-center rounded-full p-0.5 ${on ? "justify-end bg-signal" : "justify-start bg-edge-field"}`}
                    >
                      <span className={`size-3.25 rounded-full ${on ? "bg-ink-900" : "bg-fg-dimmer"}`} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] text-fg-muted">{option.label}</span>
                      <span className="block text-[11px] text-fg-faint text-pretty">{option.note}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* preview */}
          <div className="flex min-h-50 min-w-0 flex-1 flex-col bg-ink-900">
            <div className="flex shrink-0 items-center gap-2.5 border-b border-edge px-4.5 py-3">
              <span className="label-micro">Preview</span>
              {loading && <SpinnerIcon size={12} className="text-fg-faint" />}
              <span className="flex-1" />
              <span className="truncate font-mono text-[11px] text-fg-dimmer">{preview?.filename}</span>
              <span className="font-mono text-[11px] text-fg-faint">{preview ? size(preview.byteSize) : ""}</span>
            </div>
            <div className="scrollbar-thin min-h-0 flex-1 overflow-auto px-4.5 py-4">
              {error ? (
                <p className="text-[12.5px] text-danger">{error}</p>
              ) : (
                <pre className="font-mono text-[11px] leading-[1.85] whitespace-pre text-fg-dim">
                  {preview?.preview || (loading ? "" : "(nothing to export with these settings)")}
                </pre>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2.25 border-t border-edge px-4.5 py-2.75">
              <InfoIcon size={13} className="shrink-0 text-fg-faint" />
              <p className="text-[11.5px] text-fg-faint text-pretty">{previewNote(settings)}</p>
            </div>
          </div>
        </div>

        {/* footer */}
        <div className="flex shrink-0 flex-wrap items-center gap-3.5 border-t border-edge px-5.5 py-3.5">
          <div className="flex h-8.5 max-w-107 min-w-0 flex-1 items-center gap-2.25 rounded-[7px] border border-edge-field bg-ink-900 px-3">
            <span className="font-mono text-[11px] text-fg-faint">name</span>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-muted">{preview?.filename ?? "…"}</span>
          </div>
          <span className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            className="flex h-8.5 cursor-pointer items-center rounded-[7px] border border-edge-strong px-3.5 text-[13px] text-fg-dim hover:border-fg-faint hover:text-fg-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void download()}
            disabled={downloading || caseCount === 0 || Boolean(error)}
            className="flex h-8.5 cursor-pointer items-center gap-2 rounded-[7px] bg-signal px-4 text-[13px] font-semibold text-ink-900 hover:bg-signal-bright disabled:cursor-not-allowed disabled:bg-edge disabled:text-fg-faint"
          >
            {downloading ? <SpinnerIcon size={14} /> : <DownloadIcon size={14} />}
            Download {caseCount} case{caseCount === 1 ? "" : "s"}
          </button>
        </div>
      </div>
    </div>
  );
}
