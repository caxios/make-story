/**
 * Watching an episode being written.
 *
 * The pipeline is slow — minutes, not seconds — so the point of this screen is
 * that the wait is legible: which stage is running, on which scene, what that
 * scene is trying to do, and what it has cost so far. Everything on it comes
 * from the stream; nothing is guessed or animated to look busy.
 */

import {
  AlertTriangle,
  Check,
  Clapperboard,
  FileText,
  Loader2,
  PenLine,
  Save,
  ScanSearch,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { UseGenerationStream } from '@/api/useGenerationStream'
import { Badge, Button } from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import type { GenerationStage } from '@/types/storyweaver'

/** The LangGraph flow, as the five steps an author would name. */
const STEPS: { stage: GenerationStage; label: string; icon: LucideIcon }[] = [
  { stage: 'planning', label: '디렉터 (Director)', icon: Clapperboard },
  { stage: 'simulating', label: '장면 시뮬레이터 (Runner)', icon: Users },
  { stage: 'checking', label: '설정 검증 (Checker)', icon: ScanSearch },
  { stage: 'writing', label: '작가 (Writer)', icon: PenLine },
  { stage: 'recording', label: '메모리 저장 (Memory)', icon: Save },
]

/** Which step is lit, and which are behind it. */
function stepIndex(stage: GenerationStage | '' | undefined): number {
  if (!stage) return -1
  // Assembly is the Writer finishing up; it gets no step of its own.
  if (stage === 'assembling') return STEPS.length - 2
  return STEPS.findIndex((step) => step.stage === stage)
}

function elapsedLabel(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}초`
  return `${Math.floor(seconds / 60)}분 ${String(seconds % 60).padStart(2, '0')}초`
}

export function GenerationOverlay({
  generation,
  episodeTitle,
  onClose,
  onRead,
}: {
  generation: UseGenerationStream
  episodeTitle: string
  onClose: () => void
  onRead: () => void
}) {
  const { status, episodeNumber, start, progress, log, result, error, startedAt, finishedAt } =
    generation

  const [now, setNow] = useState(() => Date.now())
  const logRef = useRef<HTMLDivElement>(null)

  // One second is the right resolution for a run measured in minutes, and it
  // stops the moment the run does.
  useEffect(() => {
    if (finishedAt !== null || startedAt === null) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [startedAt, finishedAt])

  // Follow the tail of the log, the way a terminal does.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [log.length])

  if (status === 'idle') return null

  const done = status === 'complete'
  const failed = status === 'error'
  const running = !done && !failed
  const elapsed = startedAt === null ? 0 : (finishedAt ?? now) - startedAt
  const current = stepIndex(progress?.stage)
  const fraction = done ? 1 : (progress?.fraction ?? 0.02)

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={`제${episodeNumber}화 집필 중`}
        className="sw-glass animate-rise relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl"
      >
        {/* --- Header --- */}
        <header className="flex items-start justify-between gap-4 border-b border-line-strong px-6 py-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2.5 text-base font-semibold tracking-tight text-ink">
              {running && <Loader2 className="size-4 shrink-0 animate-spin text-accent-bright" />}
              {done && <Check className="size-4 shrink-0 text-good-bright" />}
              {failed && <AlertTriangle className="size-4 shrink-0 text-bad-bright" />}
              <span className="truncate">
                {done ? '집필 완료' : failed ? '생성 실패' : '집필 중'} · 제{episodeNumber}화
              </span>
            </h2>
            {episodeTitle && <p className="mt-0.5 truncate text-xs text-ink-muted">{episodeTitle}</p>}
          </div>
          {/* Closing mid-run only stops watching; the backend keeps going. */}
          <button
            type="button"
            onClick={onClose}
            title={running ? '화면 닫기 (백그라운드에서 집필 지속)' : '닫기'}
            aria-label={running ? '화면 닫기' : '닫기'}
            className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-muted transition-colors hover:bg-white/5 hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {/* --- Resumption notice --- */}
          {start?.resuming_from_scene != null && (
            <div className="mb-5 rounded-xl border border-accent/25 bg-accent/8 px-4 py-2.5 text-xs leading-relaxed text-accent-bright">
              장면 {start.resuming_from_scene}부터 이어쓰는 중 — 이전 {start.resuming_from_scene - 1}개 장면은 이미 작성되어 저장되어 있습니다.
            </div>
          )}

          <Stepper current={current} running={running} done={done} failed={failed} />

          {/* --- Progress --- */}
          <div className="mt-6">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <p className="min-w-0 truncate text-sm text-ink">
                {failed ? '생성 중단됨' : (progress?.label ?? '연결 중…')}
              </p>
              <span className="shrink-0 font-mono text-xs tabular-nums text-ink-muted">
                {Math.round(fraction * 100)}%
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className={cn(
                  'h-full rounded-full transition-[width] duration-700 ease-[cubic-bezier(0.22,1,0.36,1)]',
                  failed ? 'bg-bad' : done ? 'bg-good' : 'bg-accent',
                )}
                style={{ width: `${Math.max(fraction * 100, 2)}%` }}
              />
            </div>
          </div>

          {/* --- The scene in flight --- */}
          {progress?.scene && running && (
            <div className="mt-5 rounded-xl border border-line bg-surface/60 px-4 py-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-ink">
                  장면 {progress.scene.number}
                  {progress.total_scenes > 0 && `/${progress.total_scenes}`} ·{' '}
                  {progress.scene.title}
                </span>
                {progress.retry_count > 0 && (
                  <Badge tone="warn">재시도 {progress.retry_count}</Badge>
                )}
              </div>
              {progress.scene.objective && (
                <p className="mt-1.5 text-xs leading-relaxed text-ink-dim">
                  <span className="text-ink-muted">장면 목표 — </span>
                  {progress.scene.objective}
                </p>
              )}
              {progress.scene.characters.length > 0 && (
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  <Users className="size-3 text-ink-muted" aria-hidden />
                  {progress.scene.characters.map((name) => (
                    <Badge key={name}>{name}</Badge>
                  ))}
                </div>
              )}
              {progress.stage === 'simulating' && progress.turns > 0 && (
                <p className="mt-2.5 font-mono text-xs text-ink-muted">
                  {progress.turns}/{progress.max_turns} 턴 진행
                </p>
              )}
            </div>
          )}

          {/* --- The running log --- */}
          <div className="mt-5">
            <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
              에이전트 실행 로그
            </p>
            <div
              ref={logRef}
              className="max-h-52 space-y-1 overflow-y-auto rounded-xl border border-line bg-surface/60 px-4 py-3 font-mono text-xs leading-relaxed"
            >
              {log.length === 0 && <p className="text-ink-muted">첫 번째 작업 단계 대기 중…</p>}
              {log.map((line, index) => (
                <p key={index} className="flex items-start gap-2 text-ink-dim">
                  <Check className="mt-0.5 size-3 shrink-0 text-good" aria-hidden />
                  <span>{line}</span>
                </p>
              ))}
              {running && progress && (
                <p className="flex items-start gap-2 text-accent-bright">
                  <Loader2 className="mt-0.5 size-3 shrink-0 animate-spin" aria-hidden />
                  <span>{progress.label}</span>
                </p>
              )}
            </div>
          </div>

          {/* --- Failure --- */}
          {failed && error && (
            <div className="mt-5 rounded-xl border border-bad/30 bg-bad/8 px-4 py-3.5">
              <p className="text-sm font-medium text-bad-bright">{error.type}</p>
              <p className="mt-1 text-xs leading-relaxed break-words text-ink-dim">
                {error.message}
              </p>
              <p className="mt-2.5 text-xs leading-relaxed text-ink-muted">
                {error.resumable
                  ? `이전에 작성된 ${error.scenes_completed}개 장면은 디스크에 안전하게 보존되었습니다. 다시 생성하면 처음부터 시작하지 않고 중단된 지점부터 이어서 집필합니다.`
                  : '작성된 본문이 없어 유실된 내용이 없습니다. 에피소드가 큐로 복귀되었습니다.'}
              </p>
            </div>
          )}

          {/* --- Result --- */}
          {done && result && (
            <div className="mt-5 rounded-xl border border-good/25 bg-good/8 px-4 py-3.5">
              <p className="flex items-center gap-2 text-sm font-medium text-good-bright">
                <FileText className="size-4" />
                {result.scenes}개 장면에 걸쳐 총 {formatCount(result.words)}자 집필 완료
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                {result.recorded_to_memory
                  ? '줄거리가 메모리에 요약 및 저장되어, 다음 회차에서 이 사건을 기억하고 참조합니다.'
                  : '메모리에 기록되지 않았습니다.'}
              </p>
            </div>
          )}
        </div>

        {/* --- Footer --- */}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line-strong px-6 py-3.5">
          <div className="flex items-center gap-3 font-mono text-xs tabular-nums text-ink-muted">
            <span>{elapsedLabel(elapsed)}</span>
            {(progress?.tokens ?? result?.usage?.total_tokens ?? 0) > 0 && (
              <>
                <span aria-hidden>·</span>
                <span>
                  {formatCount(result?.usage?.total_tokens ?? progress?.tokens ?? 0)} 토큰
                </span>
              </>
            )}
            {(result?.usage?.calls ?? progress?.calls ?? 0) > 0 && (
              <>
                <span aria-hidden>·</span>
                <span>{result?.usage?.calls ?? progress?.calls}회 호출</span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button onClick={onClose}>{running ? '화면 닫기' : '닫기'}</Button>
            {done && (
              <Button variant="primary" onClick={onRead}>
                본문 읽기
              </Button>
            )}
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

// --------------------------------------------------------------------------

function Stepper({
  current,
  running,
  done,
  failed,
}: {
  current: number
  running: boolean
  done: boolean
  failed: boolean
}) {
  return (
    <ol className="flex items-center gap-1.5 overflow-x-auto pb-1">
      {STEPS.map((step, index) => {
        const isDone = done || index < current
        const isActive = running && index === current
        const Icon = step.icon

        return (
          <li key={step.stage} className="flex min-w-0 flex-1 items-center gap-1.5">
            <div
              className={cn(
                'flex min-w-0 flex-1 items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors duration-300',
                isActive && 'border-accent/40 bg-accent/12',
                isDone && !isActive && 'border-good/25 bg-good/8',
                !isActive && !isDone && 'border-line bg-surface/50',
                failed && index === current && 'border-bad/40 bg-bad/10',
              )}
            >
              {isDone && !isActive ? (
                <Check className="size-3.5 shrink-0 text-good-bright" aria-hidden />
              ) : isActive ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin text-accent-bright" aria-hidden />
              ) : (
                <Icon className="size-3.5 shrink-0 text-ink-muted" aria-hidden />
              )}
              <span
                className={cn(
                  'truncate text-xs font-medium',
                  isActive ? 'text-ink' : isDone ? 'text-good-bright' : 'text-ink-muted',
                )}
              >
                {step.label}
              </span>
            </div>
            {index < STEPS.length - 1 && (
              <span aria-hidden className="h-px w-2 shrink-0 bg-line-strong" />
            )}
          </li>
        )
      })}
    </ol>
  )
}
