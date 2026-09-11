/**
 * Toasts: the non-blocking half of feedback.
 *
 * Saves and deletions say so here rather than in a dialog. Errors get longer on
 * screen than successes, because an error is something to read, not something
 * to notice.
 */

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { ApiError } from '@/api/client'
import { cn } from '@/lib/cn'

export type ToastKind = 'success' | 'error' | 'info' | 'warning'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
  warning: (message: string) => void
  /** Report a caught exception, using the backend's own wording when it sent any. */
  fromError: (cause: unknown, fallback?: string) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DURATIONS: Record<ToastKind, number> = {
  success: 3000,
  info: 4000,
  warning: 6000,
  error: 8000,
}

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
  warning: AlertTriangle,
}

const TONES: Record<ToastKind, string> = {
  success: 'text-good-bright',
  error: 'text-bad-bright',
  info: 'text-accent-bright',
  warning: 'text-warn-bright',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
  }, [])

  const toast = useCallback(
    (message: string, kind: ToastKind = 'info') => {
      const id = nextId.current++
      setToasts((previous) => [...previous, { id, kind, message }])
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), DURATIONS[kind]),
      )
    },
    [dismiss],
  )

  // Clear every pending timer if the provider goes away mid-flight.
  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.clear()
    }
  }, [])

  const value = useMemo<ToastContextValue>(
    () => ({
      toast,
      dismiss,
      success: (message) => toast(message, 'success'),
      error: (message) => toast(message, 'error'),
      info: (message) => toast(message, 'info'),
      warning: (message) => toast(message, 'warning'),
      fromError: (cause, fallback = '오류가 발생했습니다.') => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return
        const message =
          cause instanceof ApiError
            ? cause.detail
            : cause instanceof Error
              ? cause.message
              : fallback
        toast(message, 'error')
      },
    }),
    [toast, dismiss],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: number) => void
}) {
  return (
    <div
      className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(24rem,calc(100vw-2.5rem))] flex-col gap-2.5"
      // Announced, not interrupting: a save confirmation should not steal focus.
      role="status"
      aria-live="polite"
    >
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind]
        return (
          <div
            key={toast.id}
            className="sw-glass animate-slide-in pointer-events-auto flex items-start gap-3 rounded-xl px-4 py-3"
          >
            <Icon className={cn('mt-0.5 size-4.5 shrink-0', TONES[toast.kind])} />
            <p className="flex-1 text-sm leading-relaxed text-ink">{toast.message}</p>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              className="-mr-1 -mt-0.5 rounded-md p-1 text-ink-muted transition-colors hover:bg-white/5 hover:text-ink"
              aria-label="닫기"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext)
  if (!value) throw new Error('useToast must be used inside a <ToastProvider>')
  return value
}
