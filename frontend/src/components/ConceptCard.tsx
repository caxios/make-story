/**
 * 컨셉 하나를 읽을 수 있게.
 *
 * 제안 단계에서는 셋을 나란히 놓고 고르는 카드로, 고른 뒤에는 통째로 펼친
 * 문서로 쓰인다. 같은 컴포넌트인 이유는 같은 것이기 때문이다 — 작가가 고른
 * 것은 카드가 아니라 컨셉이고, 다듬는 동안에도 계속 그 컨셉이다.
 */

import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { StoryConcept } from '@/types/storyweaver'

export function ConceptCard({
  concept,
  expanded = false,
  className,
  action,
}: {
  concept: StoryConcept
  /** Folded in the spread, open once it is the one being refined. */
  expanded?: boolean
  className?: string
  action?: React.ReactNode
}) {
  const [open, setOpen] = useState(expanded)

  return (
    <section className={cn('sw-panel flex flex-col p-5', className)}>
      <header className="min-w-0">
        <h3 className="text-base font-semibold tracking-tight text-ink">
          {concept.title || '(제목 없음)'}
        </h3>
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Badge tone="accent">{concept.genre}</Badge>
          <Badge>{concept.tone}</Badge>
          {concept.era && <Badge>{concept.era}</Badge>}
        </p>
        <p className="mt-3 text-sm leading-relaxed text-ink-dim">{concept.logline}</p>
      </header>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink-muted">
        <Count label="인물" value={concept.characters.length} />
        <Count label="규칙" value={concept.rules.length} />
        <Count label="장소" value={concept.locations.length} />
        {/* Only once there is an outline. A proposal has none by design — it is
            drawn for the one the author keeps — and showing a zero here reads
            as something missing. */}
        {concept.episodes.length > 0 && (
          <Count label="회차 구상" value={concept.episodes.length} />
        )}
      </dl>

      {concept.characters.length > 0 && (
        <p className="mt-3 text-xs leading-relaxed text-ink-muted">
          {concept.characters
            .map((character) => `${character.name}(${character.role})`)
            .join(' · ')}
        </p>
      )}

      {!expanded && (
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="mt-3 flex items-center gap-1 self-start text-xs text-ink-muted transition-colors hover:text-ink"
        >
          <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
          자세히
        </button>
      )}

      {(open || expanded) && (
        <div className="mt-4 space-y-4 border-t border-line pt-4">
          <Prose title="기획 의도" body={concept.premise} />
          <Prose title="전체 아크" body={concept.arc} />
          <Prose title="계획된 결말" body={concept.ending} />

          {concept.characters.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold tracking-tight text-ink-dim">인물</h4>
              <div className="mt-2 space-y-2">
                {concept.characters.map((character) => (
                  <div key={character.name} className="rounded-lg border border-line p-3">
                    <p className="flex flex-wrap items-center gap-1.5 text-sm text-ink">
                      <span className="font-medium">{character.name}</span>
                      <Badge>{character.role}</Badge>
                      {character.age !== null && (
                        <span className="text-xs text-ink-muted">{character.age}세</span>
                      )}
                      {character.gender && (
                        <span className="text-xs text-ink-muted">{character.gender}</span>
                      )}
                    </p>
                    {character.personality && (
                      <p className="mt-1 text-xs leading-relaxed text-ink-dim">
                        {character.personality}
                      </p>
                    )}
                    {character.goal && (
                      <p className="mt-1 text-xs text-ink-muted">목표 — {character.goal}</p>
                    )}
                    {character.secret && (
                      <p className="mt-0.5 text-xs text-ink-muted">비밀 — {character.secret}</p>
                    )}
                    {character.relationships.length > 0 && (
                      <p className="mt-1 text-xs text-ink-muted">
                        {character.relationships.join(' · ')}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <Tags title="규칙" items={concept.rules} />
          <Tags title="장소" items={concept.locations} />
          <Tags title="세력" items={concept.factions} />

          {concept.episodes.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold tracking-tight text-ink-dim">
                회차 구상
                <span className="ml-1.5 font-normal text-ink-muted">
                  — 대략적인 방향입니다. 각 화를 쓰기 직전에 다시 상세히 기획하고,
                  그때 작가님이 확인하십니다.
                </span>
              </h4>
              <ol className="mt-2 space-y-1">
                {concept.episodes.map((episode) => (
                  <li key={episode.number} className="flex gap-2 text-xs leading-relaxed">
                    <span className="w-8 shrink-0 text-right font-mono text-ink-muted">
                      {episode.number}화
                    </span>
                    <span className="text-ink-dim">{episode.line}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}

      {action && <div className="mt-4 flex justify-end">{action}</div>}
    </section>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  )
}

function Prose({ title, body }: { title: string; body: string }) {
  if (!body.trim()) return null
  return (
    <div>
      <h4 className="text-xs font-semibold tracking-tight text-ink-dim">{title}</h4>
      <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-ink-dim">{body}</p>
    </div>
  )
}

function Tags({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <h4 className="text-xs font-semibold tracking-tight text-ink-dim">{title}</h4>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <li
            key={item}
            className="rounded-md border border-line px-2 py-1 text-xs text-ink-dim"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
