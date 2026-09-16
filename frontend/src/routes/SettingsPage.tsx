import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AppShell } from "../components/AppShell";
import { Button } from "../components/Button";
import { CheckIcon, InfoIcon, SpinnerIcon } from "../components/icons";
import {
  ApiError,
  settingsApi,
  type ExportDefaults,
  type FileFormat,
  type MarkdownLayout,
  type WorkspaceSettings,
} from "../lib/api";

const OPTIONS: { key: string; label: string; note: string }[] = [
  {
    key: "numbered_steps",
    label: "Numbered steps, one per line",
    note: "Off joins them with semicolons on a single line.",
  },
  { key: "blank_actual", label: "Leave actual_result blank", note: 'Off pre-fills every row with "Not run".' },
  { key: "run_header", label: "Prepend a run summary header", note: "Ticket, source, commit and coverage above the rows." },
];

const REQUIRED_COLUMNS = ["id", "title"];

/** Everything a workspace decides once, for everybody. Shown, not editable. */
function Managed() {
  return (
    <span
      className="rounded-[3px] border border-edge-strong px-1.5 py-px font-mono text-[9.5px] text-fg-faint"
      title="Chosen for the whole workspace. Ask whoever set up QA Agent to change it."
    >
      workspace
    </span>
  );
}

function Section({
  title,
  managed = false,
  chip,
  description,
  children,
}: {
  title: string;
  managed?: boolean;
  chip?: ReactNode;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[10px] border border-edge bg-ink-800 px-4.75 py-4.25">
      <div className="mb-1 flex flex-wrap items-center gap-2.25">
        <h2 className="text-[13.5px] font-semibold text-fg">{title}</h2>
        {managed && <Managed />}
        {chip}
      </div>
      {description && <p className="mb-3.5 max-w-180 text-[12.5px] text-fg-dimmer text-pretty">{description}</p>}
      {children}
    </section>
  );
}

