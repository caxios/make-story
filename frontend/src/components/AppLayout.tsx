/**
 * The shell: a collapsible sidebar, a header that says where the story stands,
 * and the page itself.
 *
 * Collapsing is remembered per browser, because it is a working preference —
 * an author on a laptop keeps it shut and an author on a monitor keeps it open,
 * and neither wants to say so twice.
 */

import {
  BookOpen,
  Brain,
  ChevronLeft,
  ClipboardList,
  Feather,
  Home,
  ListOrdered,
  Menu,
  Settings,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

const NAV: NavItem[] = [
  { to: '/', label: '대시보드', icon: Home },
  { to: '/world', label: '세계관 빌더', icon: BookOpen },
  { to: '/characters', label: '캐릭터 워크숍', icon: Users },
  { to: '/planner', label: '스토리 플래너', icon: ClipboardList },
  { to: '/episodes', label: '에피소드 큐', icon: ListOrdered },
  { to: '/reading', label: '리딩룸 (본문 열람)', icon: Feather },
  { to: '/memory', label: '메모리 인스펙터', icon: Brain },
  { to: '/settings', label: '설정', icon: Settings },
]

const COLLAPSED_KEY = 'storyweaver.sidebar.collapsed'

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSED_KEY) === 'true',
  )
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, String(collapsed))
  }, [collapsed])

  return (
    <div className="flex min-h-screen bg-canvas">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenMobile={() => setMobileOpen(true)} />
        <main className="flex-1 px-5 py-6 sm:px-8 sm:py-8">
          <div className="animate-fade mx-auto w-full max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Sidebar
// --------------------------------------------------------------------------

function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onCloseMobile,
}: {
  collapsed: boolean
  onToggle: () => void
  mobileOpen: boolean
  onCloseMobile: () => void
}) {
  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="네비게이션 닫기"
          onClick={onCloseMobile}
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex flex-col border-r border-line bg-surface',
          'transition-[width,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
          'lg:sticky lg:top-0 lg:h-screen lg:translate-x-0',
          collapsed ? 'w-[4.5rem]' : 'w-64',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center gap-2.5 px-4">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-accent to-violet shadow-lg shadow-accent/25">
            <Feather className="size-4.5 text-white" />
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold tracking-tight text-ink">
                StoryWeaver
              </p>
              <p className="truncate text-[0.7rem] text-ink-muted">소설 창작 스튜디오</p>
            </div>
          )}
          <button
            type="button"
            onClick={onCloseMobile}
            className="rounded-lg p-1.5 text-ink-muted hover:bg-white/5 hover:text-ink lg:hidden"
            aria-label="네비게이션 닫기"
          >
            <X className="size-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={collapsed ? label : undefined}
              // On a phone the drawer that was navigated from should close.
              onClick={onCloseMobile}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium',
                  'transition-colors duration-150',
                  collapsed && 'justify-center px-0',
                  isActive
                    ? 'bg-accent/12 text-ink'
                    : 'text-ink-dim hover:bg-white/4 hover:text-ink',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {/* The active marker is a shape as well as a colour, so the
                      current page is legible without relying on hue. */}
                  <span
                    className={cn(
                      'absolute left-0 h-5 w-0.5 rounded-r-full bg-accent-bright transition-opacity',
                      isActive ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                  <Icon
                    className={cn(
                      'size-4.5 shrink-0 transition-colors',
                      isActive ? 'text-accent-bright' : 'text-ink-muted group-hover:text-ink-dim',
                    )}
                  />
                  {!collapsed && <span className="truncate">{label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'hidden w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-muted',
              'transition-colors hover:bg-white/4 hover:text-ink lg:flex',
              collapsed && 'justify-center px-0',
            )}
            aria-label={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
          >
            <ChevronLeft
              className={cn('size-4.5 transition-transform duration-300', collapsed && 'rotate-180')}
            />
            {!collapsed && <span>사이드바 접기</span>}
          </button>
        </div>
      </aside>
    </>
  )
}

// --------------------------------------------------------------------------
// Header
// --------------------------------------------------------------------------

function Header({ onOpenMobile }: { onOpenMobile: () => void }) {
  const { project, stats, health, offline } = useProject()

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-canvas/85 px-5 backdrop-blur-xl sm:px-8">
      <button
        type="button"
        onClick={onOpenMobile}
        className="-ml-1 rounded-lg p-2 text-ink-dim hover:bg-white/5 hover:text-ink lg:hidden"
        aria-label="네비게이션 열기"
      >
        <Menu className="size-5" />
      </button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[0.95rem] font-semibold tracking-tight text-ink">
          {project?.name || '제목 없는 이야기'}
        </h1>
        {project?.world.title && (
          <p className="truncate text-xs text-ink-muted">{project.world.title}</p>
        )}
      </div>

      <div className="flex items-center gap-2">
        {stats && (
          <>
            <Pill tone="good" label={`${stats.episodes_completed}화 집필 완료`} />
            <Pill tone="neutral" label={`${stats.episodes_queued}화 대기 중`} hideBelowSm />
            <Pill
              tone="neutral"
              label={`총 ${formatCount(stats.total_words)}자`}
              hideBelowSm
            />
            {stats.open_thread_count > 0 && (
              <Pill tone="accent" label={`진행 중 떡밥 ${stats.open_thread_count}개`} hideBelowSm />
            )}
          </>
        )}
        <StatusDot offline={offline} health={health} />
      </div>
    </header>
  )
}

function Pill({
  label,
  tone,
  hideBelowSm,
}: {
  label: string
  tone: 'good' | 'accent' | 'neutral'
  hideBelowSm?: boolean
}) {
  return (
    <span
      className={cn(
        'rounded-full border px-2.5 py-1 text-[0.7rem] font-medium whitespace-nowrap',
        hideBelowSm && 'hidden sm:inline-block',
        tone === 'good' && 'border-good/30 bg-good/10 text-good-bright',
        tone === 'accent' && 'border-accent/30 bg-accent/10 text-accent-bright',
        tone === 'neutral' && 'border-line-strong bg-white/3 text-ink-dim',
      )}
    >
      {label}
    </span>
  )
}

/** Whether the backend is up, and whether it can actually write anything. */
function StatusDot({ offline, health }: { offline: string; health: import('@/types/storyweaver').Health | null }) {
  const [tone, title] = offline
    ? (['bad', offline] as const)
    : !health
      ? (['neutral', 'Connecting to the backend…'] as const)
      : !health.api_key_configured
        ? (['warn', 'Connected, but GOOGLE_API_KEY is unset — generation will fail'] as const)
        : health.memory_available
          ? (['good', `Connected · ${health.model} · memory on`] as const)
          : (['warn', `Connected · ${health.model} · memory unavailable`] as const)

  return (
    <span className="ml-1 flex items-center" title={title}>
      <span className="sr-only">{title}</span>
      <span
        aria-hidden
        className={cn(
          'size-2 rounded-full',
          tone === 'good' && 'bg-good',
          tone === 'warn' && 'bg-warn',
          tone === 'bad' && 'bg-bad animate-pulse-soft',
          tone === 'neutral' && 'bg-ink-muted animate-pulse-soft',
        )}
      />
    </span>
  )
}
