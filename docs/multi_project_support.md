# Implementation Specification: Multi-Project (Multi-Novel) Support

**Goal:** Enable StoryWeaver to manage and switch between multiple independent novels/stories simultaneously without overwriting data, by isolating storage and memory per project.

---

## 1. Overview & Architecture

Currently, StoryWeaver hardcodes all data storage to a single root directory:
- `data/project.json` (World lore, characters, episode queue, style)
- `data/state/` (Chronicle, character memories, plot threads, story memory)
- `data/chromadb/` (ChromaDB vector database collections)

Because agents are stateless functions that merely receive injected state (lore, sheets, recent summaries, memory items) in their prompt packets, multi-project support does NOT require rewriting agents or LLM prompts. 

We only need to:
1. **Isolate directories per project**: `data/projects/{project_id}/`
2. **Resolve project context in backend**: Inspect incoming `X-Project-Id` header (or query param) to inject the appropriate `ProjectStore` and `MemoryManager`.
3. **Add Project Selector in frontend**: Allow users to create, switch, and view their novels from the UI.

---

## 2. Directory Layout & Migration

### Target Directory Structure
```text
data/
  ├── examples/
  │     └── harry_potter_sample.json
  └── projects/
        ├── default/                  <-- Migrated or initial project
        │     ├── project.json
        │     ├── state/
        │     │     ├── chronicle.json
        │     │     ├── story_memory.json
        │     │     └── character_*.json
        │     └── chromadb/
        ├── novel_magic_academy/
        │     ├── project.json
        │     ├── state/
        │     └── chromadb/
        └── novel_sci_fi/
              ├── project.json
              ├── state/
              └── chromadb/
```

### Backward Compatibility / Auto-Migration
If `data/project.json` exists at the root of `data/`, the backend should automatically move or copy it (along with `data/state/` and `data/chromadb/`) into `data/projects/default/` on boot.

---

## 3. Backend Changes

### A. `backend/storyweaver/config.py`
Add paths for multi-project root:
```python
PROJECTS_DIR = DATA_DIR / "projects"
DEFAULT_PROJECT_ID = "default"
```

### B. `backend/storyweaver/ui/project.py`
Update `ProjectStore`:
```python
class ProjectStore:
    def __init__(self, project_id: str = "default", data_dir: Path | str | None = None):
        if data_dir is not None:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = config.PROJECTS_DIR / project_id
        self.project_id = project_id
```

Add helper functions:
- `list_projects() -> list[dict]`: Scans `config.PROJECTS_DIR` for directories containing `project.json` and returns id, title, episode count, updated time.
- `create_project(project_id: str, title: str) -> Project`: Initializes a new folder with an initial `Project(name=title)`.

### C. `backend/storyweaver/api/deps.py`
Replace global singletons with a project-aware resolver:

1. **Project ID dependency**:
```python
from fastapi import Header, Query

def get_project_id(
    x_project_id: str | None = Header(default=None, alias="X-Project-Id"),
    project_id: str | None = Query(default=None),
) -> str:
    # Fallback to DEFAULT_PROJECT_ID if not provided
    pid = x_project_id or project_id or config.DEFAULT_PROJECT_ID
    return safe_project_id(pid)
```

2. **ProjectStore injection**:
```python
def get_store(project_id: str = Depends(get_project_id)) -> ProjectStore:
    return ProjectStore(project_id=project_id)
```

3. **MemoryManager caching per project**:
Maintain a cache of `MemoryManager` instances keyed by `project_id`:
```python
_memory_managers: dict[str, MemoryManager] = {}

def get_memory(project_id: str = Depends(get_project_id)) -> MemoryManager | None:
    if project_id not in _memory_managers:
        store = get_store(project_id)
        try:
            _memory_managers[project_id] = MemoryManager(
                data_dir=store.state_dir,
                chroma_client=chromadb.PersistentClient(path=str(store.chroma_dir)),
            )
        except Exception as error:
            logger.exception("Failed to initialize memory for project %s", project_id)
            return None
    return _memory_managers[project_id]
```

### D. `backend/storyweaver/api/project.py`
Add project management endpoints:
- `GET /api/projects` -> List all projects (id, name, updated_at, episode_count)
- `POST /api/projects` -> Create a new project `{ "id": "...", "name": "..." }`
- `DELETE /api/projects/{project_id}` -> (Optional) Delete a project

Existing endpoints (`/api/project`, `/api/world`, `/api/characters`, `/api/episodes`, etc.) remain identical because they already use `Depends(deps.get_project)`, `Depends(deps.get_store)`, `Depends(deps.get_memory)`, which now automatically receive the project ID from the request header!

---

## 4. Frontend Changes

### A. API Client (`frontend/src/api/client.ts`)
1. Store current project ID in `localStorage` (`storyweaver_current_project_id`, defaults to `"default"`).
2. Attach `X-Project-Id` header to every HTTP request in the `request()` helper:
```typescript
const currentProjectId = localStorage.getItem('storyweaver_current_project_id') || 'default'

headers: {
  'Content-Type': 'application/json',
  'X-Project-Id': currentProjectId,
  ...options.headers,
}
```
3. Add API client functions:
- `listProjects(): Promise<ProjectSummary[]>`
- `createProject(payload: { id: string; name: string }): Promise<Project>`

### B. ProjectContext (`frontend/src/state/ProjectContext.tsx`)
Extend `ProjectContext` to manage project list and active switching:
```typescript
interface ProjectSummary {
  id: string
  name: string
  episodes_count: number
  updated_at?: string
}

interface ProjectContextValue {
  // Existing fields:
  project: Project | null
  stats: ProjectStats | null
  health: Health | null
  loading: boolean
  offline: string
  refresh: () => Promise<void>
  
  // New fields:
  currentProjectId: string
  projects: ProjectSummary[]
  switchProject: (projectId: string) => Promise<void>
  createProject: (name: string, id?: string) => Promise<void>
}
```
When `switchProject(newId)` is called:
1. Update `localStorage.setItem('storyweaver_current_project_id', newId)`
2. Reset/reload project, stats, and health.
3. All components across all pages automatically re-render with the new novel's data.

### C. UI: Project Selector Component (`frontend/src/components/ProjectSelector.tsx`)
Add a selector component in `AppLayout.tsx` (top navigation header or sidebar header):
- Dropdown showing current novel title (e.g. `📚 마법 아카데미의 천재`)
- List of available projects to switch with one click
- "+ 새 소설 만들기 (New Novel)" modal triggering `createProject()`

---

## 5. Verification Checklist

1. **Auto-migration**: Existing `data/project.json` and memory safely migrate to `data/projects/default/` without data loss.
2. **Project creation**: User can create a new project with title "소설 B" from the UI.
3. **Data isolation**:
   - Adding a character in "소설 B" does NOT appear in "소설 A".
   - Vector search / memories generated in "소설 B" do NOT pollute "소설 A".
4. **Seamless switching**: Switching projects in the top dropdown immediately updates Dashboard, WorldBuilder, CharacterWorkshop, EpisodeQueue, etc.
5. **Full test suite passing**: Existing pytest and vitest/tsc build cleanly.
