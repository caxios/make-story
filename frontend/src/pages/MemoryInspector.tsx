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
      .catch((cause) => fromError(cause, 'Could not reach the memory layer.'))
  }, [fromError])

  useEffect(() => {
    if (!status?.available) return
    void api
      .getPlotThreads(latestEpisode || undefined)
      .then(setThreads)
      .catch((cause) => fromError(cause, 'Could not load the plot threads.'))
  }, [status?.available, latestEpisode, fromError])

  if (status && !status.available) {
    return (
      <>
        <PageHeader title="Memory Inspector" />
        <Panel>
          <EmptyState
            icon={Database}
            title="The memory layer did not start"
            description={
              status.error ||
              'ChromaDB is unavailable. Everything else works; episodes just will not remember each other.'
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
        title="Memory Inspector"
        description="What earlier episodes established, and what they will hand the agents next time."
        actions={
          status && (
            <div className="flex items-center gap-2">
              <Badge tone="good">{formatCount(stored)} memories</Badge>
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
            label: 'Plot threads',
            icon: Spline,
            count: threads?.active.length,
          },
          { id: 'search', label: 'Search', icon: Search },
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
          title="No plot threads yet"
          description="The summarizer opens a thread whenever an episode raises a question it does not answer. Generate an episode and they will appear here."
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
            {threads.stale.length} thread{threads.stale.length === 1 ? ' has' : 's have'} gone
            quiet for {threads.stale_after_episodes} episodes or more. A reader starts to treat a
            thread that quiet as dropped — the Director is told about these, but an outline that
            touches one deliberately works better.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Column
          title="Open"
          description="Questions the story has raised and not yet paid off."
          tone="accent"
          threads={threads.active}
          staleIds={staleIds}
          latestEpisode={latestEpisode}
        />
        <Column
          title="Resolved"
          description="Paid off, and safe to stop worrying about."
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
        <p className="py-6 text-center text-xs text-ink-muted">Nothing here yet.</p>
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
              ep {thread.resolved_in_episode}
            </Badge>
          ) : (
            <Badge tone={thread.status === 'progressing' ? 'accent' : 'neutral'}>
              {thread.status}
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
          <span className="text-ink-dim">Most recently — </span>
          {thread.events.at(-1)}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[0.68rem] text-ink-muted">
        <span>opened in ep {thread.opened_in_episode}</span>
        {!resolved && (
          <span className={cn(stale && 'font-medium text-warn-bright')}>
            {quietFor === 0
              ? 'touched this episode'
              : `unmentioned for ${quietFor} episode${quietFor === 1 ? '' : 's'}`}
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
  episode_summaries: 'episode summary',
  interaction_records: 'interaction',
  world_lore: 'world lore',
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
      fromError(cause, 'The search failed.')
    } finally {
      setSearching(false)
    }
  }, [query, characterId, fromError])

  const nameOf = (id: string) =>
    project?.characters.find((character) => character.id === id)?.name ?? id

  return (
    <>
      <Panel
        title="Semantic search"
        description="The same retrieval the agents use. What comes back here is what they will be handed."
      >
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="Query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void run()
            }}
            placeholder="what did they promise each other?"
            className="min-w-64 flex-1"
          />
          <SelectField
            label="Only memories involving"
            value={characterId}
            onChange={(event) => setCharacterId(event.target.value)}
            options={[
              { value: '', label: '— anyone —' },
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
            Search
          </Button>
        </div>
      </Panel>

      <div className="mt-4">
        {results === null ? (
          <Panel>
            <EmptyState
              icon={Brain}
              title="Ask it something"
              description="Search is how you find out whether the story actually remembers what you think it does — before an episode relies on it."
            />
          </Panel>
        ) : results.length === 0 ? (
          <Panel>
            <EmptyState
              icon={Search}
              title="Nothing came back"
              description="Either the story has not established this yet, or the phrasing is far from how it was recorded. Try the words a character would have used."
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
          {hit.episode_number > 0 && <Badge>ep {hit.episode_number}</Badge>}
          {typeof sceneNumber === 'number' && <Badge>scene {sceneNumber}</Badge>}
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
