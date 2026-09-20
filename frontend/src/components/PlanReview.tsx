/**
 * 기획서 — the episode's layout, before a word of it is written.
 *
 * Drafting this costs one model call; writing the chapter costs dozens. So it
 * is worth reading properly: every scene here becomes minutes of simulation and
 * a slice of the 회차's length, and a scene that is wrong is cheapest to fix now.
 *
 * Everything is editable, because the point is not to show the author what the
 * model decided — it is to let the author decide.
 */

import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  MapPin,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import * as api from '@/api/client'
import { ExpressionControls, type Expression } from '@/components/ExpressionControls'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  Drawer,
  IconButton,
  SelectField,
  TextArea,
  TextField,
} from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import type {
  CharacterProfile,
  Episode,
  EpisodePlan,
  Location,
  Scene,
} from '@/types/storyweaver'

/** One scene while the author is working on it. */
interface Draft {
  title: string
  objective: string
  participating_character_ids: string[]
  location_id: string | null
  beats: string[]
}

function toDraft(scene: Scene): Draft {
  return {
    title: scene.title,
    objective: scene.objective,
    participating_character_ids: [...scene.participating_character_ids],
    location_id: scene.location_id,
    beats: scene.beats.map((beat) => beat.description),
  }
}

const BLANK: Draft = {
  title: '',
  objective: '',
  participating_character_ids: [],
  location_id: null,
  beats: [],
}

function expressionOf(episode: Episode | null): Expression {
  return {
    creativity: episode?.creativity ?? null,
    prose_density: episode?.prose_density ?? null,
    tone_notes: episode?.tone_notes ?? '',
  }
}

