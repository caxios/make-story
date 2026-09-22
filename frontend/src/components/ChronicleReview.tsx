/**
 * 회차를 쓰고 난 뒤, AI가 남긴 기록을 작가가 확인하는 자리.
 *
 * 이 관문이 있는 이유는 하나다. 연대기는 작가가 처음 쓴 설정을 이긴다 —
 * 그래서 AI가 지어낸 변화가 확인 없이 들어가면, 그 뒤의 모든 회차가 그것을
 * 사실로 알고 쓰인다. 승인하기 전까지 이 기록들은 아무 데도 쓰이지 않는다.
 *
 * 기획서 승인과 같은 모양이다. 쓰기 전에 한 번, 쓰고 나서 한 번.
 */

import { CheckCircle2, Circle, ScrollText } from 'lucide-react'
import { useMemo, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import { Badge, Button, EmptyState, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { ChronicleEntry, EntryKind } from '@/types/storyweaver'

const KIND_LABELS: Record<EntryKind, string> = {
  initial: '처음',
  changed: '변함',
  added: '생김',
  revealed: '밝혀짐',
  removed: '사라짐',
  restored: '되돌아옴',
}

const SECTION_LABELS: Record<string, string> = {
  summary: '개요',
  appearance: '외모',
  personality: '성격',
  speech: '말투',
  role: '역할',
  values: '가치관',
  goals: '목표',
  backstory: '과거',
  secrets: '비밀',
  deeds: '작중 행적',
  description: '개요',
  features: '특징',
  state: '상태',
  statement: '조문',
  exceptions: '예외',
  active: '효력',
  overview: '개요',
  tone: '분위기',
  era: '시대',
  events: '주요 사건',
}

function sectionLabel(key: string): string {
  if (key.startsWith('relationship:')) return `인간관계 · ${key.slice('relationship:'.length)}`
  return SECTION_LABELS[key] ?? key
}

export function ChronicleReview({
  open,
  episodeNumber,
  onClose,
  onApplied,
}: {
  open: boolean
  episodeNumber?: number
  onClose: () => void
  onApplied?: () => void
}) {
  const { success, fromError } = useToast()

  const [entries, setEntries] = useState<ChronicleEntry[] | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [loadedFor, setLoadedFor] = useState<number | 'all' | null>(null)

  const key = episodeNumber ?? 'all'
  if (open && loadedFor !== key) {
    setLoadedFor(key)
    setEntries(null)
    void api
      .getPendingReview(episodeNumber)
      .then((review) => {
        setEntries(review.entries)
        // Everything starts accepted. The summarizer is right far more often
        // than not, and a gate that makes the author tick twenty boxes to get
        // the ordinary outcome is a gate they will stop reading.
        setChosen(new Set(review.entries.map((entry) => entry.entry_id)))
      })
      .catch((cause) => {
        fromError(cause, '기록을 불러오지 못했습니다.')
        setEntries([])
      })
  }

  const grouped = useMemo(() => {
    const groups = new Map<string, ChronicleEntry[]>()
    for (const entry of entries ?? []) {
      const label = `${entry.subject_id}`
      groups.set(label, [...(groups.get(label) ?? []), entry])
    }
    return [...groups.entries()]
  }, [entries])

  const toggle = (entryId: string) =>
    setChosen((current) => {
      const next = new Set(current)
      if (next.has(entryId)) next.delete(entryId)
      else next.add(entryId)
      return next
    })

  const apply = async () => {
    if (!entries) return
    setBusy(true)
    try {
      const accept = entries.filter((e) => chosen.has(e.entry_id)).map((e) => e.entry_id)
      const discard = entries.filter((e) => !chosen.has(e.entry_id)).map((e) => e.entry_id)
      await api.applyChronicleReview({ accept, discard }, episodeNumber)
      success(
        discard.length > 0
          ? `${accept.length}건을 기록하고 ${discard.length}건은 버렸습니다.`
          : `${accept.length}건을 기록했습니다.`,
      )
      setLoadedFor(null)
      onApplied?.()
      onClose()
    } catch (cause) {
      fromError(cause, '반영하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const close = () => {
    setLoadedFor(null)
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={close}
      wide
      title={episodeNumber ? `${episodeNumber}화가 남긴 기록` : '확인을 기다리는 기록'}
      description="승인한 것만 위키에 남고, 다음 회차를 쓸 때 AI가 보게 됩니다. 지금은 아무 데도 쓰이지 않습니다."
      footer={
        entries && entries.length > 0 ? (
          <>
            <Button
              variant="ghost"
              onClick={() => setChosen(new Set())}
              disabled={busy}
            >
              전부 해제
            </Button>
            <Button
              variant="ghost"
              onClick={() => setChosen(new Set(entries.map((e) => e.entry_id)))}
              disabled={busy}
            >
              전부 선택
            </Button>
            <Button variant="primary" loading={busy} disabled={busy} onClick={() => void apply()}>
              {chosen.size}건 기록하기
              {entries.length - chosen.size > 0 && ` (${entries.length - chosen.size}건 버림)`}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={close}>
            닫기
          </Button>
        )
      }
    >
      {entries === null ? (
        <div className="h-40 animate-pulse-soft rounded-lg bg-white/2" />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="확인할 기록이 없습니다"
          description="이번 회차에서 설정이 달라진 것은 없었습니다. 근거를 대지 못한 변화는 애초에 기록되지 않습니다."
        />
      ) : (
        <div className="space-y-4">
          {grouped.map(([subject, group]) => (
            <div key={subject}>
              <h4 className="mb-2 font-mono text-xs text-ink-muted">{subject}</h4>
              <div className="space-y-2">
                {group.map((entry) => {
                  const picked = chosen.has(entry.entry_id)
                  return (
                    <button
                      key={entry.entry_id}
                      type="button"
                      onClick={() => toggle(entry.entry_id)}
                      className={cn(
                        'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors',
                        picked
                          ? 'border-accent/40 bg-accent/5'
                          : 'border-line opacity-60 hover:opacity-100',
                      )}
                    >
                      {picked ? (
                        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-accent" />
                      ) : (
                        <Circle className="mt-0.5 size-5 shrink-0 text-ink-muted" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <Badge>{sectionLabel(entry.section_key)}</Badge>
                          <Badge tone="accent">{KIND_LABELS[entry.kind]}</Badge>
                        </span>
                        <span className="mt-1.5 block text-sm leading-relaxed text-ink">
                          {entry.previous && (
                            <>
                              <span className="text-ink-muted">{entry.previous}</span>
                              <span className="mx-1.5 text-ink-muted">→</span>
                            </>
                          )}
                          {entry.value}
                        </span>
                        {entry.reason && (
                          <span className="mt-1 block text-xs leading-relaxed text-ink-muted">
                            {entry.reason}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
