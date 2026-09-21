/**
 * 🌍 World Builder — the overview, the rules the Lore Checker enforces, and
 * where everything happens.
 *
 * The last three tabs are three different jobs: writing the premise, writing
 * the constraints, and drawing the map. They do not share a save button,
 * because they do not share a working session.
 *
 * Quick Setup is the way in before any of that exists: a paragraph read into
 * all three at once, which is why it is the landing tab on an empty world and
 * has to ask before it runs on a world that already has something in it.
 */

import {
  BookOpen,
  ChevronRight,
  CornerDownRight,
  MapPin,
  Pencil,
  Plus,
  Scale,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Modal,
  PageHeader,
  Panel,
  SelectField,
  Tabs,
  TagInput,
  TextArea,
  TextField,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { Location, Rule, WorldLore } from '@/types/storyweaver'

const GENRES = [
  'fantasy',
  'science fiction',
  'mystery',
  'modern',
  'historical',
  'horror',
  'romance',
  'thriller',
  'literary',
] as const

const GENRE_LABELS: Record<string, string> = {
  fantasy: '판타지 (Fantasy)',
  'science fiction': 'SF / 공상과학 (Sci-Fi)',
  mystery: '추리 / 미스터리 (Mystery)',
  modern: '현대 / 일상 (Modern)',
  historical: '역사 / 시대극 (Historical)',
  horror: '공포 / 호러 (Horror)',
  romance: '로맨스 (Romance)',
  thriller: '스릴러 (Thriller)',
  literary: '순문학 (Literary)',
}

const RULE_CATEGORIES = [
  'magic',
  'physics',
  'society',
  'politics',
  'technology',
  'taboo',
  'economy',
  'biology',
] as const

const RULE_CATEGORY_LABELS: Record<string, string> = {
  magic: '마법 / 초능력 (magic)',
  physics: '물리 법칙 (physics)',
  society: '사회 / 문화 (society)',
  politics: '정치 / 세력 (politics)',
  technology: '과학 / 기술 (technology)',
  taboo: '금기 / 터부 (taboo)',
  economy: '경제 / 화폐 (economy)',
  biology: '생물 / 종족 (biology)',
}

type TabId = 'quick-setup' | 'overview' | 'rules' | 'locations'

export function WorldBuilder() {
  const { project, loading, refresh } = useProject()
  // Null means the author has not picked a tab yet, and the landing tab is
  // derived below. An effect that forced the tab instead would drag them back
  // here on every project reload, because a reload is a new world object.
  const [chosen, setChosen] = useState<TabId | null>(null)

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />
  if (!project) return null

  const world = project.world
  // An empty world opens on Quick Setup: there is nothing to edit yet, and a
  // paragraph is a faster first move than six empty fields. The title is no
  // use as a signal here — a new project is born holding "Untitled World" —
  // so emptiness is what the author has actually put in.
  const blank =
    !world.overview.trim() && world.rules.length === 0 && world.locations.length === 0
  const tab: TabId = chosen ?? (blank ? 'quick-setup' : 'overview')
  const setTab = setChosen

  return (
    <>
      <PageHeader
        title="세계관 빌더"
        description="작품의 기본 전제, 지켜야 할 세계관 규칙, 그리고 이야기가 펼쳐지는 장소들을 정의합니다."
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'quick-setup', label: '빠른 설정', icon: Sparkles },
          { id: 'overview', label: '기본 전제 (개요)', icon: BookOpen },
          { id: 'rules', label: '세계관 규칙', icon: Scale, count: world.rules.length },
          { id: 'locations', label: '장소 / 공간', icon: MapPin, count: world.locations.length },
        ]}
      />

      {tab === 'quick-setup' && (
        <QuickSetupTab world={world} onSaved={refresh} onDone={() => setTab('overview')} />
      )}
      {tab === 'overview' && <OverviewTab world={world} onSaved={refresh} />}
      {tab === 'rules' && <RulesTab rules={world.rules} onChanged={refresh} />}
      {tab === 'locations' && <LocationsTab locations={world.locations} onChanged={refresh} />}
    </>
  )
}

// ==========================================================================
// Quick setup
// ==========================================================================

/**
 * A paragraph in, a world out.
 *
 * Unlike the character sheet, this one saves as soon as it has read the
 * description: the other three tabs are where it gets refined, so there is
 * nowhere sensible to hold an unsaved world in the meantime. That makes it
 * destructive on a world that already exists, so a world that already exists
 * gets asked first.
 */
