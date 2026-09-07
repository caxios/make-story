/**
 * 🏠 Dashboard — where the story stands, and the next thing to do about it.
 */

import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  Plus,
  Sparkles,
  Spline,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Badge, Button, EmptyState, Panel } from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { Episode } from '@/types/storyweaver'

export function Dashboard() {
  const { project, stats, health, loading, offline, refresh } = useProject()
  const navigate = useNavigate()

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="sw-panel h-28 animate-pulse-soft" />
        ))}
      </div>
    )
  }

  if (offline) return <Offline message={offline} onRetry={() => void refresh()} />
  if (!project || !stats) return null

  const nextQueued = project.episodes.find((episode) => episode.status === 'queued')
  const recent = [...project.episodes]
    .filter((episode) => episode.status === 'completed')
    .sort((a, b) => b.episode_number - a.episode_number)
    .slice(0, 3)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-ink">
          {project.name || 'Untitled Story'}
        </h2>
        <p className="mt-1 text-sm text-ink-dim">
          {project.world.overview.trim()
            ? [project.world.genre, project.world.tone].filter(Boolean).join(' · ')
            : 'No world yet — start in World Builder.'}
        </p>
      </div>

      {/* --- The numbers --- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Panel className="flex items-center gap-4">
          <ProgressRing
            completed={stats.episodes_completed}
            total={stats.episodes_total}
          />
          <div className="min-w-0">
            <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">Episodes</p>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-ink tabular-nums">
              {stats.episodes_completed}
              <span className="text-base font-normal text-ink-muted">/{stats.episodes_total}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">{stats.episodes_queued} queued</p>
          </div>
        </Panel>

        <Stat icon={FileText} label="Words" value={formatCount(stats.total_words)} />
        <Stat icon={Users} label="Cast" value={stats.character_count} />
        <Stat
          icon={Spline}
          label="Open threads"
          value={stats.memory_available ? stats.open_thread_count : '—'}
          hint={stats.memory_available ? '떡밥 still unresolved' : 'Memory unavailable'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* --- Quick actions --- */}
        <Panel title="Next" description="The obvious things to do from here.">
          <div className="space-y-2">
            <Action
              icon={Sparkles}
              primary
              title={
                nextQueued
                  ? `Generate episode ${nextQueued.episode_number}`
                  : 'Nothing queued to generate'
              }
              detail={nextQueued?.title || nextQueued?.author_storyline || undefined}
              disabled={!nextQueued}
              onClick={() => navigate('/episodes')}
            />
            <Action
              icon={Plus}
              title="Add an episode outline"
              detail="A rough paragraph is enough — the Director fills in the rest."
              onClick={() => navigate('/episodes')}
            />
            <Action
              icon={Users}
              title="Open the Character Workshop"
              detail={`${stats.character_count} character${stats.character_count === 1 ? '' : 's'} in the cast`}
              onClick={() => navigate('/characters')}
            />
          </div>
        </Panel>

        {/* --- Recent chapters --- */}
        <Panel title="Recently written" description="The last three finished chapters.">
          {recent.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              title="Nothing written yet"
              description="Queue an outline and generate it, and the chapter will show up here."
            />
          ) : (
            <div className="space-y-2">
              {recent.map((episode) => (
                <RecentEpisode
                  key={episode.episode_number}
                  episode={episode}
                  onOpen={() => navigate('/reading')}
                />
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* --- Health --- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Memory">
          {stats.memory_available ? (
            <p className="text-sm text-ink-dim">
              Running, with <span className="font-medium text-ink">{stats.open_thread_count}</span>{' '}
              open plot thread{stats.open_thread_count === 1 ? '' : 's'}. Episodes can refer back to
              what earlier ones established.
            </p>
          ) : (
            <p className="text-sm text-ink-dim">
              Unavailable — {stats.memory_error || 'ChromaDB did not start'}. Everything else works;
              episodes just will not remember each other.
            </p>
          )}
        </Panel>

        <Panel title="Model">
          <p className="font-mono text-sm text-ink-dim">{health?.model ?? '—'}</p>
          {health && !health.api_key_configured && (
            <p className="mt-2 text-sm text-warn-bright">
              GOOGLE_API_KEY is unset, so generation will fail until it is filled in.
            </p>
          )}
        </Panel>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------

function Offline({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="sw-panel flex flex-col items-center gap-4 px-6 py-16 text-center">
      <div className="grid size-12 place-items-center rounded-2xl border border-bad/30 bg-bad/10">
        <AlertTriangle className="size-5.5 text-bad-bright" />
      </div>
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-ink">
          The backend is not answering
        </h2>
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-ink-dim">{message}</p>
      </div>
      <code className="rounded-lg border border-line bg-surface px-3 py-2 font-mono text-xs text-ink-dim">
        uvicorn storyweaver.server:app --reload --port 8000
      </code>
      <Button variant="primary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/** How much of the queue is written, as a ring rather than another number. */
function ProgressRing({ completed, total }: { completed: number; total: number }) {
  const fraction = total === 0 ? 0 : completed / total
  const radius = 22
  const circumference = 2 * Math.PI * radius

  return (
    <svg width="56" height="56" viewBox="0 0 56 56" className="shrink-0 -rotate-90">
      <circle
        cx="28"
        cy="28"
        r={radius}
        fill="none"
        stroke="var(--color-line)"
        strokeWidth="4"
      />
      <circle
        cx="28"
        cy="28"
        r={radius}
        fill="none"
        stroke="var(--color-good)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - fraction)}
        className="transition-[stroke-dashoffset] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
      />
    </svg>
  )
}

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: LucideIcon
  label: string
  value: string | number
  hint?: string
}) {
  return (
    <Panel className="transition-colors hover:border-line-strong">
      <div className="flex items-center gap-2 text-ink-muted">
        <Icon className="size-4" />
        <span className="text-xs font-medium tracking-wide uppercase">{label}</span>
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-ink tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}
    </Panel>
  )
}

function Action({
  icon: Icon,
  title,
  detail,
  onClick,
  disabled,
  primary,
}: {
  icon: LucideIcon
  title: string
  detail?: string
  onClick: () => void
  disabled?: boolean
  primary?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        primary
          ? 'border-accent/30 bg-accent/8 hover:not-disabled:bg-accent/14'
          : 'border-line bg-surface hover:not-disabled:border-line-strong',
      )}
    >
      <Icon className={cn('size-4.5 shrink-0', primary ? 'text-accent-bright' : 'text-ink-muted')} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-ink">{title}</span>
        {detail && <span className="mt-0.5 block truncate text-xs text-ink-muted">{detail}</span>}
      </span>
    </button>
  )
}

function RecentEpisode({ episode, onOpen }: { episode: Episode; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:border-line-strong"
    >
      <CheckCircle2 className="size-4 shrink-0 text-good" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-ink">
          {episode.episode_number}. {episode.title || '(untitled)'}
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
          {formatCount(episode.final_text.split(/\s+/).filter(Boolean).length)} words
          <span aria-hidden>·</span>
          {episode.scenes.length} scene{episode.scenes.length === 1 ? '' : 's'}
        </span>
      </span>
      <Badge tone="good">Read</Badge>
    </button>
  )
}
