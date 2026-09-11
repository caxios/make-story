/**
 * 👤 Character Workshop — the cast, and how they feel about each other.
 *
 * The drawer edits a working copy and saves it in one call, rather than firing
 * a request per keystroke: a character sheet is a document, not a settings
 * panel, and half-written prose has no business reaching the model.
 */

import {
  Copy,
  Eye,
  EyeOff,
  Heart,
  Network,
  Pencil,
  Plus,
  Trash2,
  UserRound,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { CharacterGraph } from '@/components/CharacterGraph'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  EmptyState,
  IconButton,
  Modal,
  PageHeader,
  Panel,
  SelectField,
  Slider,
  Tabs,
  TagInput,
  TextArea,
  TextField,
} from '@/components/ui'
import { useProject } from '@/state/ProjectContext'
import type {
  CharacterGraph as GraphData,
  CharacterProfile,
  Relationship,
  Trait,
} from '@/types/storyweaver'

const ROLES = [
  '주인공',
  '적대자 / 악역',
  '서브 주인공',
  '조연',
  '스승 / 조력자',
  '라이벌 / 대조 인물',
  '연인 / 히로인',
  '단역 / 엑스트라',
] as const

export const ROLE_LABELS: Record<string, string> = {
  주인공: '주인공',
  '적대자 / 악역': '적대자 / 악역',
  '서브 주인공': '서브 주인공',
  조연: '조연',
  '스승 / 조력자': '스승 / 조력자',
  '라이벌 / 대조 인물': '라이벌 / 대조 인물',
  '연인 / 히로인': '연인 / 히로인',
  '단역 / 엑스트라': '단역 / 엑스트라',
  // 영문 레거시 호환
  protagonist: '주인공',
  antagonist: '적대자 / 악역',
  deuteragonist: '서브 주인공',
  supporting: '조연',
  mentor: '스승 / 조력자',
  foil: '라이벌 / 대조 인물',
  'love interest': '연인 / 히로인',
  minor: '단역 / 엑스트라',
}

const RELATIONSHIP_TYPES = [
  '친구',
  '라이벌',
  '스승',
  '제자',
  '가족',
  '동맹 / 아군',
  '적 / 원수',
  '연인',
  '동료',
  '남 / 초면',
] as const

export const RELATIONSHIP_LABELS: Record<string, string> = {
  친구: '친구',
  라이벌: '라이벌',
  스승: '스승',
  제자: '제자',
  가족: '가족',
  '동맹 / 아군': '동맹 / 아군',
  '적 / 원수': '적 / 원수',
  연인: '연인',
  동료: '동료',
  '남 / 초면': '남 / 초면',
  // 영문 레거시 호환
  friend: '친구',
  rival: '라이벌',
  mentor: '스승',
  student: '제자',
  family: '가족',
  ally: '동맹 / 아군',
  enemy: '적 / 원수',
  lover: '연인',
  colleague: '동료',
  stranger: '남 / 초면',
}

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role
}

export function relationshipLabel(type: string): string {
  return RELATIONSHIP_LABELS[type] ?? type
}

/** Traits a new character starts with — a spread, not a template to keep. */
const STARTER_TRAITS = ['용기', '따뜻함', '현실적', '자존심'] as const

function blankCharacter(): CharacterProfile {
  return {
    id: '',
    name: '',
    role: '조연',
    aliases: [],
    age: null,
    gender: null,
    appearance: '',
    personality_summary: '',
    traits: STARTER_TRAITS.map((name) => ({ name, intensity: 0.5, description: null })),
    speech_style: '',
    values: [],
    goals: [],
    backstory: '',
    relationships: [],
    secrets: [],
    author_notes: '',
  }
}

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^\p{L}\p{N}-]/gu, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
}

/** The card blurb: the first sentence of the personality summary. */
function oneLine(character: CharacterProfile): string {
  const summary = character.personality_summary.trim()
  if (!summary) return '아직 성격 요약이 작성되지 않았습니다.'
  const stop = summary.search(/[.!?。](\s|$)/)
  return stop === -1 ? summary : summary.slice(0, stop + 1)
}

function roleTone(role: string) {
  if (
    role === '주인공' ||
    role === '서브 주인공' ||
    role === 'protagonist' ||
    role === 'deuteragonist'
  )
    return 'accent' as const
  if (role === '적대자 / 악역' || role === 'antagonist') return 'bad' as const
  if (
    role === '스승 / 조력자' ||
    role === '연인 / 히로인' ||
    role === 'mentor' ||
    role === 'love interest'
  )
    return 'violet' as const
  return 'neutral' as const
}

