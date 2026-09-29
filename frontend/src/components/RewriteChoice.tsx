/**
 * 완료된 회차를 다시 쓰는 두 가지 길: 기획서는 그대로 두고 본문만 새로 쓰거나,
 * 기획서부터 다시 만들거나. 큐와 읽기 화면이 함께 쓴다.
 */

import { ClipboardList, PenLine } from 'lucide-react'

import { Button, Modal } from '@/components/ui'
import { formatCount } from '@/lib/cn'
import type { Episode } from '@/types/storyweaver'

const words = (text: string) => text.split(/\s+/).filter(Boolean).length

export function RewriteChoice({
  episode,
  onClose,
  onKeepPlan,
  onReplan,
  keepPlanNote,
  replanNote,
}: {
  episode: Episode | null
  onClose: () => void
  /** 지금 기획서대로 본문만 다시 쓴다. */
  onKeepPlan: () => void
  /** 기획서부터 다시 만든다. */
  onReplan: () => void
  keepPlanNote: string
  replanNote: string
}) {
  const scenes = episode?.scenes.length ?? 0
  const count = words(episode?.final_text ?? '')

  const choose = (action: () => void) => {
    onClose()
    action()
  }

  return (
    <Modal
      open={episode !== null}
      onClose={onClose}
      title={`제${episode?.episode_number}화를 어떻게 다시 쓸까요?`}
      description={`지금 본문(${formatCount(count)} 단어)은 새 본문이 저장될 때 바뀝니다. 그 전까지는 그대로 남아 있습니다.`}
      footer={<Button onClick={onClose}>취소</Button>}
    >
      <div className="space-y-3">
        <button
          type="button"
          disabled={scenes === 0}
          onClick={() => choose(onKeepPlan)}
          className="w-full rounded-xl border border-accent/40 bg-accent/8 px-4 py-3 text-left transition-colors hover:bg-accent/12 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="flex items-center gap-2 text-sm font-medium text-ink">
            <PenLine className="size-4 text-accent-bright" aria-hidden />
            본문만 다시 쓰기
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-ink-muted">
            {scenes > 0
              ? `지금 기획서(${scenes}개 장면)는 그대로 두고, 인물 연기부터 본문까지 새로 씁니다. ${keepPlanNote}`
              : '이 회차에는 남아 있는 기획서가 없습니다. 기획서부터 다시 만들어 주세요.'}
          </span>
        </button>

        <button
          type="button"
          onClick={() => choose(onReplan)}
          className="w-full rounded-xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:border-line-strong"
        >
          <span className="flex items-center gap-2 text-sm font-medium text-ink">
            <ClipboardList className="size-4 text-ink-dim" aria-hidden />
            기획서부터 다시
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-ink-muted">
            디렉터가 장면 구성을 새로 짭니다. {replanNote}
          </span>
        </button>
      </div>
    </Modal>
  )
}
