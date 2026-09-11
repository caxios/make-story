/**
 * The pieces every authoring page is built from.
 *
 * Kept in one file because they are small and always used together; anything
 * that grows past a screen moves out to its own module.
 */

import { Loader2, X, type LucideIcon } from 'lucide-react'
import { createPortal } from 'react-dom'
import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'

import { cn } from '@/lib/cn'

// --------------------------------------------------------------------------
// Button
// --------------------------------------------------------------------------

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-deep shadow-sm shadow-accent/20',
  secondary: 'bg-raised text-ink border border-line-strong hover:bg-overlay',
  ghost: 'text-ink-dim hover:bg-white/5 hover:text-ink',
  danger: 'bg-bad/12 text-bad-bright border border-bad/30 hover:bg-bad/20',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-2.5 text-[0.8rem] gap-1.5',
  md: 'h-9.5 px-3.5 text-sm gap-2',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: LucideIcon
  loading?: boolean
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap',
        'transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        Icon && <Icon className="size-4 shrink-0" />
      )}
      {children}
    </button>
  )
}

/** A square button that is only an icon. The label lives in `title`. */
export function IconButton({
  icon: Icon,
  title,
  variant = 'ghost',
  className,
  ...rest
}: Omit<ButtonProps, 'children' | 'size'> & { icon: LucideIcon; title: string }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      className={cn(
        'grid size-8 shrink-0 place-items-center rounded-lg transition-colors duration-150',
        'disabled:cursor-not-allowed disabled:opacity-40',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      <Icon className="size-4" />
    </button>
  )
}

// --------------------------------------------------------------------------
// Fields
// --------------------------------------------------------------------------

function FieldShell({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label?: string
  hint?: string
  htmlFor?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-dim">
          {label}
        </label>
      )}
      {children}
      {hint && <p className="text-xs leading-relaxed text-ink-muted">{hint}</p>}
    </div>
  )
}

export function TextField({
  label,
  hint,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} htmlFor={id} className={className}>
      <input id={id} className="sw-field w-full text-sm" {...rest} />
    </FieldShell>
  )
}

export function TextArea({
  label,
  hint,
  className,
  rows = 4,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: string }) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} htmlFor={id} className={className}>
      <textarea id={id} rows={rows} className="sw-field w-full resize-y text-sm leading-relaxed" {...rest} />
    </FieldShell>
  )
}

export function SelectField({
  label,
  hint,
  options,
  className,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string
  hint?: string
  options: readonly { value: string; label: string }[]
}) {
  const id = useId()
  return (
    <FieldShell label={label} hint={hint} htmlFor={id} className={className}>
      <select id={id} className="sw-field w-full text-sm" {...rest}>
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-surface">
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}

/**
 * A labelled range, with its value always visible.
 *
 * A slider you cannot read the number off is a slider you cannot set twice the
 * same way, so the value sits next to the label rather than in a tooltip.
 */
export function Slider({
  label,
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.05,
  format = (v: number) => v.toFixed(2),
  tone = 'accent',
}: {
  label: string
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  format?: (value: number) => string
  tone?: 'accent' | 'sentiment'
}) {
  const id = useId()
  const accent =
    tone === 'accent'
      ? 'var(--color-accent)'
      : value > 0.3
        ? 'var(--color-good)'
        : value < -0.3
          ? 'var(--color-bad)'
          : 'var(--color-ink-muted)'

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="truncate text-xs font-medium text-ink-dim">
          {label}
        </label>
        <span className="font-mono text-xs tabular-nums text-ink">{format(value)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ accentColor: accent }}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line-strong"
      />
    </div>
  )
}

/**
 * A list of short strings, edited as tags.
 *
 * Enter commits, Backspace on an empty box removes the last one — the two
 * gestures anyone already expects from a tag field.
 */
export function TagInput({
  label,
  hint,
  values,
  onChange,
  placeholder = '입력 후 Enter 키를 누르세요',
}: {
  label?: string
  hint?: string
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
}) {
  const id = useId()
  const inputRef = useRef<HTMLInputElement>(null)

  const commit = () => {
    const value = inputRef.current?.value.trim()
    if (!value || !inputRef.current) return
    if (!values.includes(value)) onChange([...values, value])
    inputRef.current.value = ''
  }

  return (
    <FieldShell label={label} hint={hint} htmlFor={id}>
      <div className="sw-field flex flex-wrap items-center gap-1.5 py-2">
        {values.map((value, index) => (
          <span
            key={`${value}-${index}`}
            className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-raised px-2 py-0.5 text-xs text-ink"
          >
            {value}
            <button
              type="button"
              onClick={() => onChange(values.filter((_, i) => i !== index))}
              className="text-ink-muted transition-colors hover:text-bad-bright"
              aria-label={`Remove ${value}`}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          ref={inputRef}
          placeholder={values.length === 0 ? placeholder : ''}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              commit()
            } else if (
              event.key === 'Backspace' &&
              event.currentTarget.value === '' &&
              values.length > 0
            ) {
              onChange(values.slice(0, -1))
            }
          }}
          onBlur={commit}
          className="min-w-32 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted"
        />
      </div>
    </FieldShell>
  )
}