function Facts({ items }: { items: { k: string; v: string; note?: string }[] }) {
  return (
    <dl
      className="grid gap-px overflow-hidden rounded-lg border border-edge bg-edge"
      style={{ gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, minmax(0, 1fr))` }}
    >
      {items.map((item) => (
        <div key={item.k} className="bg-ink-700 px-3.25 py-2.75">
          <dt className="label-micro mb-1">{item.k}</dt>
          <dd className="font-mono text-[13px] text-fg-muted">{item.v}</dd>
          {item.note && <p className="mt-0.75 text-[11px] text-fg-faint text-pretty">{item.note}</p>}
        </div>
      ))}
    </dl>
  );
}

export function SettingsPage() {
  const [data, setData] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<ExportDefaults | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await settingsApi.get();
      setData(body);
      setDraft(body.exportDefaults);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load settings.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !draft) {
    return (
      <AppShell title="Settings">
        <div className="flex flex-1 items-center justify-center gap-3 text-fg-faint">
          {error ? (
            <span className="text-[13px] text-danger">{error}</span>
          ) : (
            <>
              <SpinnerIcon size={18} />
              <span className="text-[13px]">Loading…</span>
            </>
          )}
        </div>
      </AppShell>
    );
  }

  const { spend, generation, signIn, account } = data;
  const spent = Number(spend.spentUsd);
  const cap = Number(spend.capUsd);
  const fraction = cap > 0 ? Math.min(1, spent / cap) : 0;
  const active = new Set([...draft.columns, ...REQUIRED_COLUMNS]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.exportDefaults);

  async function save() {
    if (!draft || !dirty) return;
    setSaving(true);
    try {
      const { exportDefaults } = await settingsApi.updateExportDefaults(draft);
      setData((current) => current && { ...current, exportDefaults });
      setDraft(exportDefaults);
      setNotice("Saved");
      window.setTimeout(() => setNotice(""), 2500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your defaults.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell title="Settings" subtitle={<span>{account.email}</span>}>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4.5">
        <div className="mx-auto flex w-full max-w-225 flex-col gap-3.5">
          {/* spend */}
          <Section title="Spend" managed>
            <div className="flex flex-wrap items-start gap-5.5">
              <div className="w-80 shrink-0">
                <p className="mb-2.5 flex items-baseline gap-1.75">
                  <span className="font-display text-[28px] font-semibold text-fg">${spent.toFixed(2)}</span>
                  <span className="font-mono text-[11px] text-fg-faint">of ${cap.toFixed(2)} this month</span>
                </p>
                <div className="mb-2.25 h-1.25 overflow-hidden rounded-full bg-edge">
                  <div
                    className={`h-1.25 ${spend.capReached ? "bg-danger" : fraction > 0.8 ? "bg-warn" : "bg-signal"}`}
                    style={{ width: `${Math.round(fraction * 100)}%` }}
                  />
                </div>
                <p className="font-mono text-[11px] text-fg-faint">
                  {spend.runCount} run{spend.runCount === 1 ? "" : "s"} this month
                  {spend.runCount > 0 ? ` · $${(spent / spend.runCount).toFixed(3)} average` : ""}
                </p>
              </div>

              <div className="min-w-90 flex-1">
                <Facts
                  items={[
                    { k: "Monthly limit", v: `$${cap.toFixed(2)}`, note: "Shared by everyone in the workspace." },
                    { k: "Per-run limit", v: `$${Number(generation.costCapUsd).toFixed(2)}`, note: "One run can never cost more." },
                  ]}
                />
              </div>
            </div>

            <div className="mt-3.5 flex items-center gap-2.25 rounded-[7px] border border-edge bg-ink-700 px-3 py-2.5">
              <InfoIcon size={14} className="shrink-0 text-fg-faint" />
              <p className="text-[12px] text-fg-dimmer text-pretty">
                At the monthly limit, starting a run is refused rather than queued. The per-run limit stops one run
                part-way and keeps the test cases it already wrote.
              </p>
            </div>
          </Section>

          {/* generation */}
          <Section
            title="Generation"
            managed
            description="What writes the test cases, and how far it is allowed to read before it has to stop."
          >
            <div className="mb-3 rounded-lg border border-signal-edge bg-[#121710] px-3.5 py-3">
              <p className="mb-0.5 flex items-center gap-2.25">
                <span className="font-mono text-[12.5px] text-fg">{generation.modelName}</span>
                <span className="rounded-[3px] border border-signal-edge bg-signal-bg px-1.5 font-mono text-[10px] text-signal">
                  in use
                </span>
              </p>
              <p className="text-[12px] text-fg-dimmer text-pretty">{generation.modelNote}</p>
            </div>

            <Facts
              items={[
                { k: "Effort", v: generation.effort, note: generation.effortNote },
                { k: "Files per run", v: String(generation.maxFiles), note: "Changed files plus what the agent follows." },
                { k: "Reading rounds", v: String(generation.maxRounds), note: "How many times it can ask for more." },
              ]}
            />
            <p className="mt-2.5 text-[11.5px] text-fg-faint text-pretty">
              Reaching a limit ends the reading and marks the run <span className="font-mono text-warn">stopped early</span>{" "}
              — the test cases already written are kept.
            </p>
          </Section>

          {/* sign-in */}
          <Section title="Sign-in" managed description="Who can get in, and how long a signed-in session lasts.">
            <div className="flex flex-wrap items-start gap-5.5">
              <div className="w-80 shrink-0">
                <p className="label-micro mb-2">Email domains that may sign in</p>
                {signIn.allowedEmailDomains.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {signIn.allowedEmailDomains.map((domain) => (
                      <span
                        key={domain}
                        className="rounded-[5px] border border-edge-strong bg-ink-700 px-2 py-0.75 font-mono text-[11px] text-fg-muted"
                      >
                        {domain}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-[12px] text-fg-faint">Any address can request a sign-in link.</p>
                )}
              </div>
              <div className="min-w-90 flex-1">
                <Facts
                  items={[
                    { k: "Signed out after", v: signIn.idleTimeout, note: "Of being idle." },
                    { k: "Session ends after", v: signIn.absoluteTimeout, note: "Counted from signing in." },
                    { k: "Sign-in link", v: `${signIn.magicLinkMinutes} min`, note: "Works once." },
                  ]}
                />
              </div>
            </div>
          </Section>

          {/* export defaults — the part that is genuinely yours */}
          <Section
            title="Your export defaults"
            chip={
              <span className="rounded-[3px] border border-signal-edge bg-signal-bg px-1.5 py-px font-mono text-[9.5px] text-signal">
                yours
              </span>
            }
            description="What the export dialog opens with. Saved for you, not for the workspace."
          >
            <p className="label-micro mb-2">Format</p>
            <div className="mb-3.5 flex max-w-90 gap-1.5 rounded-[7px] border border-edge-field bg-ink-900 p-1">
              {(
                [
                  { key: "csv", label: ".csv" },
                  { key: "md", label: ".md" },
                ] as const
              ).map((format) => {
                const on = draft.fileFormat === format.key;
                return (
                  <button
                    key={format.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setDraft({ ...draft, fileFormat: format.key as FileFormat })}
                    className={`h-7 flex-1 cursor-pointer rounded-md font-mono text-[11.5px] ${
                      on ? "bg-signal font-semibold text-ink-900" : "text-fg-dimmer hover:text-fg-muted"
                    }`}
                  >
                    {format.label}
                  </button>
                );
              })}
            </div>

            {draft.fileFormat === "md" && (
              <>
                <p className="label-micro mb-2">Markdown layout</p>
                <div className="mb-3.5 flex max-w-160 gap-2">
                  {(
                    [
                      { key: "table", label: "One table", note: "Closest to the CSV." },
                      { key: "sections", label: "One section per case", note: "Reads as a document." },
                    ] as const
                  ).map((layout) => {
                    const on = draft.layout === layout.key;
                    return (
                      <button
                        key={layout.key}
                        type="button"
                        aria-pressed={on}
                        onClick={() => setDraft({ ...draft, layout: layout.key as MarkdownLayout })}
                        className={`flex-1 cursor-pointer rounded-[7px] border px-3 py-2.5 text-left ${
                          on ? "border-signal-edge bg-[#121710]" : "border-edge bg-ink-700 hover:border-edge-strong"
                        }`}
                      >
                        <span className={`block text-[12.5px] font-medium ${on ? "text-fg" : "text-fg-muted"}`}>
                          {layout.label}
                        </span>
                        <span className="block text-[11px] text-fg-faint">{layout.note}</span>
                      </button>
                    );
                  })}
                </div>
              </>
            )}

            <div className="mb-2 flex items-center justify-between">
              <p className="label-micro">Columns</p>
              <span className="font-mono text-[10.5px] text-fg-faint">
                {active.size} of {data.exportColumns.length}
              </span>
            </div>
            <div className="mb-3.5 grid gap-1.5 sm:grid-cols-3">
              {data.exportColumns.map((column) => {
                const on = active.has(column.key);
                return (
                  <button
                    key={column.key}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    disabled={column.required}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        columns: on
                          ? draft.columns.filter((key) => key !== column.key)
                          : [...draft.columns, column.key],
                      })
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
                    <span
                      className={`min-w-0 flex-1 truncate font-mono text-[11px] ${on ? "text-fg-bright" : "text-fg-dimmer"}`}
                    >
                      {column.header}
                    </span>
                    {column.required && <span className="font-mono text-[9px] text-fg-faint">req</span>}
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-1.5">
              {OPTIONS.filter(
                (option) => !(option.key === "numbered_steps" && draft.fileFormat === "md" && draft.layout === "sections"),
              ).map((option) => {
                const on = Boolean(draft.options[option.key]);
                return (
                  <button
                    key={option.key}
                    type="button"
                    role="switch"
                    aria-checked={on}
                    onClick={() => setDraft({ ...draft, options: { ...draft.options, [option.key]: !on } })}
                    className="flex cursor-pointer items-center gap-2.5 rounded-[7px] border border-edge bg-ink-700 px-2.75 py-2.25 text-left hover:border-edge-strong"
                  >
                    <span
                      className={`flex h-4.25 w-7.5 shrink-0 items-center rounded-full p-0.5 ${
                        on ? "justify-end bg-signal" : "justify-start bg-edge-field"
                      }`}
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

            <div className="mt-3.5 flex items-center gap-2.5">
              {notice && (
                <span role="status" className="font-mono text-[11px] text-signal">
                  {notice}
                </span>
              )}
              <span className="flex-1" />
              {dirty && (
                <Button variant="secondary" onClick={() => setDraft(data.exportDefaults)} className="h-7 px-2.75 text-[12px]">
                  Discard
                </Button>
              )}
              <Button
                variant="primary"
                busy={saving}
                disabled={!dirty}
                onClick={() => void save()}
                className="h-7 px-3.25 text-[12px]"
              >
                Save defaults
              </Button>
            </div>
          </Section>

          {error && <p className="text-[12.5px] text-danger">{error}</p>}
        </div>
      </div>
    </AppShell>
  );
}
