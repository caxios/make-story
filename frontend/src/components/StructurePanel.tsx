/**
 * 에피소드 큐의 '작품 구조' — 기획을 마친 뒤에도 분량을 정하고 바꾸는 자리.
 *
 * 여기서 정한 구조는 다음 회차 개요(AI가 개요 쓰기), 스토리 플래너, 디렉터
 * 기획서가 모두 읽는다. 그래서 400화로 정해 두면 13화의 개요는 "400화 중
 * 13화, 1부 도입부"로 쓰인다.
 *
 * 다시 짜기는 두 단계다. 먼저 새 구조와 아직 안 쓴 회차의 새 개요를 받아
 * 보고(저장 안 함), 작가가 고른 것만 적용한다. 이미 쓴 회차는 건드리지 않는다.
 */

import { ChevronDown, LayoutList, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import * as api from '@/api/client'
import { useSettingsRegistration } from '@/lib/useSettingsRegistration'
import { LengthFields } from '@/components/LengthFields'
import { StructureOverview } from '@/components/StructureOverview'
import { useToast } from '@/components/ToastContext'
import { Button, IconButton, Modal, Panel, TextArea, TextField } from '@/components/ui'
import { cn } from '@/lib/cn'
import type {
  PlannedRelationship,
  PlannedThread,
  StoryPart,
  StoryStructure,
  StructureDraft,
  StructureView,
} from '@/types/storyweaver'

export function StructurePanel({
  onChanged,
  watch,
}: {
  onChanged: () => Promise<void>
  /** 이 값이 바뀌면(회차 추가·완료) 다음 회차 위치를 다시 읽는다. */
  watch: string
}) {
  const { fromError } = useToast()
  const [view, setView] = useState<StructureView | null>(null)
  const [open, setOpen] = useState(true)
  const [redrawing, setRedrawing] = useState(false)
  const [editing, setEditing] = useState(false)

  const load = useCallback(async () => {
    try {
      setView(await api.getStructure())
    } catch (cause) {
      fromError(cause, '작품 구조를 불러오지 못했습니다.')
    }
  }, [fromError])

  useEffect(() => {
    void load()
  }, [load, watch])

  const changed = async (next?: StructureView) => {
    if (next) setView(next)
    else await load()
    await onChanged()
  }

  if (!view) return null
  const structure = view.structure

  return (
    <Panel
      className="mb-5"
      title={
        structure
          ? `작품 구조 — 전체 ${structure.target_episodes}화 · ${structure.parts.length}부 · 떡밥 ${structure.threads.length}개`
          : '작품 구조 — 분량이 정해지지 않았습니다'
      }
      description={
        structure
          ? `다음에 쓸 ${view.next_episode}화의 개요는 이 구조 안에서의 위치를 알고 쓰입니다.`
          : '전체 몇 화짜리 작품인지 정하면, 부 구성과 떡밥 배치를 짜고 모든 회차 개요가 그 호흡에 맞춰 쓰입니다. 지금은 회차마다 결말을 향해 서두를 수 있습니다.'
      }
      actions={
        <>
          {structure && (
            <>
              <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(true)}>
                직접 고치기
              </Button>
              <IconButton
                icon={ChevronDown}
                title={open ? '접기' : '펼치기'}
                className={cn('transition-transform', open && 'rotate-180')}
                onClick={() => setOpen((value) => !value)}
              />
            </>
          )}
          <Button
            size="sm"
            variant={structure ? 'secondary' : 'primary'}
            icon={structure ? RotateCcw : LayoutList}
            onClick={() => setRedrawing(true)}
          >
            {structure ? '분량 바꾸기·다시 짜기' : '분량 정하고 구조 짜기'}
          </Button>
        </>
      }
    >
      {structure && open && <StructureOverview structure={structure} current={view.next_episode} />}

      <RedrawModal
        open={redrawing}
        view={view}
        onClose={() => setRedrawing(false)}
        onApplied={async (next) => {
          setRedrawing(false)
          await changed(next)
        }}
      />
      {structure && (
        <EditModal
          open={editing}
          structure={structure}
          onClose={() => setEditing(false)}
          onSaved={async (next) => {
            setEditing(false)
            await changed(next)
          }}
        />
      )}
    </Panel>
  )
}

// ==========================================================================
// 분량 바꾸기 · 다시 짜기
// ==========================================================================

