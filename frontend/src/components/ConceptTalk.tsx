/**
 * 대화로 기획하기 — 빈손에서, 말을 주고받으며.
 *
 * 제안 세 개를 받아 고르는 쪽은 "뭐라도 보여줘"에 답한다. 이쪽은 "같이 정해
 * 보자"에 답한다. 무엇을 쓰고 싶은지 아직 스스로도 모르는 작가에게 필요한 건
 * 완성된 선택지가 아니라, 자기가 원하는 걸 알아차리게 만드는 질문이다.
 *
 * 둘은 탭으로 나란히 있고 서로를 밀어내지 않는다. 대화하다 제안이 보고 싶어질
 * 수도, 제안 세 개가 다 안 맞아서 대화로 넘어올 수도 있다. 어느 쪽이든 다른
 * 쪽을 버려야만 갈 수 있다면 그건 선택지가 아니다.
 *
 * 여기서는 대화 기록 자체가 상태다 — 이 앱에서 유일하게 모델에게 지난 대화를
 * 다시 보내는 자리이고, 유일하게 쓸수록 비용이 늘어나는 자리다. 짧게 주고받게
 * 만든 건 그래서다.
 */

import { MessagesSquare, Send, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Button, Panel, TextArea } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { ConceptMessage } from '@/types/storyweaver'

const OPENERS = [
  '뭘 쓰고 싶은지 아직 잘 모르겠어. 같이 정해보자.',
  '요즘 읽고 싶은데 없는 이야기가 하나 있어.',
  '주인공이 거짓말쟁이인 이야기를 쓰고 싶어.',
]

export function ConceptTalk({
  messages,
  draft,
  onDraftChange,
  busy,
  onSend,
  onBuild,
  onClear,
}: {
  messages: ConceptMessage[]
  draft: string
  onDraftChange: (value: string) => void
  busy: string
  onSend: () => void
  onBuild: () => void
  onClear: () => void
}) {
  const endRef = useRef<HTMLDivElement>(null)

  // 답이 도착하면 그쪽으로 따라 내려간다. 대화는 아래가 현재다.
  useEffect(() => {
    if (messages.length > 0) endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [messages.length, busy])

  const spoke = messages.some((message) => message.role === 'author')

  return (
    <Panel
      title="대화하며 함께 기획하기"
      description="정해진 순서는 없습니다. 떠오르는 대로 말씀하시면 됩니다. 대화는 저장되니 창을 닫았다 오셔도 이어집니다."
      actions={
        spoke && (
          <Button size="sm" variant="ghost" icon={Trash2} disabled={Boolean(busy)} onClick={onClear}>
            대화 비우기
          </Button>
        )
      }
    >
      {messages.length === 0 ? (
        <div className="rounded-lg border border-line p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-ink">
            <MessagesSquare className="size-4 text-accent-bright" />
            아무 말이나 먼저 건네 보세요
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
            완성된 생각이 아니어도 괜찮습니다. 장면 하나, 인물 하나, 느낌 한 줄이면
            거기서부터 같이 끌어냅니다.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {OPENERS.map((opener) => (
              <button
                key={opener}
                type="button"
                onClick={() => onDraftChange(opener)}
                className={cn(
                  'rounded-full border border-line px-3 py-1.5 text-xs text-ink-dim',
                  'transition-colors hover:border-line-strong hover:text-ink',
                )}
              >
                {opener}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <ol className="max-h-[26rem] space-y-3 overflow-y-auto pr-1">
          {messages.map((message, index) => (
            <li
              key={`${message.created_at}-${index}`}
              className={cn('flex', message.role === 'author' ? 'justify-end' : 'justify-start')}
            >
              <p
                className={cn(
                  'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap',
                  message.role === 'author'
                    ? 'bg-accent/15 text-ink'
                    : 'border border-line bg-white/3 text-ink-dim',
                )}
              >
                {message.text}
              </p>
            </li>
          ))}
          {busy === 'talk' && (
            <li className="animate-pulse-soft text-xs text-ink-muted">생각하는 중…</li>
          )}
          <li ref={endRef} />
        </ol>
      )}

      <div className="mt-4">
        <TextArea
          rows={3}
          placeholder="편하게 적어 주세요. Ctrl+Enter로 보냅니다."
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
              event.preventDefault()
              onSend()
            }
          }}
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-ink-muted">
            {spoke
              ? '충분히 정해졌다 싶으면 오른쪽에서 기획으로 만드세요.'
              : '아직 아무것도 정하지 않아도 됩니다.'}
          </span>
          <div className="flex gap-2">
            <Button
              icon={Send}
              loading={busy === 'talk'}
              disabled={!draft.trim() || Boolean(busy)}
              onClick={onSend}
            >
              보내기
            </Button>
            <Button
              variant="primary"
              icon={Sparkles}
              loading={busy === 'build'}
              disabled={!spoke || Boolean(busy)}
              onClick={onBuild}
            >
              이 대화로 기획 만들기
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  )
}
