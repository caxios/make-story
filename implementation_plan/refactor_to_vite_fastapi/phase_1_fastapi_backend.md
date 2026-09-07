# Phase 1: FastAPI Backend Layer

## 1. Goal

Build a clean, high-performance REST and Server-Sent Events (SSE) API layer using **FastAPI** that wraps the existing `StoryWeaver` Python core without altering the underlying agent logic, LangGraph workflows, ChromaDB storage, or Pydantic models.

---

## 2. Dependencies & Configuration

### 2.1 Dependencies (`pyproject.toml`)
Add the following packages to `pyproject.toml` dependencies:
- `fastapi>=0.110.0`: Async web framework with automatic OpenAPI documentation.
- `uvicorn[standard]>=0.28.0`: ASGI server for running FastAPI.
- `sse-starlette>=2.0.0`: High-performance Server-Sent Events streaming support.
- `httpx>=0.27.0`: Required for async testing with `pytest`.

### 2.2 Server Entry Point (`src/storyweaver/server.py`)
- Configure `FastAPI(title="StoryWeaver API", version="0.2.0")`.
- Configure `CORSMiddleware`:
  - `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]`
  - `allow_credentials=True`
  - `allow_methods=["*"]`
  - `allow_headers=["*"]`
- Provide application lifespan to cleanly initialize `ProjectStore` and verify `MemoryManager` state.

---

## 3. API Route Structure

All endpoints reside under `src/storyweaver/api/`:

```
src/storyweaver/api/
├── __init__.py
├── deps.py              # Shared dependencies (get_store, get_project, get_memory)
├── project.py           # Project state, metadata, and dashboard statistics
├── world.py             # World lore, rules, and location hierarchy CRUD
├── characters.py        # Character profiles, cloning, and relationship graph data
├── episodes.py          # Episode queue CRUD, reordering, and batch import
├── generation.py        # Real-time SSE streaming generation endpoint
├── memory.py            # Vector memory search and plot thread inspection
└── export.py            # Chapter & project export downloads (md, docx, zip)
```

---

## 4. Detailed Endpoint Specifications

### 4.1 Project & Stats (`/api/project`)
- `GET /api/project`: Returns full `Project` model JSON.
- `PUT /api/project`: Atomically overwrites project data and saves to disk via `ProjectStore`.
- `GET /api/project/stats`: Returns `ProjectStats` (episodes total, completed, queued, word count, character count, open plot threads).

### 4.2 World Lore (`/api/world`)
- `GET /api/world`: Fetch `WorldLore`.
- `PUT /api/world`: Update title, genre, tone, era, overview.
- `POST /api/world/rules`: Add or update a world rule.
- `DELETE /api/world/rules/{rule_id}`: Delete a rule.
- `POST /api/world/locations`: Add or update a location (supporting parent-child hierarchy).
- `DELETE /api/world/locations/{location_id}`: Delete a location and re-parent orphans to root.

### 4.3 Characters (`/api/characters`)
- `GET /api/characters`: Return list of `CharacterProfile`.
- `POST /api/characters`: Upsert character profile.
- `DELETE /api/characters/{character_id}`: Delete character and automatically cascade-remove any relationship referencing this character.
- `POST /api/characters/{character_id}/clone`: Clone character with new `id` and `name`.
- `GET /api/characters/graph`: Return `{ nodes: [...], edges: [...] }` formatted specifically for visual network rendering (node id, label, role; edge source, target, type, sentiment score).

### 4.4 Episode Queue (`/api/episodes`)
- `GET /api/episodes`: Return all episodes ordered by `episode_number`.
- `POST /api/episodes`: Add new outline (`author_storyline`, `title`). Auto-increments episode number.
- `PUT /api/episodes/{episode_number}`: Update episode title, storyline, pacing, or status.
- `DELETE /api/episodes/{episode_number}`: Delete episode and automatically renumber remaining episodes sequentially.
- `POST /api/episodes/{episode_number}/move`: Reorder queue by `offset` (`-1` for up, `+1` for down) with auto-renumbering.
- `POST /api/episodes/batch`: Import outlines from multi-chapter text separated by delimiter.

### 4.5 Real-time Generation Stream (`/api/generation`)
- `GET /api/generation/stream/{episode_number}?max_turns={max_turns}`
  - Protocol: **Server-Sent Events (SSE)**
  - Wrapper around `episode_runner.stream_episode()`
  - Yields JSON payloads:
    ```json
    {
      "event": "node_update",
      "data": {
        "node": "director_plan_scenes",
        "current_scene": 0,
        "total_scenes": 4,
        "label": "Planning scene breakdown...",
        "summary": "Director created 4 scenes."
      }
    }
    ```
  - Yields `"complete"` event when assembly finishes with updated episode model.
  - Yields `"error"` event if an exception occurs, preserving checkpoint info.

### 4.6 Memory Inspector (`/api/memory`)
- `GET /api/memory/threads`: Fetch active and resolved plot threads (떡밥).
- `POST /api/memory/query`: Semantic search query against ChromaDB vector store; returns matched documents with relevance scores.

### 4.7 Export (`/api/export`)
- `GET /api/export/episode/{number}/markdown`: Stream formatted `.md` file.
- `GET /api/export/episode/{number}/docx`: Stream formatted Word document.
- `GET /api/export/project/zip`: Stream full project ZIP archive containing all episodes and lore.

---

## 5. Verification & Testing

1. **Unit Tests**:
   - Write `tests/test_api_endpoints.py` using FastAPI's `TestClient`.
   - Validate project loading, character cascading deletion, episode renumbering, and batch outline creation.
2. **Interactive Swagger UI**:
   - Run `uvicorn src.storyweaver.server:app --reload --port 8000`
   - Open `http://localhost:8000/docs` and test all endpoints interactively.
