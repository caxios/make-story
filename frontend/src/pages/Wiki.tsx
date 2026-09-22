/**
 * 📖 위키 — 이 작품의 모든 설정과, 그것이 그렇게 된 내력.
 *
 * 문서 목록이다. 인물·세계관·장소·규칙이 각자 문서를 갖고, 회차가 진행되면서
 * 기록이 쌓인다. 기록이 아직 없는 문서도 보인다 — 한 번도 건드려지지 않은
 * 설정이야말로 작가가 찾고 싶어 하는 것일 때가 많기 때문이다.
 */

import { BookMarked, BookOpen, MapPin, Scale, ScrollText, Users } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import { ChronicleReview } from '@/components/ChronicleReview'
import { useToast } from '@/components/ToastContext'
import { Badge, Button, EmptyState, PageHeader, Panel, TextField } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { SubjectType, WikiSubjectRow } from '@/types/storyweaver'

const GROUPS: { type: SubjectType; label: string; icon: typeof Users }[] = [
  { type: 'character', label: '인물', icon: Users },
  { type: 'world', label: '세계관', icon: BookOpen },
  { type: 'location', label: '장소', icon: MapPin },
  { type: 'rule', label: '규칙', icon: Scale },
  { type: 'faction', label: '세력', icon: Users },
]

export function Wiki() {
  const { fromError } = useToast()
  const navigate = useNavigate()

  const [rows, setRows] = useState<WikiSubjectRow[] | null>(null)
  const [query, setQuery] = useState('')
  // Records a chapter left waiting. The modal after a generation is the usual
  // way in, but an author who closed it needs somewhere to come back to —
  // otherwise the proposals sit there counting for nothing and unreachable.
  const [waiting, setWaiting] = useState(0)
  const [reviewing, setReviewing] = useState(false)

  const load = useCallback(async () => {
    try {
      const [subjects, pending] = await Promise.all([
        api.getWikiSubjects(),
        api.getPendingReview().catch(() => ({ entries: [] })),
      ])
      setRows(subjects)
      setWaiting(pending.entries.length)
    } catch (cause) {
      fromError(cause, '위키를 불러오지 못했습니다.')
      setRows([])
    }
  }, [fromError])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle || !rows) return rows ?? []
    return rows.filter(
      (row) =>
        row.title.toLowerCase().includes(needle) ||
        row.subject_id.toLowerCase().includes(needle),
    )
  }, [rows, query])

  const recorded = useMemo(
    () => (rows ?? []).reduce((total, row) => total + row.entry_count, 0),
    [rows],
  )

  if (rows === null) return <div className="sw-panel h-72 animate-pulse-soft" />

  return (
    <div className="space-y-5">
      <PageHeader
        title="위키"
        description={
          recorded > 0
            ? `설정 문서 ${rows.length}개, 기록 ${recorded}건. 각 문서는 지금의 설정과 거기까지 온 내력을 함께 보여줍니다.`
            : '설정 문서입니다. 회차를 쓰면 무엇이 어떻게 변했는지가 여기에 쌓입니다.'
        }
        actions={
          <TextField
            placeholder="문서 검색"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-56"
          />
        }
      />

      {waiting > 0 && (
        <Panel className="border-warn/30">
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm leading-relaxed text-ink-dim">
              확인을 기다리는 기록이 <strong className="text-ink">{waiting}건</strong> 있습니다.
              <span className="mt-1 block text-xs text-ink-muted">
                승인하기 전까지는 위키에도 반영되지 않고, 다음 회차를 쓸 때 AI도 보지
                못합니다.
              </span>
            </p>
            <Button variant="primary" icon={ScrollText} onClick={() => setReviewing(true)}>
              확인하기
            </Button>
          </div>
        </Panel>
      )}

      <ChronicleReview
        open={reviewing}
        onClose={() => setReviewing(false)}
        onApplied={() => void load()}
      />

      {rows.length === 0 ? (
        <Panel>
          <EmptyState
            icon={BookMarked}
            title="아직 문서가 없습니다"
            description="세계관과 인물을 만들면 각자 위키 문서를 갖게 됩니다. 회차를 쓰면 그 문서에 변화가 기록됩니다."
          />
        </Panel>
      ) : (
        GROUPS.map(({ type, label, icon: Icon }) => {
          const group = filtered.filter((row) => row.subject_type === type)
          if (group.length === 0) return null
          return (
            <Panel key={type} title={`${label} (${group.length})`}>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {group.map((row) => (
                  <button
                    key={`${row.subject_type}:${row.subject_id}`}
                    type="button"
                    onClick={() =>
                      navigate(
                        `/wiki/${row.subject_type}/${encodeURIComponent(row.subject_id)}`,
                      )
                    }
                    className={cn(
                      'flex items-start gap-3 rounded-lg border border-line p-3 text-left',
                      'transition-colors hover:border-line-strong hover:bg-white/3',
                    )}
                  >
                    <Icon className="mt-0.5 size-4 shrink-0 text-ink-muted" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {row.title}
                      </span>
                      <span className="mt-1 flex items-center gap-1.5 text-xs text-ink-muted">
                        {row.entry_count > 0 ? (
                          <>
                            <Badge tone="accent">기록 {row.entry_count}건</Badge>
                            {row.last_episode !== null && (
                              <span>최근 {row.last_episode}화</span>
                            )}
                          </>
                        ) : (
                          <span>아직 변한 것이 없습니다</span>
                        )}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </Panel>
          )
        })
      )}

      {rows.length > 0 && filtered.length === 0 && (
        <Panel>
          <EmptyState
            icon={BookMarked}
            title="찾으시는 문서가 없습니다"
            description={`'${query}'와 맞는 문서가 없습니다. 다른 이름으로 찾아보세요.`}
          />
        </Panel>
      )}
    </div>
  )
}
