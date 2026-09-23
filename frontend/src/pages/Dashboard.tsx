/**
 * 🏠 Dashboard — where the story stands, and the next thing to do about it.
 */

import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  Lightbulb,
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
          {project.name || '제목 없는 이야기'}
        </h2>
        <p className="mt-1 text-sm text-ink-dim">
          {project.world.overview.trim()
            ? [project.world.genre, project.world.tone].filter(Boolean).join(' · ')
            : '아직 아무것도 정해지지 않았습니다.'}
        </p>
      </div>

      {/* An empty project has one useful next step, and it is not a form. */}
      {!project.world.overview.trim() && project.characters.length === 0 && (
        <Panel
          title="무엇을 쓸지부터 정해 보세요"
          description="어떤 소설인지 아직 정하지 않으셨다면, AI와 함께 컨셉부터 잡을 수 있습니다. 제안을 받고, 하나를 골라, 만족할 때까지 다듬으면 세계관과 인물과 회차 구상이 한 번에 만들어집니다."
        >
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={Lightbulb} onClick={() => navigate('/concept')}>
              작품 기획 시작하기
            </Button>
            <Button icon={BookOpen} onClick={() => navigate('/world')}>
              이미 구상이 있습니다 — 직접 적을게요
            </Button>
          </div>
        </Panel>
      )}

      {/* --- The numbers --- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Panel className="flex items-center gap-4">
          <ProgressRing
            completed={stats.episodes_completed}
            total={stats.episodes_total}
          />
          <div className="min-w-0">
            <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">집필 회차</p>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-ink tabular-nums">
              {stats.episodes_completed}
              <span className="text-base font-normal text-ink-muted">/{stats.episodes_total}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">{stats.episodes_queued}화 대기 중</p>
          </div>
        </Panel>

        <Stat icon={FileText} label="총 글자 수" value={formatCount(stats.total_words)} />
        <Stat icon={Users} label="등장인물" value={`${stats.character_count}명`} />
        <Stat
          icon={Spline}
          label="진행 중인 떡밥"
          value={stats.memory_available ? `${stats.open_thread_count}개` : '—'}
          hint={stats.memory_available ? '아직 회수되지 않은 복선' : '메모리 비활성화'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* --- Quick actions --- */}
        <Panel title="빠른 작업" description="지금 바로 진행할 수 있는 추천 작업입니다.">
          <div className="space-y-2">
            <Action
              icon={Sparkles}
              primary
              title={
                nextQueued
                  ? `제 ${nextQueued.episode_number}화 생성하기`
                  : '생성 대기 중인 회차가 없습니다'
              }
              detail={nextQueued?.title || nextQueued?.author_storyline || undefined}
              disabled={!nextQueued}
              onClick={() => navigate('/episodes')}
            />
            <Action
              icon={Plus}
              title="새 에피소드 줄거리 추가하기"
              detail="대략적인 줄거리만 적어도 감독 에이전트가 씬을 쪼개고 살을 붙입니다."
              onClick={() => navigate('/episodes')}
            />
            <Action
              icon={Users}
              title="캐릭터 워크숍 열기"
              detail={`현재 등장인물 ${stats.character_count}명 등록됨`}
              onClick={() => navigate('/characters')}
            />
          </div>
        </Panel>

        {/* --- Recent chapters --- */}
        <Panel title="최근 작성된 회차" description="가장 최근 완성된 3개 회차입니다.">
          {recent.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              title="아직 작성된 회차가 없습니다"
              description="에피소드 큐에서 줄거리를 추가하고 첫 번째 회차를 생성해 보세요."
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
        <Panel title="메모리 / 기억 저장소">
          {stats.memory_available ? (
            <p className="text-sm text-ink-dim">
              정상 작동 중입니다. <span className="font-medium text-ink">떡밥 {stats.open_thread_count}개</span>가
              추적되고 있으며, 새로운 회차 생성 시 이전 사건들을 유기적으로 참조합니다.
            </p>
          ) : (
            <p className="text-sm text-ink-dim">
              비활성화됨 — {stats.memory_error || 'ChromaDB가 시작되지 않았습니다'}.
            </p>
          )}
        </Panel>

        <Panel title="AI 모델">
          <p className="font-mono text-sm text-ink-dim">{health?.model ?? '—'}</p>
          {health && !health.api_key_configured && (
            <p className="mt-2 text-sm text-warn-bright">
              GOOGLE_API_KEY가 설정되지 않아 생성이 실패할 수 있습니다.
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
          백엔드 서버에 연결할 수 없습니다
        </h2>
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-ink-dim">{message}</p>
      </div>
      <code className="rounded-lg border border-line bg-surface px-3 py-2 font-mono text-xs text-ink-dim">
        .venv\Scripts\uvicorn.exe storyweaver.server:app --reload --port 8001
      </code>
      <Button variant="primary" onClick={onRetry}>
        다시 시도
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
          {episode.episode_number}화. {episode.title || '(제목 없음)'}
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
          {formatCount(episode.final_text.split(/\s+/).filter(Boolean).length)}자
          <span aria-hidden>·</span>
          씬 {episode.scenes.length}개
        </span>
      </span>
      <Badge tone="good">본문 읽기</Badge>
    </button>
  )
}