type TabId = 'cast' | 'graph'

export function CharacterWorkshop() {
  const { project, loading, refresh } = useProject()
  const { success, fromError } = useToast()

  const [tab, setTab] = useState<TabId>('cast')
  const [editing, setEditing] = useState<CharacterProfile | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [deleting, setDeleting] = useState<CharacterProfile | null>(null)
  const [cloning, setCloning] = useState<CharacterProfile | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  const characters = useMemo(() => project?.characters ?? [], [project])

  // The graph is derived server-side, so it is fetched rather than computed —
  // and refetched whenever the cast changes underneath it.
  useEffect(() => {
    if (tab !== 'graph') return
    let cancelled = false
    void api
      .getCharacterGraph()
      .then((data) => !cancelled && setGraph(data))
      .catch((cause) => fromError(cause, '인물 관계도를 불러오지 못했습니다.'))
    return () => {
      cancelled = true
    }
  }, [tab, characters, fromError])

  const remove = async (character: CharacterProfile) => {
    try {
      await api.deleteCharacter(character.id)
      await refresh()
      const referrers = characters.filter((other) =>
        other.relationships.some((r) => r.target_character_id === character.id),
      ).length
      success(
        referrers > 0
          ? `'${character.name}' 캐릭터 및 관련 관계 ${referrers}개를 삭제했습니다.`
          : `'${character.name}' 캐릭터를 삭제했습니다.`,
      )
    } catch (cause) {
      fromError(cause, '캐릭터를 삭제하지 못했습니다.')
    }
  }

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />
  if (!project) return null

  return (
    <>
      <PageHeader
        title="캐릭터 워크숍"
        description="등장인물의 신원, 말투, 가치관, 비밀 등 AI 에이전트가 연기할 모든 설정을 구성합니다."
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditing(blankCharacter())
              setIsNew(true)
            }}
          >
            캐릭터 추가
          </Button>
        }
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'cast', label: '등장인물 목록', icon: Users, count: characters.length },
          { id: 'graph', label: '관계도 그래프', icon: Network },
        ]}
      />

      {tab === 'cast' &&
        (characters.length === 0 ? (
          <Panel>
            <EmptyState
              icon={UserRound}
              title="등록된 캐릭터가 없습니다"
              description="에피소드를 진행하려면 최소 한 명 이상의 캐릭터가 필요합니다. 캐릭터 시트의 모든 내용은 AI 에이전트의 대사와 행동의 기준이 됩니다."
              action={
                <Button
                  variant="primary"
                  icon={Plus}
                  onClick={() => {
                    setEditing(blankCharacter())
                    setIsNew(true)
                  }}
                >
                  첫 캐릭터 추가하기
                </Button>
              }
            />
          </Panel>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {characters.map((character) => (
              <CharacterCard
                key={character.id}
                character={character}
                onEdit={() => {
                  setEditing(character)
                  setIsNew(false)
                }}
                onClone={() => setCloning(character)}
                onDelete={() => setDeleting(character)}
              />
            ))}
          </div>
        ))}

      {tab === 'graph' && (
        <Panel
          title="인물 관계도 네트워크"
          description="캐릭터를 클릭하면 설정을 확인/수정할 수 있습니다. 마우스를 올리면 연결된 관계가 강조됩니다."
        >
          {characters.length === 0 ? (
            <EmptyState
              icon={Network}
              title="표시할 관계도가 없습니다"
              description="캐릭터를 추가하고 서로 간의 관계를 설정하면 여기에 시각화됩니다."
            />
          ) : graph === null ? (
            <div className="h-96 animate-pulse-soft rounded-xl bg-white/2" />
          ) : graph.edges.length === 0 ? (
            <>
              <CharacterGraph
                graph={graph}
                onSelect={(id) => {
                  const found = characters.find((character) => character.id === id)
                  if (found) {
                    setEditing(found)
                    setIsNew(false)
                  }
                }}
              />
              <p className="mt-4 text-center text-xs text-ink-muted">
                아직 설정된 관계가 없습니다 — 캐릭터를 열어 다른 인물과의 관계를 추가해 보세요.
              </p>
            </>
          ) : (
            <CharacterGraph
              graph={graph}
              onSelect={(id) => {
                const found = characters.find((character) => character.id === id)
                if (found) {
                  setEditing(found)
                  setIsNew(false)
                }
              }}
            />
          )}
        </Panel>
      )}

      <CharacterDrawer
        character={editing}
        isNew={isNew}
        cast={characters}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />

      <CloneDialog
        character={cloning}
        existingIds={characters.map((character) => character.id)}
        onClose={() => setCloning(null)}
        onCloned={refresh}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title={`정말 '${deleting?.name}' 캐릭터를 삭제하시겠습니까?`}
        message={
          <>
            해당 캐릭터를 향한 모든 관계 설정도 함께 삭제됩니다.
            <p className="mt-2 text-ink-muted">
              이미 작성 완료된 회차 본문은 안전하게 유지됩니다.
            </p>
          </>
        }
      />
    </>
  )
}

