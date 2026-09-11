/**
 * 🧠 Memory Inspector — what the story remembers, and what it still owes.
 *
 * Two different questions, so two tabs: the 떡밥 ledger (exact, structured,
 * and the thing that decides whether a serial holds together), and semantic
 * search over the vector store (fuzzy, and the thing that tells you what the
 * agents will actually be handed next episode).
 */

import {
  AlertTriangle,
  Brain,
  Check,
  Database,
  Search,
  Spline,
  Users,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  EmptyState,
  PageHeader,
  Panel,
  SelectField,
  Tabs,
  TextField,
} from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { MemoryHit, MemoryStatus, PlotThread, PlotThreads } from '@/types/storyweaver'

type TabId = 'threads' | 'search'

export function MemoryInspector() {
  const { project } = useProject()
  const { fromError } = useToast()

  const [tab, setTab] = useState<TabId>('threads')
  const [status, setStatus] = useState<MemoryStatus | null>(null)
  const [threads, setThreads] = useState<PlotThreads | null>(null)

  const latestEpisode = useMemo(
    () =>
      Math.max(
        0,
        ...(project?.episodes ?? [])
          .filter((episode) => episode.status === 'completed')
          .map((episode) => episode.episode_number),
      ),
    [project],
  )

  useEffect(() => {
    void api
      .getMemoryStatus()
      .then(setStatus)
      .catch((cause) => fromError(cause, '메모리 계층에 접근하지 못했습니다.'))
  }, [fromError])

  useEffect(() => {
    if (!status?.available) return
    void api
      .getPlotThreads(latestEpisode || undefined)
      .then(setThreads)
      .catch((cause) => fromError(cause, '복선(떡밥) 목록을 불러오지 못했습니다.'))
  }, [status?.available, latestEpisode, fromError])

  if (status && !status.available) {
    return (
      <>
        <PageHeader title="메모리 인스펙터" />
        <Panel>
          <EmptyState
            icon={Database}
            title="메모리 계층이 시작되지 않았습니다"
            description={
              status.error ||
              'ChromaDB를 사용할 수 없습니다. 다른 기능은 정상 작동하지만, 회차 간 장기 기억이 연동되지 않습니다.'
            }
          />
        </Panel>
      </>
    )
  }

  const stored = status
    ? Object.values(status.collections).reduce((total, n) => total + n, 0)
    : 0

  return (
    <>
      <PageHeader
        title="메모리 인스펙터"
        description="이전 에피소드들이 기억하고 있는 설정과 복선(떡밥), 그리고 다음 회차 생성 시 AI에게 전달될 메모리를 조회합니다."
        actions={
          status && (
            <div className="flex items-center gap-2">
              <Badge tone="good">{formatCount(stored)}개 기억 저장됨</Badge>
            </div>
          )
        }
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          {
            id: 'threads',
            label: '복선 / 떡밥 장부',
            icon: Spline,
            count: threads?.active.length,
          },
          { id: 'search', label: '시맨틱 검색', icon: Search },
        ]}
      />

      {tab === 'threads' && (
        <ThreadBoard
          threads={threads}
          latestEpisode={latestEpisode}
          loading={threads === null}
        />
      )}
      {tab === 'search' && <SearchPlayground />}
    </>
  )
}

// ==========================================================================
// Plot threads
// ==========================================================================