export function PlanReview({
  open,
  episode,
  episodeNumber,
  episodeTitle,
  plan,
  characters,
  locations,
  onClose,
  onChanged,
  onApprove,
}: {
  open: boolean
  episode: Episode | null
  episodeNumber: number
  episodeTitle: string
  plan: EpisodePlan | null
  characters: CharacterProfile[]
  locations: Location[]
  onClose: () => void
  onChanged: () => Promise<void>
  /** Approve and start writing. The drawer closes and generation takes over. */
  onApprove: () => void
}) {
  const { success, fromError } = useToast()
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [expression, setExpression] = useState<Expression>(expressionOf(episode))
  const [saving, setSaving] = useState(false)
  const [redrafting, setRedrafting] = useState(false)

  useEffect(() => {
    if (plan) setDrafts(plan.scenes.map(toDraft))
  }, [plan])

  useEffect(() => setExpression(expressionOf(episode)), [episode])

  if (!plan) return null

  const nameOf = (id: string) => characters.find((c) => c.id === id)?.name ?? id
  const unit = plan.unit === 'characters' ? '자' : '단어'
  const perScene = plan.target_per_scene
  const projected = perScene * drafts.length
  const short = projected < plan.standard_low
  const long = projected > plan.standard_high

  const expressionDirty =
    JSON.stringify(expression) !== JSON.stringify(expressionOf(episode))
  const dirty =
    JSON.stringify(drafts) !== JSON.stringify(plan.scenes.map(toDraft)) || expressionDirty
  const valid =
    drafts.length > 0 &&
    drafts.every(
      (draft) =>
        draft.title.trim() &&
        draft.objective.trim() &&
        draft.participating_character_ids.length > 0,
    )

  const patch = (index: number, changes: Partial<Draft>) =>
    setDrafts((previous) =>
      previous.map((draft, i) => (i === index ? { ...draft, ...changes } : draft)),
    )

  const move = (index: number, offset: number) =>
    setDrafts((previous) => {
      const next = [...previous]
      const target = index + offset
      if (target < 0 || target >= next.length) return previous
      ;[next[index], next[target]] = [next[target]!, next[index]!]
      return next
    })

  const save = async () => {
    setSaving(true)
    try {
      if (expressionDirty) {
        // `null` cannot mean "unset" in a partial update, so clearing every
        // override is its own request rather than three nulls.
        const cleared =
          expression.creativity === null &&
          expression.prose_density === null &&
          expression.tone_notes.trim() === ''
        await api.updateEpisode(
          episodeNumber,
          cleared
            ? { reset_expression: true }
            : {
                ...(expression.creativity !== null
                  ? { creativity: expression.creativity }
                  : {}),
                ...(expression.prose_density !== null
                  ? { prose_density: expression.prose_density }
                  : {}),
                tone_notes: expression.tone_notes,
              },
        )
      }
      await api.savePlan(
        episodeNumber,
        drafts.map((draft) => ({
          title: draft.title.trim(),
          objective: draft.objective.trim(),
          participating_character_ids: draft.participating_character_ids,
          location_id: draft.location_id,
          beats: draft.beats
            .filter((beat) => beat.trim())
            .map((beat) => ({ description: beat.trim() })),
        })),
      )
      await onChanged()
      success('기획서를 저장했습니다')
      return true
    } catch (cause) {
      fromError(cause, '기획서를 저장하지 못했습니다.')
      return false
    } finally {
      setSaving(false)
    }
  }

  const redraft = async () => {
    setRedrafting(true)
    try {
      await api.draftPlan(episodeNumber)
      await onChanged()
      success('기획서를 다시 짰습니다')
    } catch (cause) {
      fromError(cause, '기획서를 다시 짜지 못했습니다.')
    } finally {
      setRedrafting(false)
    }
  }

  const approve = async () => {
    // Whatever is on screen is what gets written, so save it first.
    if (dirty && !(await save())) return
    onApprove()
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`기획서 · 제${episodeNumber}화`}
      description={episodeTitle || '집필 전에 구성을 확인하세요'}
      footer={
        <>
          <Button icon={RefreshCw} onClick={() => void redraft()} loading={redrafting}>
            다시 짜기
          </Button>
          <Button onClick={() => void save()} loading={saving} disabled={!dirty || !valid}>
            저장만
          </Button>
          <Button
            variant="primary"
            icon={Sparkles}
            onClick={() => void approve()}
            disabled={!valid || redrafting}
          >
            승인하고 집필 시작
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {/* --- How freely this chapter is written --- */}
        <ExpressionControls value={expression} onChange={setExpression} />

        {/* --- The length this plan is budgeted for --- */}
        <div
          className={cn(
            'flex items-start gap-3 rounded-xl border px-4 py-3',
            short || long ? 'border-warn/30 bg-warn/8' : 'border-line bg-surface',
          )}
        >
          {short || long ? (
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn-bright" aria-hidden />
          ) : (
            <Check className="mt-0.5 size-4 shrink-0 text-good-bright" aria-hidden />
          )}
          <div className="text-xs leading-relaxed text-ink-dim">
            <p>
              장면 {drafts.length}개 × {formatCount(perScene)}
              {unit} ≈{' '}
              <span className="font-medium text-ink">
                {formatCount(projected)}
                {unit}
              </span>
            </p>
            <p className="mt-1 text-ink-muted">
              {short
                ? `한국 웹소설 1회차 기준(${formatCount(plan.standard_low)}~${formatCount(
                    plan.standard_high,
                  )}자)보다 짧습니다. 장면을 추가하거나 설정에서 장면당 분량을 올리세요.`
                : long
                  ? `기준(${formatCount(plan.standard_low)}~${formatCount(
                      plan.standard_high,
                    )}자)보다 깁니다. 장면을 합치거나 장면당 분량을 줄이세요.`
                  : `한국 웹소설 1회차 기준(${formatCount(
                      plan.standard_low,
                    )}~${formatCount(plan.standard_high)}자) 안에 들어옵니다.`}
            </p>
          </div>
        </div>

        {/* --- The scenes --- */}
        {drafts.map((draft, index) => (
          <section key={index} className="rounded-xl border border-line bg-surface px-4 py-3.5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <Badge tone="accent">장면 {index + 1}</Badge>
              <div className="flex items-center gap-1">
                <IconButton
                  icon={ArrowUp}
                  title="위로"
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                />
                <IconButton
                  icon={ArrowDown}
                  title="아래로"
                  disabled={index === drafts.length - 1}
                  onClick={() => move(index, 1)}
                />
                <IconButton
                  icon={Trash2}
                  title="이 장면 삭제"
                  onClick={() => setDrafts(drafts.filter((_, i) => i !== index))}
                />
              </div>
            </div>

            <div className="space-y-3">
              <TextField
                label="장면 제목"
                value={draft.title}
                onChange={(event) => patch(index, { title: event.target.value })}
              />
              <TextArea
                label="이 장면이 해내야 하는 일"
                rows={2}
                value={draft.objective}
                onChange={(event) => patch(index, { objective: event.target.value })}
                hint="시뮬레이션은 이 목표가 달성되면 장면을 끝냅니다."
              />

              <div>
                <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-dim">
                  <Users className="size-3.5" aria-hidden />
                  등장인물
                  <span className="font-normal text-ink-muted">
                    — 먼저 고른 인물이 장면을 엽니다
                  </span>
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {characters.map((character) => {
                    const picked = draft.participating_character_ids.includes(character.id)
                    return (
                      <button
                        key={character.id}
                        type="button"
                        onClick={() =>
                          patch(index, {
                            participating_character_ids: picked
                              ? draft.participating_character_ids.filter(
                                  (id) => id !== character.id,
                                )
                              : [...draft.participating_character_ids, character.id],
                          })
                        }
                        className={cn(
                          'rounded-lg border px-2.5 py-1 text-xs transition-colors',
                          picked
                            ? 'border-accent/40 bg-accent/12 text-ink'
                            : 'border-line bg-canvas text-ink-muted hover:border-line-strong hover:text-ink-dim',
                        )}
                      >
                        {character.name}
                      </button>
                    )
                  })}
                </div>
                {draft.participating_character_ids.length === 0 && (
                  <p className="mt-1.5 text-xs text-warn-bright">
                    등장인물이 최소 한 명은 있어야 합니다.
                  </p>
                )}
                {draft.participating_character_ids.length > 0 && (
                  <p className="mt-1.5 text-xs text-ink-muted">
                    순서: {draft.participating_character_ids.map(nameOf).join(' → ')}
                  </p>
                )}
              </div>

              <SelectField
                label="장소"
                value={draft.location_id ?? ''}
                onChange={(event) => patch(index, { location_id: event.target.value || null })}
                options={[
                  { value: '', label: '— 지정 안 함 —' },
                  ...locations.map((location) => ({
                    value: location.id,
                    label: location.name,
                  })),
                ]}
              />

              <div>
                <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-dim">
                  <MapPin className="size-3.5" aria-hidden />
                  비트 — 이 장면에서 반드시 일어나야 하는 일
                </p>
                <div className="space-y-1.5">
                  {draft.beats.map((beat, beatIndex) => (
                    <div key={beatIndex} className="flex items-center gap-2">
                      <input
                        value={beat}
                        onChange={(event) =>
                          patch(index, {
                            beats: draft.beats.map((b, i) =>
                              i === beatIndex ? event.target.value : b,
                            ),
                          })
                        }
                        className="sw-field flex-1 text-sm"
                      />
                      <IconButton
                        icon={Trash2}
                        title="비트 삭제"
                        onClick={() =>
                          patch(index, {
                            beats: draft.beats.filter((_, i) => i !== beatIndex),
                          })
                        }
                      />
                    </div>
                  ))}
                  <Button
                    size="sm"
                    icon={Plus}
                    onClick={() => patch(index, { beats: [...draft.beats, ''] })}
                  >
                    비트 추가
                  </Button>
                </div>
              </div>
            </div>
          </section>
        ))}

        <Button icon={Plus} onClick={() => setDrafts([...drafts, { ...BLANK }])}>
          장면 추가
        </Button>
      </div>
    </Drawer>
  )
}
