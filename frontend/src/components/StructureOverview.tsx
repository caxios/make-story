/**
 * 작품 구조 — 목표 분량, 부(파트) 구성, 떡밥 배치를 한눈에.
 *
 * 12화짜리 구상이 12화 만에 결말에 닿았던 건, 개요를 쓰는 단계가 결말은
 * 알아도 결말이 얼마나 먼지는 몰랐기 때문이다. 이 구조가 그 거리를 알려 준다.
 * 부 막대는 실제 비율대로 그린다 — 400화 중 1부 60화가 얼마만큼인지 눈으로
 * 보이는 게 숫자보다 호흡을 더 잘 전한다.
 */

import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { StoryStructure } from '@/types/storyweaver'

const PART_TONES = [
  'bg-accent/25 border-accent/40',
  'bg-violet/25 border-violet/40',
  'bg-good/20 border-good/40',
  'bg-warn/20 border-warn/40',
  'bg-bad/15 border-bad/35',
  'bg-white/8 border-line-strong',
]

export function StructureOverview({
  structure,
  current,
  compact = false,
}: {
  structure: StoryStructure
  /** 지금 위치(다음에 쓸 회차). 막대 위에 표시한다. */
  current?: number
  compact?: boolean
}) {
  const target = structure.target_episodes
  const marker = current !== undefined ? Math.min(current, target) : undefined

  return (
    <div className="space-y-4">
      {/* 부 막대 */}
      <div>
        <div className="relative flex h-9 overflow-hidden rounded-lg border border-line">
          {structure.parts.map((part, index) => (
            <div
              key={`${part.start}-${part.title}`}
              title={`${index + 1}부 ${part.title} (${part.start}~${part.end}화)`}
              className={cn(
                'flex min-w-0 items-center justify-center border-r px-1 text-[0.7rem] text-ink last:border-r-0',
                PART_TONES[index % PART_TONES.length],
              )}
              style={{
                width: `${((part.end - part.start + 1) / target) * 100}%`,
              }}
            >
              <span className="truncate">{index + 1}부</span>
            </div>
          ))}
          {marker !== undefined && (
            <div
              className="absolute inset-y-0 w-0.5 bg-ink"
              style={{ left: `${((marker - 0.5) / target) * 100}%` }}
              title={`다음 회차: ${current}화`}
            />
          )}
        </div>
        <div className="mt-1 flex justify-between text-[0.7rem] text-ink-muted">
          <span>1화</span>
          {marker !== undefined && <span>▲ 다음: {current}화</span>}
          <span>{target}화</span>
        </div>
      </div>

      {/* 부별 설명 */}
      <ol className="space-y-2">
        {structure.parts.map((part, index) => {
          const here = current !== undefined && current >= part.start && current <= part.end
          return (
            <li
              key={`${part.start}-${part.title}`}
              className={cn(
                'rounded-lg border border-line p-3',
                here && 'border-accent/50 bg-accent/5',
              )}
            >
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                {index + 1}부 · {part.title}
                <Badge mono>
                  {part.start}~{part.end}화 ({part.end - part.start + 1}화)
                </Badge>
                {here && <Badge tone="accent">지금 여기</Badge>}
              </p>
              {!compact && part.purpose && (
                <p className="mt-1 text-xs leading-relaxed text-ink-dim">{part.purpose}</p>
              )}
            </li>
          )
        })}
      </ol>

      {/* 떡밥 */}
      {structure.threads.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-ink-muted">
            떡밥 {structure.threads.length}개 — 심는 회차 → 회수하는 회차
          </p>
          <ul className="space-y-1.5">
            {structure.threads.map((thread) => {
              const state =
                current === undefined
                  ? null
                  : current > thread.payoff
                    ? '회수 시점 지남'
                    : current >= thread.plant
                      ? '심어진 상태'
                      : null
              return (
                <li key={`${thread.name}-${thread.plant}`} className="text-xs leading-relaxed">
                  <span className="font-medium text-ink">{thread.name}</span>
                  <span className="ml-1.5 font-mono text-ink-muted">
                    {thread.plant}화 → {thread.payoff}화
                  </span>
                  {state && (
                    <span className="ml-1.5">
                      <Badge tone="neutral">{state}</Badge>
                    </span>
                  )}
                  {!compact && thread.description && (
                    <span className="block text-ink-dim">{thread.description}</span>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* 관계 흐름 */}
      {(structure.relationships ?? []).length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-ink-muted">
            관계 흐름 {structure.relationships.length}개 — 처음 → 결국, 그리고 전환점
          </p>
          <ul className="space-y-2">
            {structure.relationships.map((relationship, index) => {
              const next =
                current === undefined
                  ? undefined
                  : relationship.turns.find((turn) => turn.episode >= current)
              return (
                <li key={`${relationship.characters.join('-')}-${index}`} className="text-xs leading-relaxed">
                  <span className="font-medium text-ink">{relationship.characters.join(' · ')}</span>
                  {next && (
                    <span className="ml-1.5">
                      <Badge tone="violet">다음 전환 {next.episode}화</Badge>
                    </span>
                  )}
                  {!compact && (
                    <>
                      <span className="block text-ink-dim">
                        {relationship.start && `${relationship.start} → `}
                        {relationship.arc}
                      </span>
                      {relationship.turns.length > 0 && (
                        <span className="block text-ink-muted">
                          {relationship.turns
                            .map((turn) => `${turn.episode}화 ${turn.change}`)
                            .join(' · ')}
                        </span>
                      )}
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