function ThreadBoard({
  threads,
  latestEpisode,
  loading,
}: {
  threads: PlotThreads | null
  latestEpisode: number
  loading: boolean
}) {
  if (loading) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="sw-panel h-64 animate-pulse-soft" />
        <div className="sw-panel h-64 animate-pulse-soft" />
      </div>
    )
  }
  if (!threads) return null

  const staleIds = new Set(threads.stale.map((thread) => thread.id))

  if (threads.active.length === 0 && threads.resolved.length === 0) {
    return (
      <Panel>
        <EmptyState
          icon={Spline}
          title="등록된 복선(떡밥)이 없습니다"
          description="에피소드 요약 생성 시 회차에서 던져진 미해결 질문이나 떡밥이 자동으로 감지되어 이곳에 기록됩니다. 회차를 집필하면 자동으로 나타납니다."
        />
      </Panel>
    )
  }

  return (
    <>
      {threads.stale.length > 0 && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-warn/25 bg-warn/8 px-4 py-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn-bright" aria-hidden />
          <p className="text-xs leading-relaxed text-ink-dim">
            {threads.stale.length}개의 복선(떡밥)이 {threads.stale_after_episodes}화 이상 언급되지 않았습니다.
            독자는 너무 오랫동안 언급되지 않은 복선을 회수되지 않은 맥거핀으로 여길 수 있습니다.
            디렉터 AI에게 이 사실이 전달되지만, 개요에서 의도적으로 이 떡밥을 다루어 주면 더욱 좋습니다.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Column
          title="미회수 떡밥 (Open)"
          description="작품 속에서 던져졌으나 아직 해결되지 않은 의문과 사건들입니다."
          tone="accent"
          threads={threads.active}
          staleIds={staleIds}
          latestEpisode={latestEpisode}
        />
        <Column
          title="회수 완료 (Resolved)"
          description="해결되었거나 의문이 풀려 더 이상 신경 쓰지 않아도 되는 떡밥들입니다."
          tone="good"
          threads={threads.resolved}
          staleIds={staleIds}
          latestEpisode={latestEpisode}
        />
      </div>
    </>
  )
}

function Column({
  title,
  description,
  tone,
  threads,
  staleIds,
  latestEpisode,
}: {
  title: string
  description: string
  tone: 'accent' | 'good'
  threads: PlotThread[]
  staleIds: Set<string>
  latestEpisode: number
}) {
  return (
    <Panel
      title={title}
      description={description}
      actions={<Badge tone={tone}>{threads.length}</Badge>}
    >
      {threads.length === 0 ? (
        <p className="py-6 text-center text-xs text-ink-muted">아직 항목이 없습니다.</p>
      ) : (
        <div className="space-y-2.5">
          {threads.map((thread) => (
            <ThreadCard
              key={thread.id}
              thread={thread}
              stale={staleIds.has(thread.id)}
              latestEpisode={latestEpisode}
            />
          ))}
        </div>
      )}
    </Panel>
  )
}

