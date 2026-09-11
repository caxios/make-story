/**
 * 📖 Reading Room — the one page that is not a tool.
 *
 * Everything here serves reading: a single column at a comfortable measure,
 * typography the author controls, and the chapter list out of the way until it
 * is wanted. The reader's settings persist per browser, because a reading
 * preference is not something to set twice.
 */

import {
  BookOpen,
  Check,
  Download,
  FileText,
  Pencil,
  RotateCcw,
  Trash2,
  Type,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import { EpisodeSummary } from '@/components/EpisodeSummary'
import { DEFAULT_READER, Prose, type ReaderSettings } from '@/components/Prose'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Modal,
  Panel,
  Slider,
} from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { Episode } from '@/types/storyweaver'

const READER_KEY = 'storyweaver.reader'

const words = (text: string) => text.split(/\s+/).filter(Boolean).length
/** Characters including spaces — the unit Korean web novels are measured in. */
const characters = (text: string) => text.replace(/\r/g, '').length

function loadReader(): ReaderSettings {
  try {
    const stored = localStorage.getItem(READER_KEY)
    return stored ? { ...DEFAULT_READER, ...JSON.parse(stored) } : DEFAULT_READER
  } catch {
    return DEFAULT_READER
  }
}

export function ReadingRoom() {
  const { project, loading, refresh } = useProject()
  const { success, fromError } = useToast()
  const navigate = useNavigate()

  const [selected, setSelected] = useState<number | null>(null)
  const [reader, setReader] = useState<ReaderSettings>(loadReader)
  const [showTypography, setShowTypography] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [regenerating, setRegenerating] = useState(false)

  const completed = useMemo(
    () =>
      (project?.episodes ?? [])
        .filter((episode) => episode.status === 'completed' && episode.final_text.trim())
        .sort((a, b) => a.episode_number - b.episode_number),
    [project],
  )

  useEffect(() => {
    try {
      localStorage.setItem(READER_KEY, JSON.stringify(reader))
    } catch {
      // A browser that refuses storage still gets a working reader.
    }
  }, [reader])

  // Default to the last chapter written, and never point at one that is gone.
  const episode: Episode | null =
    completed.find((item) => item.episode_number === selected) ?? completed.at(-1) ?? null

  const startEditing = () => {
    if (!episode) return
    setDraft(episode.final_text)
    setEditing(true)
  }

  const save = async () => {
    if (!episode) return
    setSaving(true)
    try {
      await api.updateEpisode(episode.episode_number, { final_text: draft })
      await refresh()
      success('Your edits are saved')
      setEditing(false)
    } catch (cause) {
      fromError(cause, 'Could not save the chapter.')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!episode) return
    try {
      await api.deleteEpisode(episode.episode_number)
      await refresh()
      setSelected(null)
      success(`Episode ${episode.episode_number} deleted`)
    } catch (cause) {
      fromError(cause, 'Could not delete the episode.')
    }
  }

  const requeue = async () => {
    if (!episode) return
    try {
      await api.updateEpisode(episode.episode_number, { status: 'queued' })
      await refresh()
      navigate('/episodes')
    } catch (cause) {
      fromError(cause, 'Could not re-queue the episode.')
    }
  }

  const download = async (kind: 'markdown' | 'docx' | 'zip') => {
    if (!episode && kind !== 'zip') return
    try {
      const file =
        kind === 'zip'
          ? await api.downloadProjectArchive()
          : await api.downloadEpisode(episode!.episode_number, kind)
      api.saveBlob(file.blob, file.filename)
      success(`Downloaded ${file.filename}`)
    } catch (cause) {
      fromError(cause, 'Could not build the download.')
    }
  }

  if (loading) return <div className="sw-panel h-96 animate-pulse-soft" />
  if (!project) return null

  if (completed.length === 0 || !episode) {
    return (
      <Panel>
        <EmptyState
          icon={BookOpen}
          title="Nothing written yet"
          description="Finished chapters land here. Queue an outline and generate it in the Episode Queue."
          action={
            <Button variant="primary" onClick={() => navigate('/episodes')}>
              Go to the queue
            </Button>
          }
        />
      </Panel>
    )
  }

  const count = words(episode.final_text)

  return (
    <div className="flex gap-6">
      {/* --- Chapters --- */}
      <nav className="hidden w-52 shrink-0 lg:block">
        <p className="mb-2 px-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
          Chapters
        </p>
        <ol className="space-y-0.5">
          {completed.map((item) => {
            const active = item.episode_number === episode.episode_number
            return (
              <li key={item.episode_number}>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(item.episode_number)
                    setEditing(false)
                  }}
                  className={cn(
                    'w-full rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                    active ? 'bg-accent/12 text-ink' : 'text-ink-dim hover:bg-white/4 hover:text-ink',
                  )}
                >
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-xs text-ink-muted tabular-nums">
                      {item.episode_number}
                    </span>
                    <span className="truncate">{item.title || '(untitled)'}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <div className="min-w-0 flex-1">
        {/* --- Chapter header --- */}
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">Episode {episode.episode_number}</Badge>
              <Badge>{formatCount(count)} words</Badge>
              <Badge>{formatCount(characters(episode.final_text))} chars</Badge>
              {episode.scenes.length > 0 && (
                <Badge>
                  {episode.scenes.length} scene{episode.scenes.length === 1 ? '' : 's'}
                </Badge>
              )}
            </div>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
              {episode.title || '(untitled)'}
            </h2>
          </div>

          <div className="flex items-center gap-1">
            <IconButton
              icon={Type}
              title="Typography"
              onClick={() => setShowTypography(true)}
            />
            <IconButton
              icon={editing ? X : Pencil}
              title={editing ? 'Leave edit mode' : 'Edit this chapter'}
              onClick={() => (editing ? setEditing(false) : startEditing())}
            />
            <IconButton
              icon={RotateCcw}
              title="Regenerate this chapter"
              onClick={() => setRegenerating(true)}
            />
            <IconButton icon={Trash2} title="Delete this chapter" onClick={() => setDeleting(true)} />
          </div>
        </header>

        {/* --- What the next episode will be told about this one --- */}
        <EpisodeSummary episode={episode} onChanged={refresh} />

        {/* --- The chapter --- */}
        {editing ? (
          <div className="space-y-3">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={28}
              spellCheck={false}
              className="sw-field w-full resize-y leading-relaxed"
              style={{
                fontFamily: reader.serif ? 'var(--font-serif)' : 'var(--font-sans)',
                fontSize: `${reader.fontSize}px`,
                lineHeight: reader.lineHeight,
              }}
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-ink-muted">
                {formatCount(words(draft))} words
                {words(draft) !== count &&
                  ` · ${words(draft) > count ? '+' : ''}${formatCount(words(draft) - count)}`}
              </p>
              <div className="flex gap-2">
                <Button onClick={() => setEditing(false)}>Cancel</Button>
                <Button
                  variant="primary"
                  icon={Check}
                  onClick={() => void save()}
                  loading={saving}
                  disabled={draft === episode.final_text}
                >
                  Save changes
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <article className="sw-panel px-6 py-10 sm:px-10">
            <Prose text={episode.final_text} settings={reader} />
          </article>
        )}

        {/* --- Export --- */}
        <Panel
          title="Export"
          description="Built by the backend, so a download matches exactly what is on disk."
          className="mt-6"
        >
          <div className="flex flex-wrap gap-2">
            <Button icon={FileText} onClick={() => void download('markdown')}>
              Chapter .md
            </Button>
            <Button icon={FileText} onClick={() => void download('docx')}>
              Chapter .docx
            </Button>
            <Button icon={Download} onClick={() => void download('zip')}>
              Whole project .zip
            </Button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-muted">
            The archive holds the project file plus everything the story remembers — the vector
            store and the plot threads — so it restores as a working project, not just text.
          </p>
        </Panel>
      </div>

      {/* --- Typography --- */}
      <Modal
        open={showTypography}
        onClose={() => setShowTypography(false)}
        title="Typography"
        description="Yours alone, remembered in this browser."
        footer={
          <>
            <Button onClick={() => setReader(DEFAULT_READER)}>Reset</Button>
            <Button variant="primary" onClick={() => setShowTypography(false)}>
              Done
            </Button>
          </>
        }
      >
        <div className="space-y-5">
          <div>
            <p className="mb-2 text-xs font-medium text-ink-dim">Face</p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { serif: true, label: 'Editorial serif', sample: 'Lora' },
                { serif: false, label: 'Modern sans', sample: 'Inter' },
              ].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setReader({ ...reader, serif: option.serif })}
                  className={cn(
                    'rounded-xl border px-4 py-3 text-left transition-colors',
                    reader.serif === option.serif
                      ? 'border-accent/40 bg-accent/10'
                      : 'border-line bg-surface hover:border-line-strong',
                  )}
                >
                  <span
                    className="block text-lg text-ink"
                    style={{
                      fontFamily: option.serif ? 'var(--font-serif)' : 'var(--font-sans)',
                    }}
                  >
                    별이 지는 밤
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-muted">{option.label}</span>
                </button>
              ))}
            </div>
          </div>

          <Slider
            label="Size"
            min={16}
            max={24}
            step={1}
            value={reader.fontSize}
            onChange={(fontSize) => setReader({ ...reader, fontSize })}
            format={(value) => `${value}px`}
          />
          <Slider
            label="Line spacing"
            min={1.6}
            max={2.2}
            step={0.05}
            value={reader.lineHeight}
            onChange={(lineHeight) => setReader({ ...reader, lineHeight })}
            format={(value) => value.toFixed(2)}
          />
          <Slider
            label="Column width"
            min={55}
            max={80}
            step={1}
            value={reader.measure}
            onChange={(measure) => setReader({ ...reader, measure })}
            format={(value) => `${value} characters`}
          />

          <div className="rounded-xl border border-line bg-surface px-4 py-3">
            <Prose
              text={'"이건 아무것도 아니야." 그는 말했다.\n\nThe corridor smelled of cold stone and older rain.'}
              settings={reader}
              className="!max-w-none"
            />
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={deleting}
        onClose={() => setDeleting(false)}
        onConfirm={() => void remove()}
        title={`Delete episode ${episode.episode_number}?`}
        message={
          <>
            {formatCount(count)} words of finished prose go with it, and every later episode
            moves up a number to close the gap.
          </>
        }
      />

      <ConfirmDialog
        open={regenerating}
        onClose={() => setRegenerating(false)}
        onConfirm={() => void requeue()}
        title={`Regenerate episode ${episode.episode_number}?`}
        confirmLabel="Re-queue it"
        destructive={false}
        message={
          <>
            This puts the chapter back in the queue and takes you there. The existing{' '}
            {formatCount(count)} words stay on disk until you actually generate it again.
          </>
        }
      />
    </div>
  )
}
