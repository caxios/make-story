# Phase 5: Web UI (Streamlit)

## Goal

Build a web-based interface using Streamlit that allows the author to:
1. Define and edit the world, characters, and writing style
2. Queue episode storylines one by one
3. Trigger episode generation and watch progress
4. Read and review the generated prose
5. Inspect and manage memory (plot threads, character states)

The UI should feel like a **writer's workbench**, not a developer tool.

---

## 5.1 Page Structure

The Streamlit app uses a multi-page layout:

```
📖 StoryWeaver
├── 🏠 Dashboard           # overview, quick actions
├── 🌍 World Builder        # create/edit world lore, rules, locations
├── 👤 Character Workshop   # create/edit character profiles, relationships
├── 📝 Episode Queue        # add storylines, view queue, trigger generation
├── 📖 Reading Room         # read generated prose, chapter-by-chapter
├── 🧠 Memory Inspector     # view plot threads, character memories, episode summaries
└── ⚙️ Settings             # writing style, model config, export
```

---

## 5.2 Page Specifications

### 5.2.1 Dashboard (`pages/dashboard.py`)

- **Story Stats:** Total episodes written, total word count, active characters, open plot threads.
- **Quick Actions:** "Generate Next Episode" button, "Add Episode to Queue" shortcut.
- **Recent Activity:** Last 3 generated episodes with status and word count.
- **Active Plot Threads Preview:** Top 5 unresolved threads with staleness indicator.

### 5.2.2 World Builder (`pages/world_builder.py`)

- **World Overview Form:** Title, genre, tone, era, overview text (rich text area).
- **Rules Manager:** CRUD interface for world rules.
  - Each rule: category (dropdown), statement (text), exceptions (list).
  - "Add Rule" button, inline edit, delete with confirmation.
- **Location Manager:** CRUD for locations with parent-child hierarchy.
  - Tree view of location hierarchy.
  - Each location: name, description, notable features.
- **Factions List:** Simple list with add/remove.
- **Additional Lore:** Key-value editor for free-form lore entries.
- **Import/Export:** Load/save world as JSON.

### 5.2.3 Character Workshop (`pages/character_workshop.py`)

- **Character List:** Sidebar with all characters, click to edit.
- **Character Form:** All fields from `CharacterProfile` model.
  - Personality traits with intensity sliders (0.0 – 1.0).
  - Speech style with example dialogue preview.
  - Relationship editor: select target character, set type and sentiment slider.
  - Secrets list (collapsible, marked as "system-only").
- **Relationship Graph:** Visual network diagram (using `streamlit-agraph` or Mermaid).
  - Nodes = characters, edges = relationships, edge color/thickness = sentiment.
- **Character Clone:** Duplicate an existing character as a starting point.
- **Import/Export:** Load/save characters as JSON.

### 5.2.4 Episode Queue (`pages/episode_queue.py`)

- **Queue Table:** Ordered list of all episodes.
  - Columns: #, Title (editable), Status (queued/in_progress/completed), Word Count.
  - Drag-and-drop reorder (or up/down arrows).
- **Add Episode Form:**
  - Episode number (auto-incremented).
  - Title (optional).
  - Author Storyline (large text area — the core input).
    - Placeholder: "이번 회차에서 일어날 이야기를 대략적으로 적어주세요..."
  - "Add to Queue" button.
- **Batch Add:** Upload a text file with multiple episode outlines (one per section).
- **Generate Button:** "Generate Next Episode" — triggers the pipeline for the next queued episode.
  - Shows a progress indicator with current stage (Planning Scenes → Simulating Scene 1/4 → Checking Lore → Writing Scene 1/4 → ...).
  - Real-time log output in an expander.

### 5.2.5 Reading Room (`pages/reading_room.py`)

- **Episode Selector:** Dropdown or sidebar list of completed episodes.
- **Prose Display:** Clean, reader-friendly text display.
  - Large font, comfortable line spacing.
  - Scene breaks rendered as visual dividers.
  - Character dialogue highlighted or styled differently.
- **Side-by-Side View (optional toggle):**
  - Left: Generated prose.
  - Right: Original author storyline + scene breakdown (for comparison).
- **Edit Mode:** Author can manually edit the generated prose and save changes.
- **Export:** Download episode as `.txt`, `.md`, or `.docx`.