// --------------------------------------------------------------------------
// Structure
// --------------------------------------------------------------------------

export function Panel({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: string
  description?: string
  actions?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <section className={cn('sw-panel p-5', className)}>
      {(title || actions) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            {title && (
              <h3 className="text-sm font-semibold tracking-tight text-ink">{title}</h3>
            )}
            {description && (
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
        {description && <p className="mt-1 text-sm text-ink-dim">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly { id: T; label: string; icon?: LucideIcon; count?: number }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div role="tablist" className="mb-6 flex gap-1 border-b border-line">
      {tabs.map(({ id, label, icon: Icon, count }) => {
        const isActive = id === active
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(id)}
            className={cn(
              'relative flex items-center gap-2 px-3.5 py-2.5 text-sm font-medium',
              'transition-colors duration-150',
              isActive ? 'text-ink' : 'text-ink-muted hover:text-ink-dim',
            )}
          >
            {Icon && <Icon className="size-4" />}
            {label}
            {count !== undefined && (
              <span
                className={cn(
                  'rounded-full px-1.5 py-0.5 text-[0.65rem] tabular-nums',
                  isActive ? 'bg-accent/15 text-accent-bright' : 'bg-white/5 text-ink-muted',
                )}
              >
                {count}
              </span>
            )}
            <span
              className={cn(
                'absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent-bright transition-opacity',
                isActive ? 'opacity-100' : 'opacity-0',
              )}
            />
          </button>
        )
      })}
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="grid size-11 place-items-center rounded-2xl border border-line-strong bg-raised">
        <Icon className="size-5 text-ink-muted" />
      </div>
      <div>
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-ink-muted">
          {description}
        </p>
      </div>
      {action}
    </div>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  mono = false,
}: {
  children: ReactNode
  tone?: 'neutral' | 'accent' | 'good' | 'warn' | 'bad' | 'violet'
  mono?: boolean
}) {
  return (
    <span
      className={cn(
        'inline-block rounded-md border px-1.5 py-0.5 text-[0.68rem] font-medium whitespace-nowrap',
        mono && 'font-mono',
        tone === 'neutral' && 'border-line-strong bg-white/3 text-ink-dim',
        tone === 'accent' && 'border-accent/30 bg-accent/10 text-accent-bright',
        tone === 'violet' && 'border-violet/30 bg-violet/10 text-violet-bright',
        tone === 'good' && 'border-good/30 bg-good/10 text-good-bright',
        tone === 'warn' && 'border-warn/30 bg-warn/10 text-warn-bright',
        tone === 'bad' && 'border-bad/30 bg-bad/10 text-bad-bright',
      )}
    >
      {children}
    </span>
  )
}

// --------------------------------------------------------------------------
// Overlays
// --------------------------------------------------------------------------

/** Escape closes, and the page behind stops scrolling while it is open. */
function useDismissable(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])
}

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useDismissable(open, onClose)
  if (!open) return null

  // Rendered on `document.body`, not where it is written. A `position: fixed`
  // element is positioned against the nearest ancestor with a transform,
  // filter or backdrop-filter rather than the viewport — so an overlay left in
  // the page tree silently becomes clipped to whatever animated wrapper
  // happens to be above it.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/65 backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'sw-glass animate-rise relative flex max-h-[85vh] w-full flex-col rounded-2xl',
          wide ? 'max-w-2xl' : 'max-w-lg',
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line-strong px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
            {description && <p className="mt-1 text-xs text-ink-muted">{description}</p>}
          </div>
          <IconButton icon={X} title="닫기" onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-line-strong px-5 py-3.5">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  )
}

/** A modal that slides in from the right, for editing something long. */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
}) {
  useDismissable(open, onClose)
  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/65 backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="animate-slide-in relative flex h-full w-full max-w-xl flex-col border-l border-line-strong bg-panel shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold tracking-tight text-ink">{title}</h2>
            {description && <p className="mt-0.5 text-xs text-ink-muted">{description}</p>}
          </div>
          <IconButton icon={X} title="닫기" onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-line px-6 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = '삭제',
  destructive = true,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  message: ReactNode
  confirmLabel?: string
  destructive?: boolean
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            onClick={() => {
              onConfirm()
              onClose()
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm leading-relaxed text-ink-dim">{message}</div>
    </Modal>
  )
}
