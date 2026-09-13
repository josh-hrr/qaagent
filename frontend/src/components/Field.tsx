import { useId, type InputHTMLAttributes, type ReactNode } from 'react'

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  /** Validation or server error. Sets aria-invalid and ties the message to the input. */
  error?: string
  hint?: ReactNode
}

export function Field({ label, error, hint, className, ...rest }: FieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  return (
    <div className={className}>
      <label htmlFor={id} className="label-micro mb-1.5 block">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={[error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined}
        className={[
          'h-[42px] w-full rounded-[7px] bg-ink-900 px-3',
          'font-mono text-[13px] text-fg-muted',
          'border transition-colors duration-150',
          error
            ? 'border-danger-edge focus:border-danger'
            : 'border-edge-field hover:border-edge-strong focus:border-signal-edge',
          'outline-none focus-visible:outline-none',
          'disabled:cursor-not-allowed disabled:text-fg-faint',
        ].join(' ')}
        {...rest}
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1.5 text-[12px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="mt-1.5 text-[12px] text-fg-faint">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
