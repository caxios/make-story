/**
 * 한 섹션의 내력.
 *
 * 나무위키 문서처럼, 지금 값 아래에 거기까지 온 단계가 전부 남는다. c→b로
 * 변하고 나중에 b→d로 변했다면 두 줄 모두 남아 있어야 한다 — 나중에 작품
 * 전체를 검수할 때 작가가 어디서 어긋났는지 찾는 근거가 그것이기 때문이다.
 *
 * 그래서 취소는 삭제가 아니다. 취소된 줄은 줄이 그어진 채 남고, 되살릴 수
 * 있다. 흔적까지 없애고 싶은 기록(잘못 적은 것, 중복, 시험 삼아 적은 것)은
 * 삭제로 지운다.
 */

import { RotateCcw, Trash2, Undo2 } from 'lucide-react'

import { Badge, IconButton } from '@/components/ui'
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

const KIND_TONES: Record<EntryKind, 'neutral' | 'accent' | 'good' | 'warn' | 'bad'> = {
  initial: 'neutral',
  changed: 'accent',
  added: 'good',
  revealed: 'warn',
  removed: 'bad',
  restored: 'good',
}

export function Chronicle({
  entries,
  isLog = false,
  onRetract,
  onRestore,
  onDelete,
  busy = false,
}: {
  entries: ChronicleEntry[]
  isLog?: boolean
  onRetract?: (entry: ChronicleEntry) => void
  onRestore?: (entry: ChronicleEntry) => void
  onDelete?: (entry: ChronicleEntry) => void
  busy?: boolean
}) {
  if (entries.length === 0) {
    return (
      <p className="text-xs text-ink-muted">
        {isLog ? '아직 기록된 행적이 없습니다.' : '아직 변한 적이 없습니다.'}
      </p>
    )
  }

  return (
    <ol className="space-y-2 border-l border-line pl-4">
      {entries.map((entry) => {
        const where =
          entry.episode_number === null ? '작가' : `${entry.episode_number}화`
        return (
          <li
            key={entry.entry_id}
            className={cn(
              'relative text-sm',
              (entry.superseded || entry.pending) && 'opacity-45',
            )}
          >
            <span
              className={cn(
                'absolute -left-[1.3rem] top-1.5 size-2 rounded-full',
                entry.pending
                  ? 'bg-warn'
                  : entry.source === 'author'
                    ? 'bg-ink-muted'
                    : 'bg-accent',
              )}
              aria-hidden
            />

            <div className="flex flex-wrap items-center gap-1.5">
              <Badge mono tone={entry.source === 'author' ? 'neutral' : 'accent'}>
                {where}
              </Badge>
              {!isLog && <Badge tone={KIND_TONES[entry.kind]}>{KIND_LABELS[entry.kind]}</Badge>}
              {entry.superseded && <Badge tone="bad">취소됨</Badge>}
              {entry.pending && <Badge tone="warn">확인 대기</Badge>}

              <span className="ml-auto flex items-center gap-1">
                {entry.pending ? null : entry.superseded
                  ? onRestore && (
                      <IconButton
                        icon={RotateCcw}
                        title="되살리기"
                        disabled={busy}
                        onClick={() => onRestore(entry)}
                      />
                    )
                  : onRetract && (
                      <IconButton
                        icon={Undo2}
                        title="이 기록 취소"
                        variant="danger"
                        disabled={busy}
                        onClick={() => onRetract(entry)}
                      />
                    )}
                {!entry.pending && onDelete && (
                  <IconButton
                    icon={Trash2}
                    title="이 기록 삭제"
                    variant="danger"
                    disabled={busy}
                    onClick={() => onDelete(entry)}
                  />
                )}
              </span>
            </div>

            <p
              className={cn(
                'mt-1 leading-relaxed whitespace-pre-wrap text-ink-dim',
                entry.superseded && 'line-through',
              )}
            >
              {!isLog && entry.previous && (
                <>
                  <span className="text-ink-muted">{entry.previous}</span>
                  <span className="mx-1.5 text-ink-muted">→</span>
                </>
              )}
              <span className="text-ink">{entry.value}</span>
            </p>

            {entry.reason && (
              <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">
                {entry.reason}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