### 5.2.6 Memory Inspector (`pages/memory_inspector.py`)

- **Plot Thread Dashboard:**
  - Table: Thread name, status (color-coded), opened episode, last referenced, linked characters.
  - Filter by status (open/progressing/resolved).
  - Click to expand: full event timeline for the thread.
  - "Force Resolve" and "Reactivate" manual overrides.
- **Character Memory View:**
  - Select a character → see their interaction history, current emotional state, active goals, relationship graph.
  - Timeline visualization of interactions across episodes.
- **Episode Summaries:**
  - Accordion view of all episode summaries.
  - Search across summaries.
- **Raw Memory Search:**
  - Free-text semantic search box.
  - Shows top-K results from ChromaDB with source metadata.

### 5.2.7 Settings (`pages/settings.py`)

- **Writing Style Configuration:** All fields from `WritingStyle` model.
  - Perspective dropdown, POV character selector, prose density slider, dialogue ratio slider.
  - Language selector (한국어/English/etc.).
  - Author style notes text area.
- **Model Configuration:**
  - Model name (default: gemini-3.7-flash).
  - Temperature slider.
  - Max tokens.
- **Project Management:**
  - Export entire project (world + characters + episodes + memory) as ZIP.
  - Import project from ZIP.
  - "New Project" with confirmation dialog.

---

## 5.3 State Management

Streamlit's `st.session_state` will hold:
- Currently loaded project data (WorldLore, Characters, Episodes).
- Active MemoryManager instance.
- Generation progress state.

Persistent data is stored on disk (JSON files + ChromaDB) in the `data/` directory, and loaded/saved through the existing data models.

---

## 5.4 Real-Time Generation Feedback

When the author clicks "Generate Next Episode," the UI should show progress:

```
┌─────────────────────────────────────────┐
│ Generating Episode 12...                │
│                                         │
│ ✅ Planning scenes... (4 scenes)        │
│ ✅ Simulating Scene 1/4... Done         │
│ ✅ Lore check Scene 1... Passed         │
│ ✅ Writing Scene 1... Done (1,423 words)│
│ 🔄 Simulating Scene 2/4... (turn 7/20) │
│ ⬜ Lore check Scene 2...               │
│ ⬜ Writing Scene 2...                   │
│ ⬜ Scene 3/4...                         │
│ ⬜ Scene 4/4...                         │
│ ⬜ Assembling final text...             │
│                                         │
│ [Cancel]                                │
└─────────────────────────────────────────┘
```

Implementation: Use LangGraph's streaming/callback mechanism + Streamlit's `st.status` and `st.empty` for live updates.

---

## 5.5 Styling & UX

- **Color palette:** Dark theme with warm accent colors (amber/gold for a "writing desk" feel).
- **Typography:** Noto Serif KR for prose display (reading room), Inter/Pretendard for UI elements.
- **Icons:** Emoji-based for simplicity in Streamlit.
- **Responsive:** Streamlit handles responsiveness natively, but we'll use columns/containers for desktop optimization.

---

## 5.6 Testing Strategy

### Test 1: Full Workflow
- Create a world, add 2 characters, add 2 episodes to queue, generate both, read in Reading Room.
- Verify: No crashes, data persists between page navigations.

### Test 2: Data Persistence
- Add data, close and reopen the app.
- Verify: All data is still present.

### Test 3: Generation Progress
- Trigger episode generation.
- Verify: Progress indicator updates in real time, final text appears in Reading Room.

---

## Deliverables Checklist

- [ ] `ui/app.py` — Streamlit main entry point with page navigation
- [ ] `ui/pages/dashboard.py` — Dashboard with stats and quick actions
- [ ] `ui/pages/world_builder.py` — World creation and editing
- [ ] `ui/pages/character_workshop.py` — Character management with relationship graph
- [ ] `ui/pages/episode_queue.py` — Episode queue with generation trigger
- [ ] `ui/pages/reading_room.py` — Prose reader with edit and export
- [ ] `ui/pages/memory_inspector.py` — Memory browsing and search
- [ ] `ui/pages/settings.py` — Configuration management
- [ ] `ui/styles.css` — Custom styling
- [ ] Real-time generation progress display works
- [ ] Data round-trips correctly: create in UI → save → reload → display