// ==========================================================================
// Card
// ==========================================================================

function CharacterCard({
  character,
  onEdit,
  onClone,
  onDelete,
}: {
  character: CharacterProfile
  onEdit: () => void
  onClone: () => void
  onDelete: () => void
}) {
  const strongest = [...character.traits].sort((a, b) => b.intensity - a.intensity).slice(0, 3)

  return (
    <div className="sw-panel group flex flex-col p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold tracking-tight text-ink">
              {character.name || '(이름 없음)'}
            </h3>
            {character.role && <Badge tone={roleTone(character.role)}>{roleLabel(character.role)}</Badge>}
          </div>
          <p className="mt-1 font-mono text-xs text-ink-muted">#{character.id}</p>
        </div>
        <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <IconButton icon={Pencil} title={`${character.name} 수정`} onClick={onEdit} />
          <IconButton icon={Copy} title={`${character.name} 복제`} onClick={onClone} />
          <IconButton icon={Trash2} title={`${character.name} 삭제`} onClick={onDelete} />
        </div>
      </div>

      <p className="mt-3 line-clamp-3 flex-1 text-xs leading-relaxed text-ink-dim">
        {oneLine(character)}
      </p>

      {strongest.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {strongest.map((trait) => (
            <div key={trait.name} className="flex items-center gap-2">
              <span className="w-20 shrink-0 truncate text-[0.68rem] text-ink-muted">
                {trait.name}
              </span>
              <span className="h-1 flex-1 overflow-hidden rounded-full bg-line">
                <span
                  className="block h-full rounded-full bg-accent/70"
                  style={{ width: `${trait.intensity * 100}%` }}
                />
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3.5 flex items-center gap-3 border-t border-line pt-3 text-[0.68rem] text-ink-muted">
        <span className="flex items-center gap-1">
          <Heart className="size-3" />
          관계 {character.relationships.length}개
        </span>
        {character.secrets.length > 0 && (
          <span className="flex items-center gap-1">
            <EyeOff className="size-3" />
            비밀 {character.secrets.length}개
          </span>
        )}
      </div>
    </div>
  )
}

// ==========================================================================
// Drawer
// ==========================================================================

function CharacterDrawer({
  character,
  isNew,
  cast,
  onClose,
  onSaved,
}: {
  character: CharacterProfile | null
  isNew: boolean
  cast: CharacterProfile[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState<CharacterProfile>(character ?? blankCharacter())
  const [saving, setSaving] = useState(false)
  const [showSecrets, setShowSecrets] = useState(false)

  useEffect(() => {
    if (character) {
      setDraft(character)
      setShowSecrets(false)
    }
  }, [character])

  const idTaken = isNew && cast.some((existing) => existing.id === draft.id.trim())
  const valid = draft.id.trim() !== '' && draft.name.trim() !== '' && !idTaken

  const patch = (changes: Partial<CharacterProfile>) =>
    setDraft((previous) => ({ ...previous, ...changes }))

  const save = async () => {
    setSaving(true)
    try {
      await api.upsertCharacter({ ...draft, id: draft.id.trim(), name: draft.name.trim() })
      await onSaved()
      success(isNew ? `'${draft.name}' 캐릭터를 등록했습니다.` : `'${draft.name}' 캐릭터 설정을 저장했습니다.`)
      onClose()
    } catch (cause) {
      fromError(cause, '캐릭터를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const others = cast.filter((other) => other.id !== draft.id)

  return (
    <Drawer
      open={character !== null}
      onClose={onClose}
      title={isNew ? '새 캐릭터 등록' : draft.name || '(이름 없음)'}
      description={isNew ? undefined : `#${draft.id}`}
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!valid}>
            {isNew ? '캐릭터 등록' : '저장하기'}
          </Button>
        </>
      }
    >
      <div className="space-y-7">
        {/* --- Basics --- */}
        <Section title="기본 신원">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="이름"
              value={draft.name}
              onChange={(event) => {
                const name = event.target.value
                setDraft((previous) => ({
                  ...previous,
                  name,
                  id:
                    isNew && previous.id === slugify(previous.name)
                      ? slugify(name)
                      : previous.id,
                }))
              }}
              placeholder="예: 홍길동"
            />
            <TextField
              label="고유 식별자 (ID)"
              value={draft.id}
              disabled={!isNew}
              onChange={(event) => patch({ id: event.target.value })}
              placeholder="hong-gildong"
              hint={
                idTaken
                  ? '이미 존재하는 ID입니다.'
                  : isNew
                    ? '씬과 관계 설정에서 영문 식별자로 사용됩니다.'
                    : 'ID는 한 번 생성되면 고정됩니다.'
              }
            />
            <SelectField
              label="초기 Role"
              value={draft.role}
              onChange={(event) => patch({ role: event.target.value })}
              options={[
                { value: '', label: '— 선택 안 함 —' },
                ...(draft.role && !ROLES.includes(draft.role as (typeof ROLES)[number])
                  ? [{ value: draft.role, label: draft.role }]
                  : []),
                ...ROLES.map((role) => ({ value: role, label: ROLE_LABELS[role] ?? role })),
              ]}
              hint="이야기 시작 시점의 역할입니다. 서사가 진행됨에 따라 관계와 입지는 변화할 수 있습니다."
            />
            <TextField
              label="나이"
              type="number"
              value={draft.age ?? ''}
              onChange={(event) =>
                patch({ age: event.target.value === '' ? null : Number(event.target.value) })
              }
              placeholder="—"
            />
            <TextField
              label="성별"
              value={draft.gender ?? ''}
              onChange={(event) => patch({ gender: event.target.value || null })}
              placeholder="—"
              className="sm:col-span-2"
            />
          </div>

          <TagInput
            label="별칭 / 이명"
            values={draft.aliases}
            onChange={(aliases) => patch({ aliases })}
            hint="작품 속에서 캐릭터를 부르는 다른 호칭, 별명, 칭호 등"
            placeholder="별칭 입력 후 Enter"
          />

          <TextArea
            label="성격 요약"
            rows={4}
            value={draft.personality_summary}
            onChange={(event) => patch({ personality_summary: event.target.value })}
            placeholder="평소 성격, 태도, 분위기 등을 한 문단으로 묘사합니다."
            hint="첫 문장은 캐릭터 카드에 바로 표시됩니다."
          />

          <TextArea
            label="외모 묘사"
            rows={3}
            value={draft.appearance}
            onChange={(event) => patch({ appearance: event.target.value })}
            placeholder="타인이 보았을 때 가장 먼저 눈에 띄는 인상, 옷차림, 체격 등"
          />
        </Section>

        {/* --- Traits --- */}
        <Section
          title="성격 특성"
          description="특성의 강도는 수치 다이얼(0.0~1.0)로 에이전트에 전달됩니다 (0.9 용기는 적극적으로 맞서지만, 0.2 용기는 출구를 찾습니다)."
        >
          <TraitEditor traits={draft.traits} onChange={(traits) => patch({ traits })} />
        </Section>

        {/* --- Voice --- */}
        <Section title="말투 및 어조">
          <TextArea
            label="대화 스타일 / 어투"
            rows={4}
            value={draft.speech_style}
            onChange={(event) => patch({ speech_style: event.target.value })}
            placeholder="격식 정도, 사투리/방언, 말버릇, 그리고 이 캐릭터가 실제로 할 법한 대사 예시를 적어주세요."
            hint="자유 텍스트로 에이전트 프롬프트에 직접 인용됩니다. 실제 대사 예시를 적어주면 가장 효과적입니다."
          />
        </Section>

        {/* --- Motivation --- */}
        <Section title="행동 동기 및 가치관">
          <TagInput
            label="현재 목표"
            values={draft.goals}
            onChange={(goals) => patch({ goals })}
            hint="지금 캐릭터가 필사적으로 쫓고 있는 목표"
            placeholder="목표 입력 후 Enter"
          />
          <TagInput
            label="핵심 가치관"
            values={draft.values}
            onChange={(values) => patch({ values })}
            hint="어떤 상황에서도 절대 타협하지 않는 원칙"
            placeholder="가치관 입력 후 Enter"
          />
          <TextArea
            label="과거 배경 / 뒷이야기"
            rows={4}
            value={draft.backstory}
            onChange={(event) => patch({ backstory: event.target.value })}
            placeholder="이야기 1화가 시작되기 전에 이 인물에게 일어난 중요한 과거사"
          />
        </Section>

        {/* --- Secrets --- */}
        <Section
          title="비밀 설정"
          description="이 캐릭터 본인만 알고 있는 비밀입니다. 다른 캐릭터의 에이전트는 절대 이 내용을 볼 수 없습니다."
          action={
            <Button
              size="sm"
              icon={showSecrets ? EyeOff : Eye}
              onClick={() => setShowSecrets((value) => !value)}
            >
              {showSecrets ? '숨기기' : `보기${draft.secrets.length ? ` (${draft.secrets.length})` : ''}`}
            </Button>
          }
        >
          {showSecrets ? (
            <>
              <TagInput
                values={draft.secrets}
                onChange={(secrets) => patch({ secrets })}
                placeholder="비밀 입력 후 Enter"
              />
              <TextArea
                label="작가 메모"
                rows={3}
                value={draft.author_notes}
                onChange={(event) => patch({ author_notes: event.target.value })}
                placeholder="작가 본인만을 위한 비망록. 어떤 에이전트에게도 캐릭터 지식으로 전달되지 않습니다."
              />
            </>
          ) : (
            <p className="text-xs text-ink-muted">
              {draft.secrets.length === 0
                ? '아직 등록된 비밀이 없습니다.'
                : `비밀 ${draft.secrets.length}개가 숨김 처리되어 있습니다.`}
            </p>
          )}
        </Section>

        {/* --- Relationships --- */}
        <Section
          title="인물 간 관계"
          description="단방향 감정선: 이 캐릭터가 상대방을 어떻게 대하고 생각하는지를 설정합니다."
        >
          <RelationshipEditor
            relationships={draft.relationships}
            others={others}
            onChange={(relationships) => patch({ relationships })}
          />
        </Section>
      </div>
    </Drawer>
  )
}

function Section({
  title,
  description,
  action,
  children,
}: {
  title: string
  description?: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-line pb-2">
        <div>
          <h3 className="text-xs font-semibold tracking-wide text-ink uppercase">{title}</h3>
          {description && (
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{description}</p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

// --------------------------------------------------------------------------
// Traits
// --------------------------------------------------------------------------

function TraitEditor({
  traits,
  onChange,
}: {
  traits: Trait[]
  onChange: (traits: Trait[]) => void
}) {
  const [name, setName] = useState('')

  const add = () => {
    const trimmed = name.trim()
    if (!trimmed || traits.some((trait) => trait.name === trimmed)) return
    onChange([...traits, { name: trimmed, intensity: 0.5, description: null }])
    setName('')
  }

  return (
    <div className="space-y-3">
      {traits.length > 0 && (
        <div className="space-y-3 rounded-xl border border-line bg-surface px-4 py-3.5">
          {traits.map((trait, index) => (
            <div key={`${trait.name}-${index}`} className="flex items-end gap-3">
              <div className="min-w-0 flex-1">
                <Slider
                  label={trait.name}
                  value={trait.intensity}
                  onChange={(intensity) =>
                    onChange(
                      traits.map((existing, i) =>
                        i === index ? { ...existing, intensity } : existing,
                      ),
                    )
                  }
                />
              </div>
              <IconButton
                icon={Trash2}
                title={`${trait.name} 특성 삭제`}
                className="mb-0.5"
                onClick={() => onChange(traits.filter((_, i) => i !== index))}
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add()
            }
          }}
          placeholder="새 성격 특성 추가 (예: 용기, 냉소, 온화함, 결단력…)"
          className="sw-field flex-1 text-sm"
        />
        <Button icon={Plus} onClick={add} disabled={!name.trim()}>
          추가
        </Button>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Relationships
// --------------------------------------------------------------------------

function RelationshipEditor({
  relationships,
  others,
  onChange,
}: {
  relationships: Relationship[]
  others: CharacterProfile[]
  onChange: (relationships: Relationship[]) => void
}) {
  const nameOf = (id: string) => others.find((other) => other.id === id)?.name ?? id

  const update = (index: number, changes: Partial<Relationship>) =>
    onChange(
      relationships.map((existing, i) => (i === index ? { ...existing, ...changes } : existing)),
    )

  const unrelated = others.filter(
    (other) => !relationships.some((r) => r.target_character_id === other.id),
  )

  if (others.length === 0) {
    return (
      <p className="text-xs text-ink-muted">
        관계를 맺을 다른 캐릭터가 없습니다. 먼저 다른 캐릭터를 등록해 주세요.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {relationships.map((relationship, index) => (
        <div
          key={`${relationship.target_character_id}-${index}`}
          className="space-y-3 rounded-xl border border-line bg-surface px-4 py-3.5"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm font-medium text-ink">
              {nameOf(relationship.target_character_id)}
            </span>
            <IconButton
              icon={Trash2}
              title={`${nameOf(relationship.target_character_id)}와의 관계 삭제`}
              onClick={() => onChange(relationships.filter((_, i) => i !== index))}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label="대상 인물"
              value={relationship.target_character_id}
              onChange={(event) => update(index, { target_character_id: event.target.value })}
              options={others.map((other) => ({ value: other.id, label: other.name }))}
            />
            <SelectField
              label="관계 유형"
              value={relationship.type}
              onChange={(event) => update(index, { type: event.target.value })}
              options={[
                ...(RELATIONSHIP_TYPES.includes(
                  relationship.type as (typeof RELATIONSHIP_TYPES)[number],
                )
                  ? []
                  : [{ value: relationship.type, label: relationship.type }]),
                ...RELATIONSHIP_TYPES.map((type) => ({
                  value: type,
                  label: RELATIONSHIP_LABELS[type] ?? type,
                })),
              ]}
            />
          </div>

          <Slider
            label="호감도 / 감정선"
            tone="sentiment"
            min={-1}
            max={1}
            step={0.05}
            value={relationship.sentiment}
            onChange={(sentiment) => update(index, { sentiment })}
            format={(value) =>
              `${value > 0 ? '+' : ''}${value.toFixed(2)} · ${
                value > 0.3 ? '우호 / 동맹' : value < -0.3 ? '적대 / 반목' : '중립'
              }`
            }
          />

          <TextField
            label="관계 세부 메모"
            value={relationship.description ?? ''}
            onChange={(event) => update(index, { description: event.target.value || null })}
            placeholder="단순한 유형과 수치만으로는 다 담지 못하는 둘만의 구체적인 관계성"
          />
        </div>
      ))}

      <Button
        icon={Plus}
        disabled={unrelated.length === 0}
        onClick={() =>
          unrelated[0] &&
          onChange([
            ...relationships,
            {
              target_character_id: unrelated[0].id,
              type: '친구',
              sentiment: 0,
              description: null,
            },
          ])
        }
      >
        {unrelated.length === 0 ? '모든 등장인물과의 관계가 설정되었습니다' : '새 관계 추가하기'}
      </Button>
    </div>
  )
}

// --------------------------------------------------------------------------
// Clone
// --------------------------------------------------------------------------

function CloneDialog({
  character,
  existingIds,
  onClose,
  onCloned,
}: {
  character: CharacterProfile | null
  existingIds: string[]
  onClose: () => void
  onCloned: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [name, setName] = useState('')
  const [id, setId] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (character) {
      setName(`${character.name} (복사본)`)
      setId(`${character.id}-copy`)
    }
  }, [character])

  const taken = existingIds.includes(id.trim())
  const valid = id.trim() !== '' && name.trim() !== '' && !taken

  const clone = async () => {
    if (!character) return
    setSaving(true)
    try {
      await api.cloneCharacter(character.id, id.trim(), name.trim())
      await onCloned()
      success(`${character.name} 캐릭터를 복제하여 '${name.trim()}' 캐릭터를 생성했습니다`)
      onClose()
    } catch (cause) {
      fromError(cause, '캐릭터를 복제하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={character !== null}
      onClose={onClose}
      title={`${character?.name} 캐릭터 복제`}
      description="성격, 말투, 가치관, 비밀, 관계 등 모든 설정이 그대로 복사됩니다."
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={() => void clone()} loading={saving} disabled={!valid}>
            복제하기
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="새 캐릭터 이름"
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setId(slugify(event.target.value))
          }}
        />
        <TextField
          label="새 고유 식별자 (ID)"
          value={id}
          onChange={(event) => setId(event.target.value)}
          hint={taken ? '이미 사용 중인 ID입니다.' : undefined}
        />
      </div>
    </Modal>
  )
}
