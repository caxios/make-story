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
      success('요약이 저장되었습니다 — 이후 회차 생성 시 반영됩니다')
      setEditing(false)
    } catch (cause) {
      fromError(cause, '요약을 저장하지 못했습니다.')
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
      success('본문 내용을 바탕으로 요약을 다시 작성했습니다')
    } catch (cause) {
      fromError(cause, '회차 요약을 다시 생성하지 못했습니다.')
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
            회차 기억 (요약)
          </span>
          {!open && (
            <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
              {empty ? '아직 요약되지 않음' : episode.summary}
            </span>
          )}
        </button>

        <div className="flex shrink-0 items-center gap-1">
          {open && !editing && (
            <>
              <IconButton
                icon={RefreshCw}
                title="본문 내용을 바탕으로 요약 다시 작성"
                onClick={() => void regenerate()}
                disabled={regenerating}
                className={cn(regenerating && 'animate-pulse-soft')}
              />
              <IconButton
                icon={Pencil}
                title="요약 직접 편집"
                onClick={() => setEditing(true)}
              />
            </>
          )}
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="rounded-md px-1.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            {open ? '접기' : '펼치기'}
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-line px-4 py-3.5">
          <p className="mb-3 text-xs leading-relaxed text-ink-muted">
            다음 회차를 집필할 때 AI가 참고하는 이전 줄거리 요약입니다. 본문 마지막 결말 문맥과 함께
            디렉터 AI에게 전달됩니다. 여기서 세부 사항을 다듬으면 이후 생성되는 모든 회차에 수정된
            연속성이 반영됩니다.
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
                  취소
                </Button>
                <Button
                  variant="primary"
                  icon={Check}
                  onClick={() => void save()}
                  loading={saving}
                  disabled={draft === episode.summary}
                >
                  저장
                </Button>
              </div>
            </div>
          ) : empty ? (
            <div className="flex flex-col items-start gap-2.5">
              <p className="text-sm text-ink-dim">
                아직 저장된 요약이 없습니다. 이전 버전에서 집필되었거나 요약 생성이 건너뛰어진 회차입니다.
              </p>
              <Button
                icon={RefreshCw}
                onClick={() => void regenerate()}
                loading={regenerating}
              >
                지금 본문 요약하기
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
