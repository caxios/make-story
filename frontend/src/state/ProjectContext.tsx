/**
 * The project, loaded once and shared by every page.
 *
 * The backend is the single source of truth — it reads and writes
 * `data/project.json` on every request — so this holds no optimistic copy.
 * A page that changes something calls the API and then `refresh()`.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import type { Health, Project, ProjectStats } from '@/types/storyweaver'

interface ProjectContextValue {
  project: Project | null
  stats: ProjectStats | null
  health: Health | null
  /** True only on the very first load, so the shell can show a splash once. */
  loading: boolean
  /** Set when the backend could not be reached at all. */
  offline: string
  refresh: () => Promise<void>
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { fromError } = useToast()
  const [project, setProject] = useState<Project | null>(null)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [loading, setLoading] = useState(true)
  const [offline, setOffline] = useState('')

  const load = useCallback(
    async (announce: boolean) => {
      try {
        const [nextProject, nextStats, nextHealth] = await Promise.all([
          api.getProject(),
          api.getStats(),
          api.getHealth(),
        ])
        setProject(nextProject)
        setStats(nextStats)
        setHealth(nextHealth)
        setOffline('')
      } catch (cause) {
        // A backend that is simply not running is the common case in dev, and
        // it deserves the shell's own empty state rather than a toast per page.
        const message =
          cause instanceof api.ApiError && cause.status === 0
            ? cause.detail
            : 'Could not load the project.'
        setOffline(message)
        if (announce) fromError(cause, message)
      } finally {
        setLoading(false)
      }
    },
    [fromError],
  )

  useEffect(() => {
    void load(false)
  }, [load])

  const value = useMemo<ProjectContextValue>(
    () => ({
      project,
      stats,
      health,
      loading,
      offline,
      refresh: () => load(true),
    }),
    [project, stats, health, loading, offline, load],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext)
  if (!value) throw new Error('useProject must be used inside a <ProjectProvider>')
  return value
}
