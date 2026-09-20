/**
 * 📝 Episode Queue — outlines in, chapters out.
 *
 * Episode numbers follow position, not identity: episode 4 is whatever is
 * fourth. So every reorder renumbers the queue, and the list re-reads from the
 * backend rather than guessing what the new order became.
 */

import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ClipboardList,
  FileStack,
  GripVertical,
  ListOrdered,
  Pencil,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import { useGenerationStream } from '@/api/useGenerationStream'
import { GenerationOverlay } from '@/components/GenerationOverlay'
import { PlanReview } from '@/components/PlanReview'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Modal,
  PageHeader,
  Panel,
  SelectField,
  TextArea,
  TextField,
} from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { Episode, EpisodePlan, Pacing, PendingGeneration } from '@/types/storyweaver'

const PACING_OPTIONS: { value: Pacing; label: string }[] = [
  { value: 'slow', label: '느림 (slow) — 심리 묘사 및 차분한 호흡' },
  { value: 'normal', label: '보통 (normal) — 균형 잡힌 장면 전개' },
  { value: 'fast', label: '빠름 (fast) — 빠른 템포와 긴박한 컷 전환' },
]

const words = (text: string) => text.split(/\s+/).filter(Boolean).length

export function EpisodeQueue() {
  const { project, loading, refresh } = useProject()
  const { success, fromError } = useToast()
  const navigate = useNavigate()
  const generation = useGenerationStream()

  const [adding, setAdding] = useState(false)
  const [batching, setBatching] = useState(false)
  const [editing, setEditing] = useState<Episode | null>(null)
  const [deleting, setDeleting] = useState<Episode | null>(null)
  const [regenerating, setRegenerating] = useState<Episode | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  // The drag source lives in a ref as well as state: `drop` reads it in the
  // same tick that `dragstart` set it, and state would still be the old value.
  // State is only what the dimming renders from.
  const draggingRef = useRef<number | null>(null)
  const [dragging, setDragging] = useState<number | null>(null)
  const [dropTarget, setDropTarget] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [maxTurns, setMaxTurns] = useState(12)
  const [pending, setPending] = useState<PendingGeneration[]>([])
  // The plan under review, and the episode whose plan is being drafted.
  const [reviewing, setReviewing] = useState<Episode | null>(null)
  const [plan, setPlan] = useState<EpisodePlan | null>(null)
  const [planningFor, setPlanningFor] = useState<number | null>(null)

  const episodes = useMemo(
    () => [...(project?.episodes ?? [])].sort((a, b) => a.episode_number - b.episode_number),
    [project],
  )

  const loadPending = useCallback(() => {
    void api
      .getPendingGenerations()
      .then(setPending)
      .catch(() => setPending([]))
  }, [])

  useEffect(loadPending, [loadPending, episodes])

  // A finished run changes the project on disk, so the queue re-reads itself.
  useEffect(() => {
    if (generation.status === 'complete' || generation.status === 'error') {
      void refresh()
      loadPending()
    }
  }, [generation.status, refresh, loadPending])

  // A run nobody is watching — the overlay was closed, or the page reloaded —
  // still finishes and saves on the backend. Poll while one is in flight, so
  // its card flips to "completed" without the author having to reload.
  const unwatched =
    episodes.some((episode) => episode.status === 'in_progress') && !generation.isRunning
  useEffect(() => {
    if (!unwatched) return
    const timer = setInterval(() => {
      void refresh()
      loadPending()
    }, 5000)
    return () => clearInterval(timer)
  }, [unwatched, refresh, loadPending])

  const move = async (episode: Episode, offset: number) => {
    setBusy(true)
    try {
      await api.moveEpisode(episode.episode_number, offset)
      await refresh()
    } catch (cause) {
      fromError(cause, '큐 순서를 변경하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  /** A drop is a move of however many places the card travelled. */
  const drop = async (to: number) => {
    const from = draggingRef.current
    draggingRef.current = null
    setDragging(null)
    setDropTarget(null)
    if (from === null || from === to) return
    setBusy(true)
    try {
      // The backend moves one place at a time and renumbers as it goes, so a
      // multi-place drag is applied as a run of single steps in that direction.
      const step = to > from ? 1 : -1
      for (let at = from; at !== to; at += step) {
        await api.moveEpisode(at, step)
      }
      await refresh()
    } catch (cause) {
      fromError(cause, '큐 순서를 변경하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (episode: Episode) => {
    try {
      await api.deleteEpisode(episode.episode_number)
      await refresh()
      success(`제${episode.episode_number}화가 삭제되고 큐가 재정렬되었습니다`)
    } catch (cause) {
      fromError(cause, '회차를 삭제하지 못했습니다.')
    }
  }

  const requeue = async (episode: Episode) => {
    try {
      await api.updateEpisode(episode.episode_number, { status: 'queued' })
      await refresh()
      success(`제${episode.episode_number}화가 다시 큐에 등록되었습니다`)
    } catch (cause) {
      fromError(cause, '회차를 다시 큐에 넣지 못했습니다.')
    }
  }

  const generate = (episode: Episode) => {
    generation.reset()
    generation.begin(episode.episode_number, maxTurns)
  }

  /** Draft the layout and open it for review. One model call; nothing written. */
  const planEpisode = async (episode: Episode) => {
    setPlanningFor(episode.episode_number)
    try {
      const drafted = await api.draftPlan(episode.episode_number)
      setPlan(drafted)
      setReviewing(episode)
      await refresh()
    } catch (cause) {
      fromError(cause, '기획서를 만들지 못했습니다.')
    } finally {
      setPlanningFor(null)
    }
  }

  const reviewPlan = async (episode: Episode) => {
    try {
      setPlan(await api.getPlan(episode.episode_number))
      setReviewing(episode)
    } catch (cause) {
      fromError(cause, '기획서를 불러오지 못했습니다.')
    }
  }

  const reloadPlan = async (episodeNumber: number) => {
    setPlan(await api.getPlan(episodeNumber))
    await refresh()
  }

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />
  if (!project) return null

  const running = generation.episodeNumber
  const generatingTitle =
    episodes.find((episode) => episode.episode_number === running)?.title ?? ''

  return (
    <>
      <PageHeader
        title="에피소드 큐"
        description="각 회차별 개요를 관리합니다. 디렉터 AI가 개요 사이의 사건과 대사를 유기적으로 채워 넣습니다."
        actions={
          <>
            <Button icon={FileStack} onClick={() => setBatching(true)}>
              일괄 등록
            </Button>
            <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>
              회차 추가
            </Button>
          </>
        }
      />

      {pending.length > 0 && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-accent/25 bg-accent/8 px-4 py-3">
          <RotateCcw className="mt-0.5 size-4 shrink-0 text-accent-bright" aria-hidden />
          <p className="text-xs leading-relaxed text-ink-dim">
            {pending.map((item) => `제${item.episode_number}화`).join(', ')} 생성이 중간에 중단되었습니다.{' '}
            작성 완료된 {pending.reduce((total, item) => total + item.scenes_completed, 0)}개 장면이
            보존되어 있습니다. 다시 생성하면 처음부터 시작하지 않고 중단된 지점부터 이어서 집필합니다.
          </p>
        </div>
      )}

      {episodes.length === 0 ? (
        <Panel>
          <EmptyState
            icon={ListOrdered}
            title="대기 중인 회차가 없습니다"
            description="개요는 한두 문장의 거친 메모여도 충분합니다. 사건 사이의 구체적인 장면 구성은 디렉터 AI가 담당합니다."
            action={
              <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>
                첫 번째 회차 추가
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="space-y-2.5">
          {episodes.map((episode, index) => (
            <EpisodeCard
              key={episode.episode_number}
              episode={episode}
              first={index === 0}
              last={index === episodes.length - 1}
              busy={busy}
              expanded={expanded === episode.episode_number}
              isDragging={dragging === episode.episode_number}
              isDropTarget={dropTarget === episode.episode_number && dragging !== null}
              resumable={pending.some(
                (item) => item.episode_number === episode.episode_number,
              )}
              generating={running === episode.episode_number && generation.isRunning}
              onToggle={() =>
                setExpanded((value) =>
                  value === episode.episode_number ? null : episode.episode_number,
                )
              }
              onMove={(offset) => void move(episode, offset)}
              onEdit={() => setEditing(episode)}
              onDelete={() => setDeleting(episode)}
              onRequeue={() => void requeue(episode)}
              planning={planningFor === episode.episode_number}
              onPlan={() => void planEpisode(episode)}
              onReviewPlan={() => void reviewPlan(episode)}
              onGenerate={() =>
                episode.status === 'completed' ? setRegenerating(episode) : generate(episode)
              }
              onDragStart={() => {
                draggingRef.current = episode.episode_number
                setDragging(episode.episode_number)
              }}
              onDragOver={() => setDropTarget(episode.episode_number)}
              onDrop={() => void drop(episode.episode_number)}
              onDragEnd={() => {
                draggingRef.current = null
                setDragging(null)
                setDropTarget(null)
              }}
            />
          ))}
        </div>
      )}

      <Panel
        title="생성 설정"
        description="다음 생성 시 적용됩니다. 각 장면은 목표가 달성되면 지정된 턴 수보다 일찍 끝날 수 있습니다."
        className="mt-5"
      >
        <TextField
          label="장면당 최대 턴 수 (상한)"
          type="number"
          min={2}
          max={40}
          value={maxTurns}
          onChange={(event) => setMaxTurns(Number(event.target.value) || 12)}
          className="max-w-48"
        />
      </Panel>

      {/* --- Overlays --- */}

      <PlanReview
        open={reviewing !== null}
        // Re-read from the queue, so a save elsewhere is reflected here.
        episode={
          episodes.find((e) => e.episode_number === reviewing?.episode_number) ?? reviewing
        }
        episodeNumber={reviewing?.episode_number ?? 0}
        episodeTitle={reviewing?.title ?? ''}
        plan={plan}
        characters={project.characters}
        locations={project.world.locations}
        onClose={() => setReviewing(null)}
        onChanged={() => reloadPlan(reviewing?.episode_number ?? 0)}
        onApprove={() => {
          const approved = reviewing
          setReviewing(null)
          if (approved) generate(approved)
        }}
      />

      <GenerationOverlay
        generation={generation}
        episodeTitle={generatingTitle}
        onClose={() => {
          generation.stop()
          generation.reset()
        }}
        onRead={() => {
          generation.reset()
          navigate('/reading')
        }}
      />

      <AddEpisodeModal
        open={adding}
        nextNumber={episodes.length + 1}
        onClose={() => setAdding(false)}
        onAdded={refresh}
      />

      <BatchAddModal open={batching} onClose={() => setBatching(false)} onAdded={refresh} />

      <EditEpisodeModal
        episode={editing}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title={`제${deleting?.episode_number}화를 삭제하시겠습니까?`}
        message={
          deleting?.status === 'completed' ? (
            <>
              이 회차는 이미 작성 완료되었습니다 ({formatCount(words(deleting.final_text))} 단어).
              삭제하면 작성된 본문이 영구 삭제됩니다.
              <p className="mt-2 text-ink-muted">
                삭제 시 이후 회차들의 번호가 하나씩 앞당겨져 자동으로 재정렬됩니다.
              </p>
            </>
          ) : (
            '삭제 시 이후 회차들의 번호가 하나씩 앞당겨져 자동으로 재정렬됩니다.'
          )
        }
      />

      <ConfirmDialog
        open={regenerating !== null}
        onClose={() => setRegenerating(null)}
        onConfirm={() => {
          if (regenerating) generate(regenerating)
        }}
        title={`제${regenerating?.episode_number}화를 다시 생성하시겠습니까?`}
        confirmLabel="다시 생성"
        destructive={false}
        message={
          <>
            기존에 작성된 본문({formatCount(words(regenerating?.final_text ?? ''))} 단어)은
            새로 생성되는 본문으로 완전히 덮어씌워집니다.
            <p className="mt-2 text-ink-muted">
              이어서 쓰지 않고 처음부터 새로 집필되며, 기존 진행 체크포인트는 초기화됩니다.
            </p>
          </>
        }
      />
    </>
  )
}

// ==========================================================================
// Card
// ==========================================================================

const STATUS_TONE = {
  queued: 'violet',
  planned: 'accent',
  in_progress: 'warn',
  completed: 'good',
} as const

const STATUS_LABELS = {
  queued: '대기 중',
  planned: '기획서 검토 대기',
  in_progress: '집필 중',
  completed: '완료',
} as const

function EpisodeCard({
  episode,
  first,
  last,
  busy,
  expanded,
  isDragging,
  isDropTarget,
  resumable,
  generating,
  planning,
  onToggle,
  onMove,
  onEdit,
  onDelete,
  onRequeue,
  onGenerate,
  onPlan,
  onReviewPlan,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  episode: Episode
  first: boolean
  last: boolean
  busy: boolean
  expanded: boolean
  isDragging: boolean
  isDropTarget: boolean
  resumable: boolean
  generating: boolean
  planning: boolean
  onToggle: () => void
  onMove: (offset: number) => void
  onEdit: () => void
  onDelete: () => void
  onRequeue: () => void
  onGenerate: () => void
  onPlan: () => void
  onReviewPlan: () => void
  onDragStart: () => void
  onDragOver: () => void
  onDrop: () => void
  onDragEnd: () => void
}) {
  const completed = episode.status === 'completed'
  const planned = episode.status === 'planned'
  const count = words(episode.final_text)

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        onDragOver()
      }}
      onDrop={(event) => {
        event.preventDefault()
        onDrop()
      }}
      className={cn(
        'sw-panel group transition-all duration-200',
        isDragging && 'opacity-40',
        isDropTarget && 'border-accent/50 ring-1 ring-accent/30',
      )}
    >
      <div className="flex items-start gap-3 px-4 py-3.5">
        {/* Only the handle starts a drag, so selecting the outline text still works. */}
        <span
          draggable
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          title="드래그하여 순서 변경"
          className="mt-0.5 cursor-grab text-ink-muted opacity-0 transition-opacity group-hover:opacity-100 active:cursor-grabbing"
        >
          <GripVertical className="size-4" />
        </span>

        <span className="mt-0.5 w-7 shrink-0 text-right font-mono text-sm text-ink-muted tabular-nums">
          #{episode.episode_number}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-medium text-ink">
              {episode.title || '(제목 없음)'}
            </h3>
            <Badge tone={STATUS_TONE[episode.status]}>
              <span className={cn(episode.status === 'in_progress' && 'animate-pulse-soft')}>
                {STATUS_LABELS[episode.status]}
              </span>
            </Badge>
            {completed && count > 0 && <Badge>{formatCount(count)} 단어</Badge>}
            {completed && episode.summary.trim() && (
              <Badge tone="accent">요약됨</Badge>
            )}
            {episode.pacing === 'slow' && <Badge tone="accent">느린 호흡</Badge>}
            {episode.pacing === 'fast' && <Badge tone="accent">빠른 호흡</Badge>}
            {resumable && <Badge tone="warn">이어쓰기 가능</Badge>}
          </div>

          <button
            type="button"
            onClick={onToggle}
            className="mt-1.5 flex w-full items-start gap-1.5 text-left"
          >
            <ChevronDown
              className={cn(
                'mt-0.5 size-3 shrink-0 text-ink-muted transition-transform',
                expanded && 'rotate-180',
              )}
              aria-hidden
            />
            <span
              className={cn(
                'text-xs leading-relaxed text-ink-muted',
                expanded ? 'whitespace-pre-wrap' : 'line-clamp-1',
              )}
            >
              {episode.author_storyline || '아직 작성된 개요가 없습니다.'}
            </span>
          </button>

          {expanded && completed && episode.scenes.length > 0 && (
            <ol className="mt-3 space-y-1 border-l border-line pl-3">
              {episode.scenes.map((scene) => (
                <li key={scene.scene_number} className="text-xs text-ink-muted">
                  <span className="text-ink-dim">{scene.scene_number}.</span> {scene.title}
                </li>
              ))}
            </ol>
          )}

          {expanded && completed && episode.summary.trim() && (
            <div className="mt-3 rounded-lg border border-line bg-surface/60 px-3 py-2">
              <p className="mb-1 text-[0.65rem] font-medium tracking-wide text-ink-muted uppercase">
                다음 회차에 전달되는 이전 줄거리 요약
              </p>
              <p className="line-clamp-4 text-xs leading-relaxed text-ink-muted">
                {episode.summary}
              </p>
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            icon={ArrowUp}
            title="위로 이동"
            disabled={first || busy}
            onClick={() => onMove(-1)}
          />
          <IconButton
            icon={ArrowDown}
            title="아래로 이동"
            disabled={last || busy}
            onClick={() => onMove(1)}
          />
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <IconButton icon={Pencil} title="개요 편집" onClick={onEdit} />
          {completed && (
            <IconButton icon={RotateCcw} title="대기열로 되돌리기" onClick={onRequeue} />
          )}
          <IconButton icon={Trash2} title="삭제" onClick={onDelete} />
          {/* Queued -> plan it; planned -> read the plan; written -> start over. */}
          {planned ? (
            <Button
              size="sm"
              variant="primary"
              icon={ClipboardList}
              className="ml-1"
              onClick={onReviewPlan}
            >
              기획서 검토
            </Button>
          ) : (
            <Button
              size="sm"
              variant={completed ? 'secondary' : 'primary'}
              icon={completed ? Sparkles : ClipboardList}
              className="ml-1"
              loading={generating || planning}
              onClick={completed ? onGenerate : onPlan}
            >
              {completed ? '다시 생성' : '기획서 만들기'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

// ==========================================================================
// Add / edit
// ==========================================================================

function AddEpisodeModal({
  open,
  nextNumber,
  onClose,
  onAdded,
}: {
  open: boolean
  nextNumber: number
  onClose: () => void
  onAdded: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [title, setTitle] = useState('')
  const [storyline, setStoryline] = useState('')
  const [pacing, setPacing] = useState<Pacing>('normal')
  const [saving, setSaving] = useState(false)

  const reset = () => {
    setTitle('')
    setStoryline('')
    setPacing('normal')
  }

  const add = async () => {
    setSaving(true)
    try {
      await api.addEpisode(storyline.trim(), title.trim(), pacing)
      await onAdded()
      success(`제${nextNumber}화가 큐에 등록되었습니다`)
      reset()
      onClose()
    } catch (cause) {
      fromError(cause, '회차를 등록하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={`제${nextNumber}화 추가`}
      description="간단한 메모 수준의 개요도 괜찮습니다. AI가 사건 사이를 흥미진진하게 채워 넣습니다."
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button
            variant="primary"
            onClick={() => void add()}
            loading={saving}
            disabled={!storyline.trim()}
          >
            큐에 추가
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="회차 제목 (선택사항)"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="비워두면 본문 작성 후 AI가 어울리는 제목을 자동으로 짓습니다."
        />
        <TextArea
          label="회차 개요"
          rows={9}
          value={storyline}
          onChange={(event) => setStoryline(event.target.value)}
          placeholder="이번 회차에서 일어날 주요 사건과 전개를 대략적으로 적어주세요…"
        />
        <SelectField
          label="전개 속도 (Pacing)"
          value={pacing}
          onChange={(event) => setPacing(event.target.value as Pacing)}
          options={PACING_OPTIONS}
        />
      </div>
    </Modal>
  )
}

function EditEpisodeModal({
  episode,
  onClose,
  onSaved,
}: {
  episode: Episode | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState({ title: '', storyline: '', pacing: 'normal' as Pacing })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (episode) {
      setDraft({
        title: episode.title,
        storyline: episode.author_storyline,
        pacing: episode.pacing,
      })
    }
  }, [episode])

  const storylineChanged =
    episode !== null && draft.storyline.trim() !== episode.author_storyline.trim()

  const save = async () => {
    if (!episode) return
    setSaving(true)
    try {
      await api.updateEpisode(episode.episode_number, {
        title: draft.title,
        author_storyline: draft.storyline,
        pacing: draft.pacing,
      })
      await onSaved()
      success('개요가 저장되었습니다')
      onClose()
    } catch (cause) {
      fromError(cause, '회차를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={episode !== null}
      onClose={onClose}
      wide
      title={`제${episode?.episode_number}화 개요 편집`}
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving}>
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="회차 제목"
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.target.value })}
        />
        <TextArea
          label="회차 개요"
          rows={9}
          value={draft.storyline}
          onChange={(event) => setDraft({ ...draft, storyline: event.target.value })}
        />
        <SelectField
          label="전개 속도 (Pacing)"
          value={draft.pacing}
          onChange={(event) => setDraft({ ...draft, pacing: event.target.value as Pacing })}
          options={PACING_OPTIONS}
        />

        {storylineChanged && (
          <p className="flex items-start gap-2 rounded-lg border border-warn/25 bg-warn/8 px-3 py-2 text-xs leading-relaxed text-warn-bright">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            개요를 변경하면 이 회차의 기존 진행 체크포인트가 초기화됩니다 — 이전 개요를 기반으로 작성된 장면들과 충돌을 방지하기 위함입니다.
          </p>
        )}
      </div>
    </Modal>
  )
}

function BatchAddModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean
  onClose: () => void
  onAdded: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [text, setText] = useState('')
  const [separator, setSeparator] = useState('---')
  const [saving, setSaving] = useState(false)

  const count = text
    .split(separator)
    .map((block) => block.trim())
    .filter(Boolean).length

  const add = async () => {
    setSaving(true)
    try {
      const added = await api.addEpisodesBatch(text, separator)
      await onAdded()
      success(`${added.length}개 회차가 큐에 등록되었습니다`)
      setText('')
      onClose()
    } catch (cause) {
      fromError(cause, '개요 목록을 가져오지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const readFile = async (file: File) => setText(await file.text())

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="일괄 등록 (Batch Add)"
      description="여러 회차의 개요를 구분자로 나누어 한 번에 등록하거나 텍스트 파일을 불러옵니다."
      footer={
        <>
          <span className="mr-auto text-xs text-ink-muted">
            {count === 0 ? '등록할 개요가 없습니다' : `${count}개 회차 준비됨`}
          </span>
          <Button onClick={onClose}>취소</Button>
          <Button
            variant="primary"
            onClick={() => void add()}
            loading={saving}
            disabled={count === 0}
          >
            {count > 0 ? `${count}개 ` : ''}등록하기
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="회차 구분자"
          value={separator}
          onChange={(event) => setSeparator(event.target.value || '---')}
          hint="회차와 회차 사이를 나누는 기준 문자열입니다."
          className="max-w-40"
        />

        <TextArea
          label="개요 목록"
          rows={12}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={`1화에서 일어나는 사건.\n${separator}\n2화에서 일어나는 사건.\n${separator}\n3화에서 일어나는 사건.`}
        />

        <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-muted transition-colors hover:text-ink-dim">
          <input
            type="file"
            accept=".txt,.md"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void readFile(file)
            }}
          />
          <FileStack className="size-3.5" />
          …또는 .txt / .md 파일 불러오기
        </label>
      </div>
    </Modal>
  )
}
