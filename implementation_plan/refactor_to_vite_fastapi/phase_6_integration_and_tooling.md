# Phase 6: Integration, Dev Tooling & End-to-End Verification

## 1. Goal

Provide seamless developer tooling for running both the FastAPI backend and Vite frontend together, ensure clean production build packaging, and perform comprehensive end-to-end verification across the entire creative workflow.

---

## 2. Unified Developer Runner (`scripts/dev.py`)

A single cross-platform Python script to launch the full development environment with one command:

```bash
python scripts/dev.py
```

### 2.1 Behavior
- Spawns two background subprocesses:
  1. **Backend**: `uvicorn src.storyweaver.server:app --reload --port 8000`
  2. **Frontend**: `npm run dev` (in `frontend/` directory, serving on `http://localhost:5173`)
- Multiplexes stdout/stderr with color-coded prefixes (`[backend]` in cyan, `[frontend]` in magenta).
- Traps `SIGINT` (`Ctrl+C`) and cleanly terminates both processes without leaving orphaned ports or running tasks.

---

## 3. Production Build & Static Mount Support

While developing with Vite's HMR server is optimal for development speed, StoryWeaver can also be built into a **single self-contained server**:

1. **Frontend Build**:
   ```bash
   cd frontend && npm run build
   ```
   Outputs production-optimized HTML, CSS, and JS to `frontend/dist/`.
2. **FastAPI Static File Serving**:
   In `src/storyweaver/server.py`, if `frontend/dist` exists, mount it at the root:
   ```python
   if (FRONTEND_DIST / "index.html").is_file():
       app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
   ```
   This allows running the entire application on a single port (`http://localhost:8000`) without needing Node.js in production environments.

---

## 4. Streamlit Fallback Coexistence

The original Streamlit interface is preserved in `src/storyweaver/ui/`.
- Authors or developers who wish to run Streamlit can do so concurrently on port 8501:
  ```bash
  streamlit run src/storyweaver/ui/app.py --server.port 8501
  ```
- Because both frontends read and write to the same `data/project.json` and `data/chromadb`, changes made in one interface are immediately accessible in the other.

---

## 5. End-to-End Acceptance Checklist

| Step | Feature | Acceptance Criteria |
| :--- | :--- | :--- |
| 1 | **Environment Startup** | `python scripts/dev.py` launches both servers with zero errors. |
| 2 | **Dashboard** | Project stats, word counts, and open plot thread counters load correctly. |
| 3 | **World Lore** | Add a world rule and nested location; verify persistence in `data/project.json`. |
| 4 | **Character Studio** | Create character with personality sliders; verify visual relationship graph updates. |
| 5 | **Episode Queue** | Add an outline, reorder queue with up/down arrows; verify sequence renumbers correctly. |
| 6 | **Live Generation** | Trigger episode generation; verify real-time SSE stepper, checklist, and scene progression. |
| 7 | **Reading Room** | Finished chapter displays with clean novel typography; verify export to `.md`, `.docx`, and `.zip`. |
| 8 | **Memory & Threads** | Verify new scene interactions are logged to ChromaDB and appear in Memory Inspector. |
| 9 | **Episode Deletion** | Delete an episode with confirmation; verify subsequent episodes renumber sequentially. |
| 10 | **Episode Regeneration** | Re-queue and regenerate an episode; verify old chapter text is overwritten and checkpoints clear. |
