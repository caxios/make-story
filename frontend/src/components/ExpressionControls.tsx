/**
 * 이번 화의 표현 설정 — how freely this one chapter is written.
 *
 * The project's writing style says how the whole serial reads. This says how
 * *this* chapter reads, because a quiet interlude and a climax should not be
 * written at the same pitch. Everything here is an override: left alone, the
 * chapter follows the project.
 *
 * The creativity dial moves two things at once — the instruction the Writer is
 * given, and the temperature it is sampled at. One without the other produces a
 * model told to be daring that plays it safe.
 */

import { RotateCcw, Wand2 } from 'lucide-react'

import { Badge, SelectField, Slider, TextArea } from '@/components/ui'
import type { ProseDensity } from '@/types/storyweaver'

export interface Expression {
  creativity: number | null
  prose_density: ProseDensity | null
  tone_notes: string
}

/** The project's own setting, used when this chapter overrides nothing. */
export const PROJECT_DEFAULT_CREATIVITY = 0.5

const LEVELS: { upTo: number; name: string; blurb: string }[] = [
  {
    upTo: 0.2,
    name: '절제',
    blurb: '담백하고 사실적인 문장. 비유와 수식을 거의 쓰지 않습니다.',
  },
  {
    upTo: 0.4,
    name: '차분',
    blurb: '필요한 곳에만 묘사를 붙입니다. 비유는 사실에 가깝게.',
  },
  {
    upTo: 0.6,
    name: '균형',
    blurb: '보통의 소설 문장. 감각 묘사와 비유를 제자리에 씁니다.',
  },
  {
    upTo: 0.8,
    name: '풍부',
    blurb: '목소리와 리듬, 이미지를 적극적으로 씁니다. 장면의 질감을 자유롭게 만듭니다.',
  },
  {
    upTo: 1.01,
    name: '자유분방',
    blurb: '낯선 이미지와 문장 구조까지 시도합니다. 사건은 그대로, 표현은 과감하게.',
  },
]

function levelFor(value: number) {
  return LEVELS.find((level) => value <= level.upTo) ?? LEVELS[LEVELS.length - 1]!
}

const DENSITIES: { value: string; label: string }[] = [
  { value: '', label: '— 프로젝트 설정을 따름 —' },
  { value: 'sparse', label: '희박 (sparse) — 짧은 문장, 여백 많이' },
  { value: 'moderate', label: '보통 (moderate) — 필요한 만큼의 묘사' },
  { value: 'lush', label: '농밀 (lush) — 겹겹의 이미지, 긴 호흡' },
]

export function ExpressionControls({
  value,
  onChange,
}: {
  value: Expression
  onChange: (next: Expression) => void
}) {
  const creativity = value.creativity ?? PROJECT_DEFAULT_CREATIVITY
  const level = levelFor(creativity)
  const overridden =
    value.creativity !== null || value.prose_density !== null || value.tone_notes.trim() !== ''

  return (
    <section className="rounded-xl border border-line bg-surface px-4 py-3.5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-xs font-semibold tracking-wide text-ink uppercase">
          <Wand2 className="size-3.5 text-ink-muted" aria-hidden />
          이번 화의 표현
        </h3>
        {overridden ? (
          <button
            type="button"
            onClick={() =>
              onChange({ creativity: null, prose_density: null, tone_notes: '' })
            }
            className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            <RotateCcw className="size-3" aria-hidden />
            프로젝트 기본값으로
          </button>
        ) : (
          <Badge>프로젝트 설정을 따르는 중</Badge>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <Slider
            label={`창의력 · 문장 자유도 — ${level.name}`}
            min={0}
            max={1}
            step={0.05}
            value={creativity}
            onChange={(next) => onChange({ ...value, creativity: next })}
            format={(v) => v.toFixed(2)}
          />
          <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{level.blurb}</p>
        </div>

        <SelectField
          label="표현 밀도"
          value={value.prose_density ?? ''}
          onChange={(event) =>
            onChange({
              ...value,
              prose_density: (event.target.value || null) as ProseDensity | null,
            })
          }
          options={DENSITIES}
        />

        <TextArea
          label="이번 화의 분위기 / 뉘앙스"
          rows={3}
          value={value.tone_notes}
          onChange={(event) => onChange({ ...value, tone_notes: event.target.value })}
          placeholder="예: 쓸쓸하고 건조하게. 농담은 넣지 말 것. 마지막 장면만 온기를 남길 것."
          hint="작가님이 쓰신 그대로 작가 에이전트의 프롬프트에 들어갑니다."
        />
      </div>
    </section>
  )
}