function ThreadCard({
  thread,
  stale,
  latestEpisode,
}: {
  thread: PlotThread
  stale: boolean
  latestEpisode: number
}) {
  const { project } = useProject()
  const nameOf = (id: string) =>
    project?.characters.find((character) => character.id === id)?.name ?? id

  const quietFor = Math.max(0, latestEpisode - thread.last_referenced_episode)
  const resolved = thread.status === 'resolved'

  return (
    <div
      className={cn(
        'rounded-xl border bg-surface px-4 py-3 transition-colors',
        stale ? 'border-warn/30' : 'border-line hover:border-line-strong',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h4 className="min-w-0 text-sm font-medium text-ink">{thread.name}</h4>
        <div className="flex shrink-0 items-center gap-1.5">
          {resolved ? (
            <Badge tone="good">
              <Check className="mr-0.5 inline size-3" />
              제{thread.resolved_in_episode}화에서 회수
            </Badge>
          ) : (
            <Badge tone={thread.status === 'progressing' ? 'accent' : 'neutral'}>
              {thread.status === 'progressing' ? '진행 중' : '미회수'}
            </Badge>
          )}
        </div>
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-ink-dim">{thread.description}</p>

      {resolved && thread.resolution && (
        <p className="mt-2 border-l-2 border-good/40 pl-2.5 text-xs leading-relaxed text-ink-muted">
          {thread.resolution}
        </p>
      )}

      {thread.events.length > 0 && !resolved && (
        <p className="mt-2 text-xs leading-relaxed text-ink-muted">
          <span className="text-ink-dim">최근 전개 — </span>
          {thread.events.at(-1)}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[0.68rem] text-ink-muted">
        <span>제{thread.opened_in_episode}화에서 시작</span>
        {!resolved && (
          <span className={cn(stale && 'font-medium text-warn-bright')}>
            {quietFor === 0
              ? '이번 회차에서 다뤄짐'
              : `${quietFor}화 동안 미언급`}
          </span>
        )}
        {thread.linked_characters.length > 0 && (
          <span className="flex items-center gap-1">
            <Users className="size-3" aria-hidden />
            {thread.linked_characters.map(nameOf).join(', ')}
          </span>
        )}
      </div>
    </div>
  )
}

// ==========================================================================
// Search
// ==========================================================================

const COLLECTION_LABELS: Record<string, string> = {
  episode_summaries: '에피소드 요약',
  interaction_records: '인물 상호작용',
  world_lore: '세계관 설정',
}

function SearchPlayground() {
  const { project } = useProject()
  const { fromError } = useToast()

  const [query, setQuery] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [results, setResults] = useState<MemoryHit[] | null>(null)
  const [searching, setSearching] = useState(false)

  const run = useCallback(async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const found = await api.searchMemory(query, {
        topK: 15,
        characterId: characterId || null,
      })
      setResults(found.results)
    } catch (cause) {
      fromError(cause, '검색에 실패했습니다.')
    } finally {
      setSearching(false)
    }
  }, [query, characterId, fromError])

  const nameOf = (id: string) =>
    project?.characters.find((character) => character.id === id)?.name ?? id

  return (
    <>
      <Panel
        title="시맨틱 검색 (Semantic Search)"
        description="AI 에이전트들이 정보를 회상할 때 사용하는 것과 동일한 벡터 검색입니다. 검색된 내용이 다음 회차 집필 시 AI에게 주어집니다."
      >
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="검색 질의어"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void run()
            }}
            placeholder="그들은 서로에게 무엇을 약속했는가?"
            className="min-w-64 flex-1"
          />
          <SelectField
            label="특정 인물 관련 기억만 필터링"
            value={characterId}
            onChange={(event) => setCharacterId(event.target.value)}
            options={[
              { value: '', label: '— 모든 등장인물 —' },
              ...(project?.characters ?? []).map((character) => ({
                value: character.id,
                label: character.name,
              })),
            ]}
            className="min-w-44"
          />
          <Button
            variant="primary"
            icon={Search}
            onClick={() => void run()}
            loading={searching}
            disabled={!query.trim()}
            className="mb-6"
          >
            검색
          </Button>
        </div>
      </Panel>

      <div className="mt-4">
        {results === null ? (
          <Panel>
            <EmptyState
              icon={Brain}
              title="무엇이든 질문해 보세요"
              description="다음 회차를 쓰기 전, AI가 작가의 의도대로 이전 사건을 실제로 기억하고 있는지 미리 확인할 수 있습니다."
            />
          </Panel>
        ) : results.length === 0 ? (
          <Panel>
            <EmptyState
              icon={Search}
              title="검색 결과가 없습니다"
              description="아직 소설에서 다뤄지지 않았거나, 저장된 표현과 질의어가 너무 다릅니다. 등장인물이 실제로 말했을 법한 단어로 검색해 보세요."
            />
          </Panel>
        ) : (
          <div className="space-y-2.5">
            {results.map((hit) => (
              <HitCard key={hit.id} hit={hit} nameOf={nameOf} />
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function HitCard({ hit, nameOf }: { hit: MemoryHit; nameOf: (id: string) => string }) {
  const participants = Array.isArray(hit.metadata.participants)
    ? (hit.metadata.participants as string[])
    : Array.isArray(hit.metadata.characters_involved)
      ? (hit.metadata.characters_involved as string[])
      : []
  const sceneNumber = hit.metadata.scene_number
  const relevance = hit.relevance ?? 0

  return (
    <div className="sw-panel px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="accent">
            {COLLECTION_LABELS[hit.collection] ?? hit.collection}
          </Badge>
          {hit.episode_number > 0 && <Badge>제{hit.episode_number}화</Badge>}
          {typeof sceneNumber === 'number' && <Badge>장면 {sceneNumber}</Badge>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {/* A bar, because a relevance is only meaningful next to the others. */}
          <span className="h-1 w-14 overflow-hidden rounded-full bg-line">
            <span
              className="block h-full rounded-full bg-accent"
              style={{ width: `${Math.round(relevance * 100)}%` }}
            />
          </span>
          <span className="font-mono text-[0.68rem] text-ink-muted tabular-nums">
            {relevance.toFixed(2)}
          </span>
        </div>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-ink-dim">{hit.document}</p>

      {participants.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <Users className="size-3 text-ink-muted" aria-hidden />
          {participants.map((id) => (
            <Badge key={id}>{nameOf(id)}</Badge>
          ))}
        </div>
      )}
    </div>
  )
}