function QuickSetupTab({
  world,
  onSaved,
  onDone,
}: {
  world: WorldLore
  onSaved: () => Promise<void>
  onDone: () => void
}) {
  const { success, fromError } = useToast()
  const [text, setText] = useState('')
  const [working, setWorking] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const hasContent =
    world.overview.trim().length > 0 || world.rules.length > 0 || world.locations.length > 0

  const run = async () => {
    if (!text.trim()) return
    setConfirming(false)
    setWorking(true)
    try {
      const parsed = await api.parseWorld(text.trim())
      await api.applyParsedWorld(parsed)
      await onSaved()
      success(
        `세계관을 반영했습니다 — 규칙 ${parsed.rules.length}개, 장소 ${parsed.locations.length}곳.`,
      )
      setText('')
      onDone()
    } catch (cause) {
      fromError(cause, '설명에서 세계관을 읽어내지 못했습니다.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <Panel
      title="설명에서 세계관 불러오기"
      description="세계관을 평소 말하듯 적어 주세요. 제목, 장르, 분위기, 시대, 개요, 규칙, 장소를 읽어내 채워 넣습니다. 세부 조정은 다른 탭에서 하시면 됩니다."
    >
      {hasContent && (
        <div className="mb-4 rounded-lg border border-warn/30 bg-warn/10 p-3 text-xs leading-relaxed text-warn-bright">
          이미 설정된 세계관이 있습니다. 실행하면 <strong>제목·장르·분위기·시대·개요·세력</strong>이
          새로 읽어낸 내용으로 교체됩니다. 규칙과 장소는 추가되며, ID가 같은 항목만 교체됩니다 —
          기존 항목이 삭제되지는 않습니다.
        </div>
      )}

      <TextArea
        label="세계관 설명"
        rows={12}
        placeholder={'예시: 마법사와 머글이 공존하는 현대 영국. 호그와트는 스코틀랜드 산중의 마법 학교로, 9와 3/4 승강장을 통해서만 갈 수 있다. 마법의 존재는 머글에게 비밀이며, 어둠의 마법사 볼드모트의 부활이 이야기의 주요 위협이다. 금지된 저주(아바다 케다브라, 크루시오, 임페리우스)는 사용이 금지된다.'}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />

      <div className="mt-4 flex justify-end">
        <Button
          variant="primary"
          icon={Sparkles}
          loading={working}
          disabled={!text.trim() || working}
          onClick={() => (hasContent ? setConfirming(true) : void run())}
        >
          {working ? '읽는 중…' : '설명에서 불러오기'}
        </Button>
      </div>

      <ConfirmDialog
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={() => void run()}
        title="기존 세계관을 덮어쓸까요?"
        confirmLabel="덮어쓰기"
        message={
          <>
            제목, 장르, 분위기, 시대, 개요, 세력이 새로 읽어낸 내용으로 교체됩니다.
            <p className="mt-2 text-ink-muted">
              규칙 {world.rules.length}개와 장소 {world.locations.length}곳은 그대로 남고, ID가 같은
              항목만 교체됩니다. 이미 작성된 회차 본문은 영향을 받지 않습니다.
            </p>
          </>
        }
      />
    </Panel>
  )
}

// ==========================================================================
// Overview
// ==========================================================================

function OverviewTab({ world, onSaved }: { world: WorldLore; onSaved: () => Promise<void> }) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState(world)
  const [saving, setSaving] = useState(false)

  // A save elsewhere, or a project reload, should not be overwritten by a
  // stale draft sitting in this tab.
  useEffect(() => setDraft(world), [world])

  const dirty = useMemo(
    () =>
      (['title', 'genre', 'tone', 'overview'] as const).some((key) => draft[key] !== world[key]) ||
      (draft.era ?? '') !== (world.era ?? '') ||
      draft.factions.join(' ') !== world.factions.join(' '),
    [draft, world],
  )

  const save = async () => {
    setSaving(true)
    try {
      await api.updateWorld({
        title: draft.title,
        genre: draft.genre,
        tone: draft.tone,
        era: draft.era?.trim() ? draft.era : null,
        overview: draft.overview,
        factions: draft.factions,
      })
      await onSaved()
      success('세계관 설정이 저장되었습니다')
    } catch (cause) {
      fromError(cause, '세계관을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <Panel
        title="세계관 기본 전제"
        description="모든 AI 에이전트가 이 설정을 읽습니다. 디렉터는 이를 기반으로 사건을 기획하고, 설정 검증기는 이에 어긋남이 없는지 판단합니다."
        actions={
          <>
            {dirty && <Badge tone="warn">저장되지 않음</Badge>}
            <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
              변경사항 저장
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="세계관 명칭 / 제목"
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            placeholder="예: 해리포터 마법 세계관"
          />
          <SelectField
            label="장르"
            value={GENRES.includes(draft.genre as (typeof GENRES)[number]) ? draft.genre : ''}
            onChange={(event) => setDraft({ ...draft, genre: event.target.value })}
            options={[
              ...(GENRES.includes(draft.genre as (typeof GENRES)[number])
                ? []
                : [{ value: draft.genre, label: draft.genre || '(미설정)' }]),
              ...GENRES.map((genre) => ({ value: genre, label: GENRE_LABELS[genre] ?? genre })),
            ]}
          />
          <TextField
            label="작품 분위기 (톤)"
            value={draft.tone}
            onChange={(event) => setDraft({ ...draft, tone: event.target.value })}
            placeholder="예: 기괴하지만 낭만적인, 어둡고 긴박한"
          />
          <TextField
            label="시대적 배경"
            value={draft.era ?? ''}
            onChange={(event) => setDraft({ ...draft, era: event.target.value })}
            placeholder="예: 1990년대 영국, 근미래 2040년대"
          />
        </div>

        <TextArea
          label="세계관 개요"
          className="mt-4"
          rows={10}
          value={draft.overview}
          onChange={(event) => setDraft({ ...draft, overview: event.target.value })}
          placeholder="어떤 세계인지, 독자가 1화를 읽기 전 알아야 할 핵심 배경을 설명해주세요."
          hint="몇 문단으로 작성합니다. 프로젝트에서 AI가 가장 빈번하게 참조하는 핵심 텍스트입니다."
        />

        <div className="mt-4">
          <TagInput
            label="주요 세력 / 집단 (Factions)"
            values={draft.factions}
            onChange={(factions) => setDraft({ ...draft, factions })}
            hint="가문, 길드, 학파, 정부, 범죄 조직 등 이야기 전개의 축이 되는 집단들을 입력하세요."
            placeholder="세력 이름을 입력 후 Enter를 누르세요"
          />
        </div>
      </Panel>
    </div>
  )
}

// ==========================================================================
// Rules
// ==========================================================================

const BLANK_RULE: Rule = { id: '', category: 'magic', statement: '', exceptions: [] }

function RulesTab({ rules, onChanged }: { rules: Rule[]; onChanged: () => Promise<void> }) {
  const { success, fromError } = useToast()
  const [editing, setEditing] = useState<Rule | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [deleting, setDeleting] = useState<Rule | null>(null)

  const byCategory = useMemo(() => {
    const groups = new Map<string, Rule[]>()
    for (const rule of rules) {
      groups.set(rule.category, [...(groups.get(rule.category) ?? []), rule])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [rules])

  const remove = async (rule: Rule) => {
    try {
      await api.deleteRule(rule.id)
      await onChanged()
      success(`규칙 "${rule.id}" 삭제 완료`)
    } catch (cause) {
      fromError(cause, '규칙을 삭제하지 못했습니다.')
    }
  }

  return (
    <>
      <Panel
        title="세계관의 절대 규칙"
        description="설정 검증기(Lore Checker)가 모든 장면을 이 규칙들에 비추어 검증하며, 위반 시 해당 턴을 다시 작성합니다."
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditing(BLANK_RULE)
              setIsNew(true)
            }}
          >
            규칙 추가
          </Button>
        }
      >
        {rules.length === 0 ? (
          <EmptyState
            icon={Scale}
            title="등록된 규칙이 없습니다"
            description="이야기 속에서 절대 모순되거나 깨져선 안 되는 원칙을 정의하세요 (예: 마법 사용 시 치러야 할 대가, 죽은 자는 부활할 수 없다 등)."
          />
        ) : (
          <div className="space-y-5">
            {byCategory.map(([category, group]) => (
              <div key={category}>
                <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
                  {RULE_CATEGORY_LABELS[category] ?? category}
                </p>
                <div className="space-y-2">
                  {group.map((rule) => (
                    <div
                      key={rule.id}
                      className="group flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 transition-colors hover:border-line-strong"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge mono>#{rule.id}</Badge>
                        </div>
                        <p className="mt-1.5 text-sm leading-relaxed text-ink">{rule.statement}</p>
                        {rule.exceptions.length > 0 && (
                          <ul className="mt-2 space-y-1">
                            {rule.exceptions.map((exception, index) => (
                              <li
                                key={index}
                                className="flex items-start gap-1.5 text-xs leading-relaxed text-ink-muted"
                              >
                                <CornerDownRight className="mt-0.5 size-3 shrink-0" />
                                <span>{exception}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                        <IconButton
                          icon={Pencil}
                          title={`규칙 ${rule.id} 수정`}
                          onClick={() => {
                            setEditing(rule)
                            setIsNew(false)
                          }}
                        />
                        <IconButton
                          icon={Trash2}
                          title={`규칙 ${rule.id} 삭제`}
                          onClick={() => setDeleting(rule)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <RuleModal
        rule={editing}
        isNew={isNew}
        existingIds={rules.map((rule) => rule.id)}
        onClose={() => setEditing(null)}
        onSaved={onChanged}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title="이 규칙을 삭제하시겠습니까?"
        message={
          <>
            <span className="font-mono text-xs text-ink-muted">#{deleting?.id}</span>
            <p className="mt-1.5">{deleting?.statement}</p>
            <p className="mt-3 text-ink-muted">
              이미 작성된 장면의 본문은 유지되지만, 앞으로 작성될 장면들은 더 이상 이 규칙의 검증을 받지 않습니다.
            </p>
          </>
        }
      />
    </>
  )
}

function RuleModal({
  rule,
  isNew,
  existingIds,
  onClose,
  onSaved,
}: {
  rule: Rule | null
  isNew: boolean
  existingIds: string[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState<Rule>(rule ?? BLANK_RULE)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (rule) setDraft(rule)
  }, [rule])

  const idTaken = isNew && existingIds.includes(draft.id.trim())
  const valid = draft.id.trim() !== '' && draft.statement.trim() !== '' && !idTaken

  const save = async () => {
    setSaving(true)
    try {
      await api.upsertRule({ ...draft, id: draft.id.trim() })
      await onSaved()
      success(isNew ? '규칙이 추가되었습니다' : '규칙이 저장되었습니다')
      onClose()
    } catch (cause) {
      fromError(cause, '규칙을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={rule !== null}
      onClose={onClose}
      title={isNew ? '세계관 규칙 추가' : `규칙 #${rule?.id} 수정`}
      description="반드시 지켜져야 할 원칙 1개와 예외가 허용되는 조항을 정의합니다."
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!valid}>
            {isNew ? '규칙 추가' : '저장'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="식별자 (ID)"
            value={draft.id}
            disabled={!isNew}
            onChange={(event) => setDraft({ ...draft, id: event.target.value })}
            placeholder="예: mana-cost"
            hint={
              idTaken
                ? '이미 존재하는 ID입니다.'
                : isNew
                  ? '짧은 영문 슬러그. 검증기가 규칙을 인용할 때 사용합니다.'
                  : 'ID는 한 번 설정되면 변경할 수 없습니다.'
            }
          />
          <SelectField
            label="분류 (카테고리)"
            value={draft.category}
            onChange={(event) => setDraft({ ...draft, category: event.target.value })}
            options={[
              ...(RULE_CATEGORIES.includes(draft.category as (typeof RULE_CATEGORIES)[number])
                ? []
                : [{ value: draft.category, label: draft.category }]),
              ...RULE_CATEGORIES.map((category) => ({
                value: category,
                label: RULE_CATEGORY_LABELS[category] ?? category,
              })),
            ]}
          />
        </div>

        <TextArea
          label="규칙 명제 (원칙)"
          rows={3}
          value={draft.statement}
          onChange={(event) => setDraft({ ...draft, statement: event.target.value })}
          placeholder="예: 마법으로 죽은 사람을 되살릴 수 없다."
          hint="단정문 형태로 명확히 작성하세요. 검증기가 문장을 문자 그대로 비교 검증합니다."
        />

        <TagInput
          label="예외 조항"
          values={draft.exceptions}
          onChange={(exceptions) => setDraft({ ...draft, exceptions })}
          hint="이 규칙이 예외적으로 적용되지 않는 특수한 경우들을 적어주세요. 예외가 없다면 비워둡니다."
          placeholder="예외 조항 입력 후 Enter"
        />
      </div>
    </Modal>
  )
}

// ==========================================================================
// Locations
// ==========================================================================

/** "The Great Hall" -> "the-great-hall". Non-Latin names keep their own characters. */
function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^\p{L}\p{N}-]/gu, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
}

const BLANK_LOCATION: Location = {
  id: '',
  name: '',
  description: '',
  parent_location_id: null,
  notable_features: [],
}

/** `(depth, location)` pairs, parents before their children — the tree, flattened. */
function buildTree(locations: Location[]): { depth: number; location: Location }[] {
  const known = new Set(locations.map((location) => location.id))
  const byParent = new Map<string | null, Location[]>()
  for (const location of locations) {
    // A parent outside this world is no parent at all: show it at the root.
    const parent =
      location.parent_location_id && known.has(location.parent_location_id)
        ? location.parent_location_id
        : null
    byParent.set(parent, [...(byParent.get(parent) ?? []), location])
  }

  const ordered: { depth: number; location: Location }[] = []
  const seen = new Set<string>()

  const walk = (parent: string | null, depth: number) => {
    for (const location of byParent.get(parent) ?? []) {
      if (seen.has(location.id)) continue // a cycle in the hierarchy
      seen.add(location.id)
      ordered.push({ depth, location })
      walk(location.id, depth + 1)
    }
  }
  walk(null, 0)

  // Anything stranded in a cycle still deserves to be listed.
  for (const location of locations) {
    if (!seen.has(location.id)) ordered.push({ depth: 0, location })
  }
  return ordered
}

function LocationsTab({
  locations,
  onChanged,
}: {
  locations: Location[]
  onChanged: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [editing, setEditing] = useState<Location | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [deleting, setDeleting] = useState<Location | null>(null)

  const tree = useMemo(() => buildTree(locations), [locations])
  const childCount = useMemo(() => {
    const counts = new Map<string, number>()
    for (const location of locations) {
      const parent = location.parent_location_id
      if (parent) counts.set(parent, (counts.get(parent) ?? 0) + 1)
    }
    return counts
  }, [locations])

  const remove = async (location: Location) => {
    try {
      await api.deleteLocation(location.id)
      await onChanged()
      const orphans = childCount.get(location.id) ?? 0
      success(
        orphans > 0
          ? `"${location.name}" 삭제 완료 — 하위 장소 ${orphans}개는 최상위 장소로 이동되었습니다`
          : `"${location.name}" 삭제 완료`,
      )
    } catch (cause) {
      fromError(cause, '장소를 삭제하지 못했습니다.')
    }
  }

  return (
    <>
      <Panel
        title="이야기가 펼쳐지는 장소"
        description="상위 장소와 하위 장소를 계층 구조로 배치할 수 있습니다 (예: 대륙 > 왕국 > 수도 > 마법 아카데미)."
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditing(BLANK_LOCATION)
              setIsNew(true)
            }}
          >
            장소 추가
          </Button>
        }
      >
        {locations.length === 0 ? (
          <EmptyState
            icon={MapPin}
            title="등록된 장소가 없습니다"
            description="장면에서 장소를 지정하면, 작가 AI가 해당 장소의 묘사와 특징을 본문에 생생하게 반영합니다."
          />
        ) : (
          <div className="space-y-1.5">
            {tree.map(({ depth, location }) => (
              <div
                key={location.id}
                className="group flex items-start gap-2 rounded-xl border border-line bg-surface py-2.5 pr-3 transition-colors hover:border-line-strong"
                // Indentation carries the hierarchy, so it is a real inset
                // rather than a margin that would break the hover target.
                style={{ paddingLeft: `${0.875 + depth * 1.375}rem` }}
              >
                {depth > 0 && (
                  <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-ink-muted" aria-hidden />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        'text-sm font-medium text-ink',
                        depth === 0 && 'tracking-tight',
                      )}
                    >
                      {location.name || '(이름 없음)'}
                    </span>
                    <Badge mono>#{location.id}</Badge>
                    {(childCount.get(location.id) ?? 0) > 0 && (
                      <Badge tone="accent">{childCount.get(location.id)}개 하위 장소</Badge>
                    )}
                  </div>
                  {location.description && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-muted">
                      {location.description}
                    </p>
                  )}
                  {location.notable_features.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {location.notable_features.map((feature, index) => (
                        <Badge key={index}>{feature}</Badge>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <IconButton
                    icon={Plus}
                    title={`${location.name} 내부에 새 하위 장소 추가`}
                    onClick={() => {
                      setEditing({ ...BLANK_LOCATION, parent_location_id: location.id })
                      setIsNew(true)
                    }}
                  />
                  <IconButton
                    icon={Pencil}
                    title={`${location.name} 수정`}
                    onClick={() => {
                      setEditing(location)
                      setIsNew(false)
                    }}
                  />
                  <IconButton
                    icon={Trash2}
                    title={`${location.name} 삭제`}
                    onClick={() => setDeleting(location)}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <LocationModal
        location={editing}
        isNew={isNew}
        locations={locations}
        onClose={() => setEditing(null)}
        onSaved={onChanged}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title={`${deleting?.name} 장소를 삭제하시겠습니까?`}
        message={
          (childCount.get(deleting?.id ?? '') ?? 0) > 0 ? (
            <>
              하위 장소 {childCount.get(deleting?.id ?? '')}개가 이 장소 안에 포함되어 있습니다.
              하위 장소들은 삭제되지 않고 최상위 장소로 이동되며, 나중에 다시 상위 장소를 지정할 수 있습니다.
            </>
          ) : (
            '이 장소가 언급된 기존 장면들의 본문은 그대로 보존됩니다.'
          )
        }
      />
    </>
  )
}

function LocationModal({
  location,
  isNew,
  locations,
  onClose,
  onSaved,
}: {
  location: Location | null
  isNew: boolean
  locations: Location[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState<Location>(location ?? BLANK_LOCATION)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (location) setDraft(location)
  }, [location])

  /** Everything that may be a parent: not itself, and not its own descendants. */
  const parentOptions = useMemo(() => {
    const banned = new Set<string>()
    if (!isNew && draft.id) {
      banned.add(draft.id)
      let grew = true
      while (grew) {
        grew = false
        for (const candidate of locations) {
          if (
            candidate.parent_location_id &&
            banned.has(candidate.parent_location_id) &&
            !banned.has(candidate.id)
          ) {
            banned.add(candidate.id)
            grew = true
          }
        }
      }
    }
    return [
      { value: '', label: '— 최상위 장소 (루트) —' },
      ...locations
        .filter((candidate) => !banned.has(candidate.id))
        .map((candidate) => ({ value: candidate.id, label: candidate.name || candidate.id })),
    ]
  }, [locations, draft.id, isNew])

  const idTaken = isNew && locations.some((existing) => existing.id === draft.id.trim())
  const valid = draft.id.trim() !== '' && draft.name.trim() !== '' && !idTaken

  const save = async () => {
    setSaving(true)
    try {
      await api.upsertLocation({ ...draft, id: draft.id.trim() })
      await onSaved()
      success(isNew ? '장소가 추가되었습니다' : '장소가 저장되었습니다')
      onClose()
    } catch (cause) {
      fromError(cause, '장소를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={location !== null}
      onClose={onClose}
      title={isNew ? '장소 추가' : `${location?.name} 편집`}
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!valid}>
            {isNew ? '장소 추가' : '저장'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="장소 이름"
            value={draft.name}
            onChange={(event) => {
              const name = event.target.value
              setDraft((previous) => ({
                ...previous,
                name,
                // A new location's id follows the name until it is set by hand,
                // so the common case needs no thought and the rare one still works.
                id: isNew && previous.id === slugify(previous.name) ? slugify(name) : previous.id,
              }))
            }}
            placeholder="예: 호그와트 대연회장"
          />
          <TextField
            label="장소 식별자 (ID)"
            value={draft.id}
            disabled={!isNew}
            onChange={(event) => setDraft({ ...draft, id: event.target.value })}
            placeholder="great-hall"
            hint={idTaken ? '이미 존재하는 장소 ID입니다.' : undefined}
          />
        </div>

        <SelectField
          label="상위 장소 (소속)"
          value={draft.parent_location_id ?? ''}
          onChange={(event) =>
            setDraft({ ...draft, parent_location_id: event.target.value || null })
          }
          options={parentOptions}
          hint="장소는 자기 자신이나 자신의 하위 장소 안으로 들어갈 수 없습니다."
        />

        <TextArea
          label="장소 묘사"
          rows={4}
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          placeholder="시각, 청각, 냄새, 분위기 등 이 장소의 구체적인 인상과 묘사를 적어주세요."
          hint="작가 AI가 장면에 생동감 있는 배경 묘사를 구성할 때 참고합니다."
        />

        <TagInput
          label="주요 특징 / 랜드마크"
          values={draft.notable_features}
          onChange={(notable_features) => setDraft({ ...draft, notable_features })}
          placeholder="특징 입력 후 Enter"
        />
      </div>
    </Modal>
  )
}
