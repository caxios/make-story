/**
 * ⚙️ Settings — how the prose is written, and what it has cost.
 *
 * Every control here reaches the Writer's prompt. Nothing on this page is
 * decorative: if a setting could not change the output, it would not be here.
 */

import { AlertTriangle, Coins, Gauge, KeyRound, Save, Type } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  SelectField,
  Slider,
  TextArea,
  TextField,
} from '@/components/ui'
import { formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type {
  Perspective,
  ProseDensity,
  Telemetry,
  Tense,
  WritingStyle,
} from '@/types/storyweaver'

const PERSPECTIVES: { value: Perspective; label: string }[] = [
  { value: 'third_person_limited', label: '3인칭 주인공 시점 (Third person limited) — 특정 인물의 내면 중심' },
  { value: 'third_person_omniscient', label: '3인칭 전지적 작가 시점 (Third person omniscient) — 자유로운 시점 이동' },
  { value: 'first_person', label: '1인칭 주인공 시점 (First person) — 주인공 독백 및 직접 서술' },
]

const TENSES: { value: Tense; label: string }[] = [
  { value: 'past', label: '과거형 (Past) — 일반적인 서사 소설의 표준' },
  { value: 'present', label: '현재형 (Present) — 긴박감과 몰입감 강조' },
]

const DENSITIES: { value: ProseDensity; label: string }[] = [
  { value: 'sparse', label: '간결함 (Sparse) — 짧은 문장과 여백, 빠른 템포' },
  { value: 'moderate', label: '보통 (Moderate) — 상황에 맞는 균형 잡힌 묘사' },
  { value: 'lush', label: '풍부함 (Lush) — 다채로운 감각적 묘사와 장문' },
]

export function Settings() {
  return (
    <>
      <PageHeader
        title="설정"
        description="문체 스타일 및 분량 제어, 모델 API 및 누적 사용량/비용을 확인합니다."
      />
      <div className="space-y-5">
        <StylePanel />
        <ChroniclePanel />
        <TelemetryPanel />
      </div>
    </>
  )
}

// ==========================================================================
// The chronicle's review gate
// ==========================================================================

function ChroniclePanel() {
  const { project, refresh } = useProject()
  const { success, fromError } = useToast()
  const [saving, setSaving] = useState(false)

  const review = project?.review_chronicle ?? true

  const toggle = async (next: boolean) => {
    if (!project) return
    setSaving(true)
    try {
      await api.saveProject({ ...project, review_chronicle: next })
      await refresh()
      success(
        next
          ? '회차를 쓰고 나면 기록을 먼저 확인하게 됩니다.'
          : '기록이 확인 없이 바로 위키에 반영됩니다.',
      )
    } catch (cause) {
      fromError(cause, '설정을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      title="위키 기록 확인"
      description="회차를 쓰고 나면 AI가 인물과 세계관의 변화를 위키에 기록합니다. 그 기록을 반영하기 전에 확인할지 정합니다."
    >
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm leading-relaxed text-ink-dim">
          {review
            ? '회차가 끝나면 기록 목록이 뜹니다. 승인한 것만 위키에 남고, 다음 회차를 쓸 때 AI가 보게 됩니다.'
            : '기록이 곧바로 반영됩니다. 빠르지만, AI가 잘못 기록한 변화도 그대로 다음 회차에 쓰입니다.'}
          <span className="mt-2 block text-xs text-ink-muted">
            연대기는 작가가 처음 쓴 설정을 이깁니다. 그래서 확인을 끄시면, 지어낸 변화
            하나가 그 뒤의 모든 회차에 사실로 전달됩니다. 위키에서 언제든 취소할 수는
            있습니다.
          </span>
        </p>
        <Button
          variant={review ? 'secondary' : 'primary'}
          loading={saving}
          disabled={saving || !project}
          onClick={() => void toggle(!review)}
        >
          {review ? '확인 끄기' : '확인 켜기'}
        </Button>
      </div>
    </Panel>
  )
}

// ==========================================================================
// Writing style
// ==========================================================================

function StylePanel() {
  const { project, refresh } = useProject()
  const { success, fromError } = useToast()

  const [draft, setDraft] = useState<WritingStyle | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (project) setDraft(project.style)
  }, [project])

  const dirty = useMemo(
    () =>
      draft !== null &&
      project !== null &&
      JSON.stringify(draft) !== JSON.stringify(project.style),
    [draft, project],
  )

  if (!draft || !project) return <div className="sw-panel h-96 animate-pulse-soft" />

  const patch = (changes: Partial<WritingStyle>) =>
    setDraft((previous) => (previous ? { ...previous, ...changes } : previous))

  const save = async () => {
    setSaving(true)
    try {
      await api.saveStyle(draft)
      await refresh()
      success('문체 설정이 저장되었습니다')
    } catch (cause) {
      fromError(cause, '문체 설정을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  // The unit this target is in follows the language: Korean is measured in
  // characters, English in words. `WritingStyle.describe_target_length` on the
  // backend makes the same decision, and this label has to agree with it.
  const korean = draft.language.toLowerCase().startsWith('ko')
  const perScene = draft.target_word_count_per_scene
  const episodeLow = perScene * 3
  const episodeHigh = perScene * 4

  return (
    <Panel
      title="문체 및 서술 스타일"
      description="작품 전체에 걸쳐 적용됩니다. 작가 AI 프롬프트에 직접 반영됩니다."
      actions={
        <>
          {dirty && <Badge tone="warn">저장되지 않음</Badge>}
          <Button
            variant="primary"
            icon={Save}
            onClick={() => void save()}
            loading={saving}
            disabled={!dirty}
          >
            문체 저장
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="서술 시점"
            value={draft.perspective}
            onChange={(event) => patch({ perspective: event.target.value as Perspective })}
            options={PERSPECTIVES}
          />
          <SelectField
            label="문장 시제"
            value={draft.tense}
            onChange={(event) => patch({ tense: event.target.value as Tense })}
            options={TENSES}
          />
          <SelectField
            label="시점 인물 (POV)"
            value={draft.pov_character_id ?? ''}
            onChange={(event) => patch({ pov_character_id: event.target.value || null })}
            options={[
              { value: '', label: '— 장면을 여는 인물 기준 —' },
              ...project.characters.map((character) => ({
                value: character.id,
                label: character.name,
              })),
            ]}
            hint="전지적 작가 시점에서는 무시됩니다. 해당 인물이 장면에 등장하지 않으면 장면을 여는 인물의 시점으로 대체됩니다."
          />
          <SelectField
            label="문장 밀도"
            value={draft.prose_density}
            onChange={(event) => patch({ prose_density: event.target.value as ProseDensity })}
            options={DENSITIES}
            hint="전개 속도(호흡)는 에피소드 큐에서 회차별로 지정할 수 있으며, 이것은 작품 전체의 문체 질감입니다."
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <Slider
            label="대화 vs. 서술 비율"
            min={0.2}
            max={0.8}
            step={0.05}
            value={draft.dialogue_ratio}
            onChange={(dialogue_ratio) => patch({ dialogue_ratio })}
            format={(value) => `${Math.round(value * 100)}% 대화`}
          />
          <div className="space-y-1.5">
            <TextField
              label={korean ? '장면당 목표 글자 수 (공백 포함)' : '장면당 목표 단어 수'}
              type="number"
              min={100}
              max={6000}
              step={100}
              value={perScene}
              onChange={(event) =>
                patch({
                  target_word_count_per_scene: Math.max(1, Number(event.target.value) || 1400),
                })
              }
            />
          </div>
        </div>

        {/* The one number an author most often wants and cannot see. */}
        <div className="flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3">
          <Gauge className="mt-0.5 size-4 shrink-0 text-ink-muted" aria-hidden />
          <div className="text-xs leading-relaxed text-ink-dim">
            <p>
              디렉터 AI는 1화당 3~4개의 장면을 기획하므로, 1화 전체 분량은 약{' '}
              <span className="font-medium text-ink">
                {formatCount(episodeLow)}–{formatCount(episodeHigh)}
              </span>{' '}
              {korean ? '자 (공백 포함)' : '단어'} 내외가 됩니다.
            </p>
            {korean && (
              <p className="mt-1.5 text-ink-muted">
                한국 웹소설 1화 표준 규격은 4,500~5,500자이며, 기본값인 장면당 1,400자는 이를 정확히
                맞추기 위해 설정되었습니다. AI는 단어가 아닌 글자 수(Characters) 단위로 지시를 받아
                분량을 정밀하게 조절합니다.
              </p>
            )}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="출력 언어"
            value={draft.language}
            onChange={(event) => patch({ language: event.target.value })}
            hint="프롬프트에 직접 전달됩니다: “ko”, “Korean”, “한국어”, “English” 등을 입력할 수 있습니다."
          />
        </div>

        <TextArea
          label="작가 스타일 특이사항 (지침)"
          rows={4}
          value={draft.author_style_notes}
          onChange={(event) => patch({ author_style_notes: event.target.value })}
          placeholder="간결한 단문 위주. 대화 지문에서 과도한 부사 생략. 웹소설 특유의 빠른 템포와 사이다 전개…"
          hint="자유 형식 텍스트로, 작가 AI의 작성 가이드라인 끝에 직접 추가됩니다."
        />
      </div>
    </Panel>
  )
}

// ==========================================================================
// Model and telemetry
// ==========================================================================

function TelemetryPanel() {
  const { fromError } = useToast()
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null)

  useEffect(() => {
    void api
      .getTelemetry()
      .then(setTelemetry)
      .catch((cause) => fromError(cause, '사용량 로그를 불러오지 못했습니다.'))
  }, [fromError])

  if (!telemetry) return <div className="sw-panel h-56 animate-pulse-soft" />

  const stages = Object.entries(telemetry.by_stage)
  const busiest = Math.max(1, ...stages.map(([, tokens]) => tokens))

  return (
    <Panel
      title="모델 및 사용 비용"
      description="모든 LLM 호출이 측정됩니다. 이 프로젝트에서 생성된 모든 회차의 누적 사용량입니다."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">모델</p>
          <p className="mt-1.5 font-mono text-sm text-ink">{telemetry.model}</p>
          <p className="mt-2 text-xs text-ink-muted">
            온도(temperature) {telemetry.temperature} · 1회 호출당 최대{' '}
            {formatCount(telemetry.max_output_tokens)} 출력 토큰
          </p>
          {!telemetry.api_key_configured && (
            <p className="mt-2.5 flex items-start gap-1.5 text-xs leading-relaxed text-warn-bright">
              <KeyRound className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일에 입력 후 백엔드를 재시작해야
              집필 생성이 정상 동작합니다.
            </p>
          )}
        </div>

        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">누적 비용</p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight text-ink tabular-nums">
              ${telemetry.cost.toFixed(2)}
            </span>
            <span className="text-xs text-ink-muted">
              {formatCount(telemetry.total_tokens)} 토큰
            </span>
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            {telemetry.runs}회 집필 · {telemetry.calls}회 호출 · 입력{' '}
            {formatCount(telemetry.input_tokens)} / 출력 {formatCount(telemetry.output_tokens)}
          </p>
          <p className="mt-2 flex items-start gap-1.5 text-[0.68rem] leading-relaxed text-ink-muted">
            <Coins className="mt-0.5 size-3 shrink-0" aria-hidden />백만 토큰당 입력 ${
              telemetry.input_cost_per_mtok
            }, 출력 ${telemetry.output_cost_per_mtok} — 실제 청구액이 아닌 모델 단가 기준 추정치입니다.
          </p>
        </div>
      </div>

      {telemetry.estimated && (
        <p className="mt-4 flex items-start gap-2 rounded-lg border border-warn/25 bg-warn/8 px-3 py-2 text-xs leading-relaxed text-warn-bright">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          일부 호출에서 사용량 메타데이터가 누락되어 텍스트 길이로부터 토큰 수를 추정했습니다.
        </p>
      )}

      {stages.length > 0 && (
        <div className="mt-5">
          <p className="mb-2.5 flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            <Type className="size-3.5" aria-hidden />
            단계별 토큰 사용량
          </p>
          <div className="space-y-2">
            {stages.map(([stage, tokens]) => (
              <div key={stage} className="flex items-center gap-3">
                <span className="w-24 shrink-0 truncate text-xs text-ink-dim">{stage}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                  <span
                    className="block h-full rounded-full bg-accent/70"
                    style={{ width: `${(tokens / busiest) * 100}%` }}
                  />
                </span>
                <span className="w-20 shrink-0 text-right font-mono text-xs text-ink-muted tabular-nums">
                  {formatCount(tokens)}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-muted">
            등장인물 간 대화 시뮬레이션 에이전트 호출이 통상 토큰 사용량의 대부분을 차지합니다.
          </p>
        </div>
      )}

      {telemetry.runs === 0 && (
        <p className="mt-4 text-xs leading-relaxed text-ink-muted">
          아직 생성된 회차가 없어 누적 사용량이 없습니다. 등장인물 3명이 나오는 4장면 1회차 집필 시
          통상 약 15만~25만 토큰이 소모됩니다.
        </p>
      )}

      {telemetry.recent.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            최근 집필 내역
          </p>
          <div className="space-y-1">
            {telemetry.recent.map((run, index) => (
              <div
                key={`${run.at}-${index}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-xs"
              >
                <span className="text-ink-dim">제{run.episode_number}화</span>
                <span className="flex items-center gap-3 font-mono text-ink-muted tabular-nums">
                  <span>{formatCount(run.input_tokens + run.output_tokens)} 토큰</span>
                  <span>${run.cost.toFixed(3)}</span>
                  <span>{Math.round(run.seconds)}초</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
