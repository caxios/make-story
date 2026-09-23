import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/AppLayout'
import { ToastProvider } from '@/components/ToastContext'
import { CharacterWorkshop } from '@/pages/CharacterWorkshop'
import { ConceptStudio } from '@/pages/ConceptStudio'
import { Dashboard } from '@/pages/Dashboard'
import { EpisodeQueue } from '@/pages/EpisodeQueue'
import { MemoryInspector } from '@/pages/MemoryInspector'
import { ReadingRoom } from '@/pages/ReadingRoom'
import { Settings } from '@/pages/Settings'
import { StoryPlanner } from '@/pages/StoryPlanner'
import { Wiki } from '@/pages/Wiki'
import { WikiSubject } from '@/pages/WikiSubject'
import { WorldBuilder } from '@/pages/WorldBuilder'
import { ProjectProvider } from '@/state/ProjectContext'

export default function App() {
  return (
    <ToastProvider>
      <ProjectProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="concept" element={<ConceptStudio />} />
              <Route path="world" element={<WorldBuilder />} />
              <Route path="characters" element={<CharacterWorkshop />} />
              <Route path="planner" element={<StoryPlanner />} />
              <Route path="episodes" element={<EpisodeQueue />} />
              <Route path="reading" element={<ReadingRoom />} />
              <Route path="wiki" element={<Wiki />} />
              <Route path="wiki/:subjectType/:subjectId" element={<WikiSubject />} />
              <Route path="memory" element={<MemoryInspector />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ProjectProvider>
    </ToastProvider>
  )
}
