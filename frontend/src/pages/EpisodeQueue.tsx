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
import type { Episode, Pacing, PendingGeneration } from '@/types/storyweaver'

const PACING_OPTIONS: { value: Pacing; label: string }[] = [
  { value: 'slow', label: 'slow — introspective, let it breathe' },
  { value: 'normal', label: 'normal — move when the scene moves' },
  { value: 'fast', label: 'fast — short sentences, hard cuts' },
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

  const move = async (episode: Episode, offset: number) => {
    setBusy(true)
    try {
      await api.moveEpisode(episode.episode_number, offset)
      await refresh()
    } catch (cause) {
      fromError(cause, 'Could not reorder the queue.')
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
      fromError(cause, 'Could not reorder the queue.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (episode: Episode) => {
    try {
      await api.deleteEpisode(episode.episode_number)
      await refresh()
      success(`Episode ${episode.episode_number} deleted, and the queue renumbered`)
    } catch (cause) {
      fromError(cause, 'Could not delete the episode.')
    }
  }

  const requeue = async (episode: Episode) => {
    try {
      await api.updateEpisode(episode.episode_number, { status: 'queued' })
      await refresh()
      success(`Episode ${episode.episode_number} is back in the queue`)
    } catch (cause) {
      fromError(cause, 'Could not re-queue the episode.')
    }
  }

  const generate = (episode: Episode) => {
    generation.reset()
    generation.begin(episode.episode_number, maxTurns)
  }

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />
  if (!project) return null

  const running = generation.episodeNumber
  const generatingTitle =
    episodes.find((episode) => episode.episode_number === running)?.title ?? ''

  return (
    <>
      <PageHeader
        title="Episode Queue"
        description="A rough outline per chapter. The Director fills in the connective tissue."
        actions={
          <>
            <Button icon={FileStack} onClick={() => setBatching(true)}>
              Batch add
            </Button>
            <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>
              Add episode
            </Button>
          </>
        }
      />

      {pending.length > 0 && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-accent/25 bg-accent/8 px-4 py-3">
          <RotateCcw className="mt-0.5 size-4 shrink-0 text-accent-bright" aria-hidden />
          <p className="text-xs leading-relaxed text-ink-dim">
            {pending.map((item) => `Episode ${item.episode_number}`).join(', ')} stopped partway
            through. The{' '}
            {pending.reduce((total, item) => total + item.scenes_completed, 0)} scene
            {pending.reduce((total, item) => total + item.scenes_completed, 0) === 1
              ? ''
              : 's'}{' '}
            already written are saved — generating again picks up from where it left off rather
            than starting over.
          </p>
        </div>
      )}

      {episodes.length === 0 ? (
        <Panel>
          <EmptyState
            icon={ListOrdered}
            title="Nothing queued"
            description="An outline can be a single rough paragraph. Everything between your beats is the Director's job."
            action={
              <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>
                Add the first outline
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
        title="Generation settings"
        description="Applies to the next run. A scene usually ends earlier, when its objective is met."
        className="mt-5"
      >
        <TextField
          label="Turns per scene (cap)"
          type="number"
          min={2}
          max={40}
          value={maxTurns}
          onChange={(event) => setMaxTurns(Number(event.target.value) || 12)}
          className="max-w-48"
        />
      </Panel>

      {/* --- Overlays --- */}

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
        title={`Delete episode ${deleting?.episode_number}?`}
        message={
          deleting?.status === 'completed' ? (
            <>
              This chapter is written — {formatCount(words(deleting.final_text))} words. Deleting
              it throws the prose away.
              <p className="mt-2 text-ink-muted">
                Every later episode moves up a number to close the gap.
              </p>
            </>
          ) : (
            'Every later episode moves up a number to close the gap.'
          )
        }
      />

      <ConfirmDialog
        open={regenerating !== null}
        onClose={() => setRegenerating(null)}
        onConfirm={() => {
          if (regenerating) generate(regenerating)
        }}
        title={`Regenerate episode ${regenerating?.episode_number}?`}
        confirmLabel="Regenerate"
        destructive={false}
        message={
          <>
            The existing chapter — {formatCount(words(regenerating?.final_text ?? ''))} words —
            is overwritten by whatever comes out this time.
            <p className="mt-2 text-ink-muted">
              It starts from scratch rather than resuming, and any saved checkpoint for it is
              cleared.
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
  in_progress: 'warn',
  completed: 'good',
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
  onToggle,
  onMove,
  onEdit,
  onDelete,
  onRequeue,
  onGenerate,
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
  onToggle: () => void
  onMove: (offset: number) => void
  onEdit: () => void
  onDelete: () => void
  onRequeue: () => void
  onGenerate: () => void
  onDragStart: () => void
  onDragOver: () => void
  onDrop: () => void
  onDragEnd: () => void
}) {
  const completed = episode.status === 'completed'
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
          title="Drag to reorder"
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
              {episode.title || '(untitled)'}
            </h3>
            <Badge tone={STATUS_TONE[episode.status]}>
              <span className={cn(episode.status === 'in_progress' && 'animate-pulse-soft')}>
                {episode.status.replace('_', ' ')}
              </span>
            </Badge>
            {completed && count > 0 && <Badge>{formatCount(count)} words</Badge>}
            {episode.pacing !== 'normal' && <Badge tone="accent">{episode.pacing}</Badge>}
            {resumable && <Badge tone="warn">resumable</Badge>}
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
              {episode.author_storyline || 'No outline written yet.'}
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
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            icon={ArrowUp}
            title="Move up"
            disabled={first || busy}
            onClick={() => onMove(-1)}
          />
          <IconButton
            icon={ArrowDown}
            title="Move down"
            disabled={last || busy}
            onClick={() => onMove(1)}
          />
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <IconButton icon={Pencil} title="Edit the outline" onClick={onEdit} />
          {completed && (
            <IconButton icon={RotateCcw} title="Put back in the queue" onClick={onRequeue} />
          )}
          <IconButton icon={Trash2} title="Delete" onClick={onDelete} />
          <Button
            size="sm"
            variant={completed ? 'secondary' : 'primary'}
            icon={Sparkles}
            className="ml-1"
            loading={generating}
            onClick={onGenerate}
          >
            {completed ? 'Regenerate' : 'Generate'}
          </Button>
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
      success(`Episode ${nextNumber} queued`)
      reset()
      onClose()
    } catch (cause) {
      fromError(cause, 'Could not queue the episode.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={`Add episode ${nextNumber}`}
      description="Rough is fine. The Director invents what happens between your beats."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void add()}
            loading={saving}
            disabled={!storyline.trim()}
          >
            Add to queue
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="Title (optional)"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Left blank, the pipeline names it after writing it."
        />
        <TextArea
          label="Outline"
          rows={9}
          value={storyline}
          onChange={(event) => setStoryline(event.target.value)}
          placeholder="이번 회차에서 일어날 이야기를 대략적으로 적어주세요…"
        />
        <SelectField
          label="Pacing"
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
      success('Outline saved')
      onClose()
    } catch (cause) {
      fromError(cause, 'Could not save the episode.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={episode !== null}
      onClose={onClose}
      wide
      title={`Edit episode ${episode?.episode_number}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="Title"
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.target.value })}
        />
        <TextArea
          label="Outline"
          rows={9}
          value={draft.storyline}
          onChange={(event) => setDraft({ ...draft, storyline: event.target.value })}
        />
        <SelectField
          label="Pacing"
          value={draft.pacing}
          onChange={(event) => setDraft({ ...draft, pacing: event.target.value as Pacing })}
          options={PACING_OPTIONS}
        />

        {storylineChanged && (
          <p className="flex items-start gap-2 rounded-lg border border-warn/25 bg-warn/8 px-3 py-2 text-xs leading-relaxed text-warn-bright">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Changing the outline discards any saved checkpoint for this episode — the scenes it
            holds belong to the old outline.
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
      success(`${added.length} episode${added.length === 1 ? '' : 's'} queued`)
      setText('')
      onClose()
    } catch (cause) {
      fromError(cause, 'Could not import the outlines.')
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
      title="Batch add"
      description="Paste or upload several outlines at once, one per section."
      footer={
        <>
          <span className="mr-auto text-xs text-ink-muted">
            {count === 0 ? 'Nothing to add yet' : `${count} outline${count === 1 ? '' : 's'}`}
          </span>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => void add()}
            loading={saving}
            disabled={count === 0}
          >
            Queue {count > 0 ? count : ''}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextField
          label="Separator"
          value={separator}
          onChange={(event) => setSeparator(event.target.value || '---')}
          hint="The line that divides one outline from the next."
          className="max-w-40"
        />

        <TextArea
          label="Outlines"
          rows={12}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={`Chapter one happens.\n${separator}\nChapter two happens.\n${separator}\nChapter three happens.`}
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
          …or load a .txt / .md file
        </label>
      </div>
    </Modal>
  )
}