function RedrawModal({
  open,
  view,
  onClose,
  onApplied,
}: {
  open: boolean
  view: StructureView
  onClose: () => void
  onApplied: (next: StructureView) => Promise<void>
}) {
  const { success, fromError } = useToast()
  const { registerFrom } = useSettingsRegistration()
  const [target, setTarget] = useState(view.structure?.target_episodes ?? 200)
  const [instruction, setInstruction] = useState('')
  const [rewrite, setRewrite] = useState(true)
  const [draft, setDraft] = useState<StructureDraft | null>(null)
  const [kept, setKept] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<'' | 'draft' | 'apply'>('')

  const close = () => {
    setDraft(null)
    onClose()
  }

  // 열 때마다 지금 저장된 분량에서 시작한다.
  useEffect(() => {
    if (open) setTarget(view.structure?.target_episodes ?? 200)
  }, [open, view.structure?.target_episodes])

  const ask = async () => {
    setBusy('draft')
    try {
      const next = await api.draftStructure(target, instruction.trim(), rewrite)
      setDraft(next)
      setKept(Object.fromEntries(next.episodes.map((e) => [e.episode_number, e.after])))
    } catch (cause) {
      fromError(cause, '구조를 짜지 못했습니다.')
    } finally {
      setBusy('')
    }
  }

  const apply = async () => {
    if (!draft) return
    setBusy('apply')
    try {
      const episodes = Object.entries(kept)
        .filter(([, text]) => text.trim())
        .map(([number, text]) => ({
          episode_number: Number(number),
          author_storyline: text.trim(),
        }))
      const next = await api.applyStructure(draft.structure, episodes)
      success(
        episodes.length > 0
          ? `전체 ${draft.structure.target_episodes}화 구조를 적용하고 ${episodes.length}개 회차 개요를 바꿨습니다.`
          : `전체 ${draft.structure.target_episodes}화 구조를 적용했습니다.`,
      )
      setDraft(null)
      await onApplied(next)
      // 다시 쓴 개요에 새로 나온 인물·설정을 등록한다.
      void registerFrom(episodes.map((e) => e.episode_number))
    } catch (cause) {
      fromError(cause, '적용하지 못했습니다.')
    } finally {
      setBusy('')
    }
  }

  const toggle = (number: number, after: string) =>
    setKept((current) => {
      const next = { ...current }
      if (number in next) delete next[number]
      else next[number] = after
      return next
    })

  return (
    <Modal
      open={open}
      onClose={close}
      wide
      title={draft ? '새 구조 확인' : '분량 정하고 구조 짜기'}
      description={
        draft
          ? '아직 아무것도 바뀌지 않았습니다. 새 개요는 고치거나 빼실 수 있습니다. 적용해야 반영됩니다.'
          : `이미 쓴 ${view.written_through}화까지는 그대로 두고, 그 뒤를 새 분량에 맞춰 배치합니다.`
      }
      footer={
        draft ? (
          <>
            <Button onClick={() => setDraft(null)} disabled={Boolean(busy)}>
              다시 설정
            </Button>
            <Button variant="primary" loading={busy === 'apply'} onClick={() => void apply()}>
              적용
            </Button>
          </>
        ) : (
          <>
            <Button onClick={close}>취소</Button>
            <Button
              variant="primary"
              icon={LayoutList}
              loading={busy === 'draft'}
              disabled={target <= view.written_through}
              onClick={() => void ask()}
            >
              구조 짜기
            </Button>
          </>
        )
      }
    >
      {!draft ? (
        <div className="space-y-4">
          <LengthFields target={target} onTargetChange={setTarget} disabled={busy === 'draft'} />
          {target <= view.written_through && (
            <p className="text-xs text-bad-bright">
              이미 {view.written_through}화까지 썼습니다. 그보다 큰 분량을 정해 주세요.
            </p>
          )}
          <TextArea
            label="원하는 구성 (선택)"
            rows={3}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="예: 1부는 가족 이야기로 느긋하게 60화쯤 / 헌터 협회 떡밥은 2부 끝에서 회수 / 비워 두면 AI가 정합니다"
          />
          <label className="flex cursor-pointer items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-accent"
              checked={rewrite}
              onChange={(event) => setRewrite(event.target.checked)}
            />
            <span>
              아직 안 쓴 회차의 개요도 새 분량에 맞춰 다시 쓰기
              <span className="block text-xs text-ink-muted">
                큐에 있는데 아직 본문을 쓰지 않은 회차만 대상입니다. 적용 전에 하나씩 확인하실 수
                있습니다.
              </span>
            </span>
          </label>
          <p className="text-xs text-ink-muted">
            모델을 {rewrite ? '최대 두 번' : '한 번'} 호출합니다.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          <StructureOverview structure={draft.structure} current={view.next_episode} />
          {draft.episodes.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-ink">
                회차 개요 — 기존 → 새 개요 ({Object.keys(kept).length}/{draft.episodes.length}개
                적용)
              </p>
              <ul className="space-y-3">
                {draft.episodes.map((episode) => {
                  const on = episode.episode_number in kept
                  return (
                    <li
                      key={episode.episode_number}
                      className={cn('rounded-lg border border-line p-3', !on && 'opacity-50')}
                    >
                      <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-ink">
                        <input
                          type="checkbox"
                          className="size-4 accent-accent"
                          checked={on}
                          onChange={() => toggle(episode.episode_number, episode.after)}
                        />
                        {episode.episode_number}화
                      </label>
                      <p className="mt-1.5 text-xs leading-relaxed text-ink-muted line-through">
                        {episode.before}
                      </p>
                      {on && (
                        <textarea
                          className="sw-field mt-2 w-full text-sm"
                          rows={2}
                          value={kept[episode.episode_number]}
                          onChange={(event) =>
                            setKept((current) => ({
                              ...current,
                              [episode.episode_number]: event.target.value,
                            }))
                          }
                        />
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

// ==========================================================================
// 직접 고치기
// ==========================================================================

function EditModal({
  open,
  structure,
  onClose,
  onSaved,
}: {
  open: boolean
  structure: StoryStructure
  onClose: () => void
  onSaved: (next: StructureView) => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [target, setTarget] = useState(structure.target_episodes)
  const [parts, setParts] = useState<StoryPart[]>(structure.parts)
  const [threads, setThreads] = useState<PlannedThread[]>(structure.threads)
  const [relationships, setRelationships] = useState<RelationshipDraft[]>(
    toDrafts(structure.relationships),
  )
  const [saving, setSaving] = useState(false)

  // 열 때마다 저장된 구조에서 다시 시작한다.
  useEffect(() => {
    if (!open) return
    setTarget(structure.target_episodes)
    setParts(structure.parts)
    setThreads(structure.threads)
    setRelationships(toDrafts(structure.relationships))
  }, [open, structure])

  const setPart = (index: number, patch: Partial<StoryPart>) =>
    setParts((current) => current.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  const setThread = (index: number, patch: Partial<PlannedThread>) =>
    setThreads((current) => current.map((t, i) => (i === index ? { ...t, ...patch } : t)))
  const setRelationship = (index: number, patch: Partial<RelationshipDraft>) =>
    setRelationships((current) => current.map((r, i) => (i === index ? { ...r, ...patch } : r)))

  const save = async () => {
    setSaving(true)
    try {
      const next = await api.saveStructure({
        target_episodes: target,
        parts,
        threads,
        relationships: fromDrafts(relationships),
      })
      success('작품 구조를 저장했습니다.')
      await onSaved(next)
    } catch (cause) {
      fromError(cause, '저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const number = (value: string) => Math.max(1, Math.round(Number(value) || 1))

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="작품 구조 직접 고치기"
      description="부의 구간이 비거나 겹치면 저장할 때 앞에서부터 이어 붙여 1화부터 마지막 화까지 빈틈없이 맞춥니다."
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            취소
          </Button>
          <Button variant="primary" loading={saving} onClick={() => void save()}>
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        <LengthFields target={target} onTargetChange={setTarget} />

        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-ink">부 구성</p>
            <Button
              size="sm"
              icon={Plus}
              onClick={() => {
                const last = parts[parts.length - 1]
                const start = last ? Math.min(last.end + 1, target) : 1
                setParts([
                  ...parts,
                  {
                    title: `${parts.length + 1}부`,
                    start,
                    end: target,
                    purpose: '',
                  },
                ])
              }}
            >
              부 추가
            </Button>
          </div>
          <ul className="space-y-3">
            {parts.map((part, index) => (
              <li key={index} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-end gap-2">
                  <span className="pb-2 text-sm text-ink-muted">{index + 1}부</span>
                  <TextField
                    className="min-w-40 flex-1"
                    label="이름"
                    value={part.title}
                    onChange={(event) => setPart(index, { title: event.target.value })}
                  />
                  <TextField
                    className="w-24"
                    label="시작"
                    type="number"
                    value={part.start}
                    onChange={(event) => setPart(index, { start: number(event.target.value) })}
                  />
                  <TextField
                    className="w-24"
                    label="끝"
                    type="number"
                    value={part.end}
                    onChange={(event) => setPart(index, { end: number(event.target.value) })}
                  />
                  <IconButton
                    icon={Trash2}
                    title="이 부 지우기"
                    variant="danger"
                    className="mb-0.5"
                    onClick={() => setParts(parts.filter((_, i) => i !== index))}
                  />
                </div>
                <textarea
                  className="sw-field mt-2 w-full text-sm"
                  rows={2}
                  placeholder="이 부에서 일어나는 일, 이 부가 끝날 때 이야기가 와 있어야 할 곳"
                  value={part.purpose}
                  onChange={(event) => setPart(index, { purpose: event.target.value })}
                />
              </li>
            ))}
          </ul>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-ink">떡밥</p>
            <Button
              size="sm"
              icon={Plus}
              onClick={() =>
                setThreads([
                  ...threads,
                  {
                    name: '',
                    description: '',
                    plant: 1,
                    payoff: Math.min(target, 50),
                  },
                ])
              }
            >
              떡밥 추가
            </Button>
          </div>
          <ul className="space-y-3">
            {threads.map((thread, index) => (
              <li key={index} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-end gap-2">
                  <TextField
                    className="min-w-40 flex-1"
                    label="이름"
                    value={thread.name}
                    onChange={(event) => setThread(index, { name: event.target.value })}
                  />
                  <TextField
                    className="w-24"
                    label="심는 회차"
                    type="number"
                    value={thread.plant}
                    onChange={(event) => setThread(index, { plant: number(event.target.value) })}
                  />
                  <TextField
                    className="w-24"
                    label="회수 회차"
                    type="number"
                    value={thread.payoff}
                    onChange={(event) => setThread(index, { payoff: number(event.target.value) })}
                  />
                  <IconButton
                    icon={Trash2}
                    title="이 떡밥 지우기"
                    variant="danger"
                    className="mb-0.5"
                    onClick={() => setThreads(threads.filter((_, i) => i !== index))}
                  />
                </div>
                <textarea
                  className="sw-field mt-2 w-full text-sm"
                  rows={2}
                  placeholder="무엇을 심고, 결국 어떻게 회수되는지 (작가용 메모 — 답까지 적어 두세요)"
                  value={thread.description}
                  onChange={(event) => setThread(index, { description: event.target.value })}
                />
              </li>
            ))}
          </ul>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-ink">관계 흐름</p>
            <Button
              size="sm"
              icon={Plus}
              onClick={() =>
                setRelationships([
                  ...relationships,
                  { names: '', start: '', arc: '', turnsText: '' },
                ])
              }
            >
              관계 추가
            </Button>
          </div>
          <ul className="space-y-3">
            {relationships.map((relationship, index) => (
              <li key={index} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-end gap-2">
                  <TextField
                    className="min-w-40 flex-1"
                    label="두 인물 (쉼표로 구분)"
                    placeholder="예: 강진우, 이서윤"
                    value={relationship.names}
                    onChange={(event) => setRelationship(index, { names: event.target.value })}
                  />
                  <TextField
                    className="min-w-40 flex-1"
                    label="처음 관계"
                    value={relationship.start}
                    onChange={(event) => setRelationship(index, { start: event.target.value })}
                  />
                  <IconButton
                    icon={Trash2}
                    title="이 관계 지우기"
                    variant="danger"
                    className="mb-0.5"
                    onClick={() => setRelationships(relationships.filter((_, i) => i !== index))}
                  />
                </div>
                <textarea
                  className="sw-field mt-2 w-full text-sm"
                  rows={2}
                  placeholder="어떻게 변해 가서 결국 어디에 닿는지"
                  value={relationship.arc}
                  onChange={(event) => setRelationship(index, { arc: event.target.value })}
                />
                <textarea
                  className="sw-field mt-2 w-full font-mono text-xs"
                  rows={3}
                  placeholder={'전환점 — 한 줄에 하나, "회차: 변화"\n예: 30: 처음으로 비밀을 털어놓는다'}
                  value={relationship.turnsText}
                  onChange={(event) => setRelationship(index, { turnsText: event.target.value })}
                />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Modal>
  )
}

// 관계 전환점은 편집하는 동안 "30: 변화" 줄 형식의 글로 다루고, 저장할 때만 나눈다.
interface RelationshipDraft {
  names: string
  start: string
  arc: string
  turnsText: string
}

const toDrafts = (relationships: PlannedRelationship[] = []): RelationshipDraft[] =>
  relationships.map((r) => ({
    names: r.characters.join(', '),
    start: r.start,
    arc: r.arc,
    turnsText: r.turns.map((t) => `${t.episode}: ${t.change}`).join('\n'),
  }))

const fromDrafts = (drafts: RelationshipDraft[]): PlannedRelationship[] =>
  drafts.map((d) => ({
    characters: d.names
      .split(/[,·]/)
      .map((name) => name.trim())
      .filter(Boolean),
    start: d.start.trim(),
    arc: d.arc.trim(),
    turns: d.turnsText
      .split('\n')
      .map((line) => line.match(/^\s*(\d+)\s*[:：화]\s*(.+)$/))
      .filter((match): match is RegExpMatchArray => match !== null)
      .map((match) => ({ episode: Number(match[1]), change: match[2].trim() })),
  }))
