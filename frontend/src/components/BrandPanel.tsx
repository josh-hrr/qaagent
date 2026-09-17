import { BrandMark } from "./icons";

const PILLARS = [
  {
    n: "01",
    text: "Ticket context from Linear — description, sub-issues, comments.",
  },
  {
    n: "02",
    text: "Code scope from Azure DevOps or GitHub, read per run.",
  },
  {
    n: "03",
    text: "Reviewed cases out as CSV or Markdown, traced to both.",
  },
];

/**
 * The marketing half of the sign-in screen. Hidden below `lg` so small windows
 * get the form full-width rather than a squashed two-column layout.
 */
export function BrandPanel() {
  return (
    <div className="relative hidden shrink-0 overflow-hidden bg-ink-900 px-16 py-11 lg:flex lg:w-[58%] lg:flex-col xl:w-[838px]">
      {/* Atmosphere: a single soft glow, a fine grid, and a fade that keeps the
          right edge quiet where it meets the form. */}
      <div
        className="pointer-events-none absolute -top-45 -left-30 h-180 w-180 rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(180,227,63,0.10) 0%, rgba(180,227,63,0) 62%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-55"
        style={{
          backgroundImage:
            "linear-gradient(#14191D 1px, transparent 1px), linear-gradient(90deg, #14191D 1px, transparent 1px)",
          backgroundSize: "56px 56px",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(105deg, rgba(11,13,15,0) 30%, #0B0D0F 88%)",
        }}
      />

      <div className="relative flex items-center gap-3">
        <BrandMark size={30} />
        <span className="font-display text-base font-bold tracking-tight">
          My Test Agent
        </span>
        <span className="rounded-[3px] border border-edge-strong px-1.5 py-0.5 font-mono text-[9px] text-fg-faint">
          internal
        </span>
      </div>

      <div className="relative my-auto max-w-[620px] py-12">
        <p className="mb-5 font-mono text-[11px] tracking-[0.12em] text-signal">
          MANUAL TEST DOCUMENTATION, AUTOMATED
        </p>
        <h1 className="font-display text-[clamp(2.25rem,3.6vw,3.25rem)] leading-[1.06] font-semibold tracking-tight text-fg-bright text-pretty">
          Test cases that read the ticket{" "}
          <span className="text-signal">and</span> the diff.
        </h1>
        <p className="mt-5 max-w-[520px] text-[15px] text-fg-dim text-pretty">
          Point it at a Linear ticket and the branch that implements it. It
          reads what actually changed, and writes the manual test cases —
          flagging code it doesn&rsquo;t trust and requirements it can&rsquo;t
          pin down.
        </p>
      </div>

      <div className="relative flex flex-wrap gap-11 border-t border-edge pt-5.5">
        {PILLARS.map((pillar) => (
          <div key={pillar.n} className="max-w-[200px]">
            <p className="mb-1.5 font-mono text-[11px] text-signal">
              {pillar.n}
            </p>
            <p className="text-[13px] text-fg-muted text-pretty">
              {pillar.text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
