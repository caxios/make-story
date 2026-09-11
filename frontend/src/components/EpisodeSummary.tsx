/**
 * The episode's memory: what the next episode will be told about this one.
 *
 * This is not a blurb for the reader. It is the text that gets injected into
 * the next Director's prompt, so an author who spots a wrong nuance here is
 * fixing the continuity of every chapter that follows — which is why it is
 * editable, and why the panel says so.
 */

import { Brain, Check, Pencil, RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import { Button, IconButton } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { Episode } from '@/types/storyweaver'

export function EpisodeSummary({
  episode,
  onChanged,
}: {
  episode: Episode
  onChanged: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(episode.summary)
  const [saving, setSaving] = useState(false)
  const [regenerating, setRegenerating] = useState(false)

  useEffect(() => {
    setDraft(episode.summary)
    setEditing(false)
  }, [episode.episode_number, episode.summary])

  const save = async () => {
    setSaving(true)
    try {
      await api.updateEpisode(episode.episode_number, { summary: draft })
      await onChanged()
      success('Summary saved — later episodes will be told this')
      setEditing(false)
    } catch (cause) {
      fromError(cause, 'Could not save the summary.')
    } finally {
      setSaving(false)
    }
  }

  const regenerate = async () => {
    setRegenerating(true)
    try {
      const updated = await api.summarizeEpisode(episode.episode_number)
      setDraft(updated.summary)
      await onChanged()
      success('Summary rewritten from the chapter')
    } catch (cause) {
      fromError(cause, 'Could not re-summarize the chapter.')
    } finally {
      setRegenerating(false)
    }
  }

  const empty = !episode.summary.trim()

  return (
    <section className="mb-5 rounded-xl border border-line bg-surface/60">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
        >
          <Brain className="size-4 shrink-0 text-ink-muted" aria-hidden />
          <span className="text-xs font-medium tracking-wide text-ink-dim uppercase">
            Episode memory
          </span>
          {!open && (
            <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
              {empty ? 'Not summarized yet' : episode.summary}
            </span>
          )}
        </button>

        <div className="flex shrink-0 items-center gap-1">
          {open && !editing && (
            <>
              <IconButton
                icon={RefreshCw}
                title="Rewrite the summary from the chapter"
                onClick={() => void regenerate()}
                disabled={regenerating}
                className={cn(regenerating && 'animate-pulse-soft')}
              />
              <IconButton
                icon={Pencil}
                title="Edit the summary"
                onClick={() => setEditing(true)}
              />
            </>
          )}
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="rounded-md px-1.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            {open ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-line px-4 py-3.5">
          <p className="mb-3 text-xs leading-relaxed text-ink-muted">
            This is what the next episode is told about this one — alongside its closing
            passage, which is taken from the prose automatically. Correct a nuance here and
            every later chapter inherits the correction.
          </p>

          {editing ? (
            <div className="space-y-3">
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={10}
                className="sw-field w-full resize-y text-sm leading-relaxed"
              />
              <div className="flex justify-end gap-2">
                <Button
                  icon={X}
                  onClick={() => {
                    setDraft(episode.summary)
                    setEditing(false)
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  icon={Check}
                  onClick={() => void save()}
                  loading={saving}
                  disabled={draft === episode.summary}
                >
                  Save
                </Button>
              </div>
            </div>
          ) : empty ? (
            <div className="flex flex-col items-start gap-2.5">
              <p className="text-sm text-ink-dim">
                No summary yet. Chapters written before summaries were recorded, or a run
                whose summarizer failed, land here.
              </p>
              <Button
                icon={RefreshCw}
                onClick={() => void regenerate()}
                loading={regenerating}
              >
                Summarize it now
              </Button>
            </div>
          ) : (
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-ink-dim">
              {episode.summary}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
