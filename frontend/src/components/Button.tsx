import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'

import { SpinnerIcon } from './icons'

type Variant = 'primary' | 'secondary' | 'ghost'
type Size = 'md' | 'lg'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-signal text-ink-900 font-semibold hover:bg-signal-bright ' +
    'disabled:bg-edge disabled:text-fg-faint disabled:hover:bg-edge',
  secondary:
    'border border-edge-strong text-fg-muted hover:border-fg-faint hover:text-fg ' +
    'disabled:border-edge disabled:text-fg-ghost disabled:hover:border-edge disabled:hover:text-fg-ghost',
  ghost: 'text-fg-dimmer hover:text-fg-muted disabled:text-fg-ghost',
}

const SIZES: Record<Size, string> = {
  md: 'h-control px-4 text-[13px]',
  lg: 'h-control-lg px-5 text-[13.5px]',
}

const BASE =
  'inline-flex items-center justify-center gap-2.5 rounded-[7px] ' +
  'cursor-pointer transition-colors duration-150 disabled:cursor-not-allowed'

function classesFor(variant: Variant, size: Size, block: boolean, extra?: string): string {
  return [BASE, VARIANTS[variant], SIZES[size], block ? 'w-full' : '', extra ?? '']
    .filter(Boolean)
    .join(' ')
}

type SharedProps = {
  variant?: Variant
  size?: Size
  /** Stretch to the container width — the default for the sign-in stack. */
  block?: boolean
  icon?: ReactNode
  children: ReactNode
}

type ButtonProps = SharedProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
    /** Shows a spinner and blocks interaction without changing the layout. */
    busy?: boolean
  }

export function Button({
  variant = 'secondary',
  size = 'md',
  block = false,
  busy = false,
  icon,
  children,
  className,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={classesFor(variant, size, block, className)}
      {...rest}
    >
      {busy ? <SpinnerIcon size={15} /> : icon}
      <span>{children}</span>
    </button>
  )
}

type ButtonLinkProps = SharedProps & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'children'>

/**
 * An anchor that looks like a button. Used where the action is a real
 * navigation — the SSO redirects — so it keeps middle-click and "open in new
 * tab" working instead of swallowing them in an onClick.
 */
export function ButtonLink({
  variant = 'secondary',
  size = 'md',
  block = false,
  icon,
  children,
  className,
  ...rest
}: ButtonLinkProps) {
  return (
    <a className={classesFor(variant, size, block, `no-underline ${className ?? ''}`)} {...rest}>
      {icon}
      <span>{children}</span>
    </a>
  )
}
