/**
 * Stroke icons on a 24px grid, drawn inline so they scale and recolour with
 * `currentColor`. Matches the icon style used across the design canvas.
 */

type IconProps = {
  className?: string
  /** Pixel size; icons are square. */
  size?: number
}

function Svg({
  size = 16,
  className,
  strokeWidth = 1.7,
  children,
}: IconProps & { strokeWidth?: number; children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export function CheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 12.5l5 5L20 6.5" strokeWidth={2.2} />
    </Svg>
  )
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h13" strokeWidth={2} />
      <path d="M13 6.5L18.5 12 13 17.5" strokeWidth={2} />
    </Svg>
  )
}

export function LockIcon(props: IconProps) {
  return (
    <Svg {...props} strokeWidth={1.8}>
      <path d="M6 10.5V8a6 6 0 0 1 12 0v2.5" />
      <rect x="4.5" y="10.5" width="15" height="9.5" rx="2.2" />
    </Svg>
  )
}

export function MailIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="5.5" width="18" height="13" rx="2.4" />
      <path d="M3.8 7l7.1 5.3a2 2 0 0 0 2.2 0L20.2 7" />
    </Svg>
  )
}

export function AlertIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4.5L21 19.2H3z" />
      <path d="M12 10v3.8M12 16.6v.01" />
    </Svg>
  )
}

export function InfoIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M12 11v5.4M12 7.8v.01" />
    </Svg>
  )
}

export function SpinnerIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={`animate-spin ${className ?? ''}`}
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth={2.4} opacity={0.25} />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
      />
    </svg>
  )
}

export function EyeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </Svg>
  )
}

export function EyeOffIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.9 6.1A8.7 8.7 0 0 1 12 5.8c6 0 9.5 6.2 9.5 6.2a17 17 0 0 1-3 3.7" />
      <path d="M6.3 8A17 17 0 0 0 2.5 12S6 18.2 12 18.2a8.9 8.9 0 0 0 3.6-.75" />
      <path d="M10 10a3 3 0 0 0 4.1 4.1" />
      <path d="M4 4l16 16" />
    </Svg>
  )
}

export function ClockIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M12 7.4V12l3 2" />
    </Svg>
  )
}

export function TrashIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4.5 6.8h15" />
      <path d="M9.2 6.8V5.2a1.4 1.4 0 0 1 1.4-1.4h2.8a1.4 1.4 0 0 1 1.4 1.4v1.6" />
      <path d="M6.4 6.8l.8 12a1.6 1.6 0 0 0 1.6 1.5h6.4a1.6 1.6 0 0 0 1.6-1.5l.8-12" />
    </Svg>
  )
}

export function PlayIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8.5 5.8v12.4l10-6.2z" />
    </Svg>
  )
}

export function TagIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3.5 8V3.8h4.2L20 16l-4.2 4.2z" />
      <circle cx="6.8" cy="7" r="1.1" />
    </Svg>
  )
}

export function BranchIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="6" cy="5.5" r="2.2" />
      <circle cx="6" cy="18.5" r="2.2" />
      <circle cx="18" cy="9" r="2.2" />
      <path d="M6 7.7v8.6" />
      <path d="M18 11.2c0 3.6-4.2 2.7-6.4 5" />
    </Svg>
  )
}

export function PlugIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M10.5 14.2a4.2 4.2 0 0 0 6 0l2.8-2.8a4.2 4.2 0 0 0-6-6l-1 1" />
      <path d="M13.5 9.8a4.2 4.2 0 0 0-6 0l-2.8 2.8a4.2 4.2 0 0 0 6 6l1-1" />
    </Svg>
  )
}

export function GearIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.2v2.4M12 18.4v2.4M20.8 12h-2.4M5.6 12H3.2M18.2 5.8l-1.7 1.7M7.5 16.5l-1.7 1.7M18.2 18.2l-1.7-1.7M7.5 7.5L5.8 5.8" />
    </Svg>
  )
}

export function SearchIcon(props: IconProps) {
  return (
    <Svg {...props} strokeWidth={1.8}>
      <circle cx="11" cy="11" r="6.2" />
      <path d="M20 20l-4.2-4.2" />
    </Svg>
  )
}

export function ExternalLinkIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14 5h5v5" />
      <path d="M19 5l-8 8" />
      <path d="M18 14.5V19H5V6h4.5" />
    </Svg>
  )
}

export function RefreshIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M19.5 13a7.5 7.5 0 1 1-2.2-6.1" />
      <path d="M19.5 4v5h-5" />
    </Svg>
  )
}

export function DownloadIcon(props: IconProps) {
  return (
    <Svg {...props} strokeWidth={2}>
      <path d="M12 4v11" />
      <path d="M7.5 10.5l4.5 4.5 4.5-4.5" />
      <path d="M4.5 19.5h15" />
    </Svg>
  )
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Svg {...props} strokeWidth={2}>
      <path d="M6 9.5l6 6 6-6" />
    </Svg>
  )
}

export function QuestionIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M9.6 9.6a2.4 2.4 0 1 1 2.9 2.4v1.4" />
      <path d="M12.5 16.6v.01" />
    </Svg>
  )
}

/** The product mark: a check in a rounded square. */
export function BrandMark({ size = 30, className }: IconProps) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-[7px] bg-signal ${className ?? ''}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg
        width={size * 0.56}
        height={size * 0.56}
        viewBox="0 0 24 24"
        fill="none"
        stroke="#0B0D0F"
        strokeWidth={2.3}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4 12.5l5 5L20 6.5" />
      </svg>
    </div>
  )
}

/** Microsoft's four-square mark, monochrome so it sits on the signal button. */
export function MicrosoftMark({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2.5" y="2.5" width="8.4" height="8.4" fill="currentColor" />
      <rect x="13.1" y="2.5" width="8.4" height="8.4" fill="currentColor" opacity={0.62} />
      <rect x="2.5" y="13.1" width="8.4" height="8.4" fill="currentColor" opacity={0.62} />
      <rect x="13.1" y="13.1" width="8.4" height="8.4" fill="currentColor" opacity={0.34} />
    </svg>
  )
}

export function GoogleMark({ size = 16, className }: IconProps) {
  return (
    <Svg size={size} className={className}>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 3.2c2.6 2.4 2.6 15.2 0 17.6" />
      <path d="M12 3.2c-2.6 2.4-2.6 15.2 0 17.6" />
      <path d="M3.4 12h17.2" />
    </Svg>
  )
}

export const providerMarks: Record<string, (props: IconProps) => React.ReactElement> = {
  microsoft: MicrosoftMark,
  google: GoogleMark,
}
