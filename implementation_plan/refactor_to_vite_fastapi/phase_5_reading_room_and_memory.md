# Phase 5: Reading Room & Memory Inspector

## 1. Goal

Deliver a dedicated, distraction-free reading environment for the generated novel chapters, provide one-click export workflows (Markdown, Docx, Zip), and implement an intuitive inspection interface for long-term memory (ChromaDB) and story foreshadowing / plot threads ("떡밥").

---

## 2. Reading Room (`src/pages/ReadingRoom.tsx`)

### 2.1 Reader Experience
- **Typography Controls**:
  - Font family toggle: Modern Sans (`Inter`) or Classic Editorial Serif (`Merriweather` / `Lora`).
  - Adjustable font size slider (16px ~ 24px) and comfortable line spacing (1.8 ~ 2.2).
  - Maximum text column width constraint (65ch ~ 75ch) for optimal reading rhythm.
- **Visual Presentation**:
  - Chapter Title header with word count and episode badge.
  - Distinct styling for scene break dividers (`◇◇◇`).
  - Dialogue formatting with subtle styling emphasis.
  - Universal text sanitizer to guarantee no leaked model signatures, extra metadata dictionaries, or unescaped `\n\n` characters ever appear in the reader.

### 2.2 Chapter Management & Editing
- **Sidebar Chapter Nav**: Quickly click between finished episodes.
- **Inline Edit Mode**: Toggle to a rich editor allowing the author to edit prose manually and save changes to disk via `PUT /api/episodes/{num}`.
- **Episode Actions**:
  - 🔄 Regenerate Episode (triggers confirmation modal, clears checkpoints, and re-queues).
  - 🗑️ Delete Episode (with word-count loss confirmation).

### 2.3 Export Workflow
- Download buttons with instant file delivery from FastAPI `/api/export`:
  - 📄 **Markdown (`.md`)**: Formatted with title, metadata, and scene dividers.
  - 📝 **Word Document (`.docx`)**: Styled document with headers and page breaks.
  - 📦 **Full Project Archive (`.zip`)**: Complete archive containing all chapters, world lore, and character profiles.

---

## 3. Memory Inspector (`src/pages/MemoryInspector.tsx`)

### 3.1 Plot Thread Dashboard ("떡밥" 관리)
- Visual Kanban or card list categorizing plot threads:
  - **Active Threads**: Open mysteries, promises, looming conflicts.
  - **Resolved Threads**: Solved questions and concluded character arcs.
- Thread details:
  - Description and opening episode number.
  - Linked characters.
  - Last referenced episode and staleness warning badge (e.g. *"Unmentioned for 4 episodes"*).

### 3.2 ChromaDB Semantic Search Playground
- Interactive search box to query the RAG memory store.
- Displays retrieved interaction cards sorted by similarity score:
  - Source episode and scene number.
  - Involved characters.
  - Summary of the simulated dialogue/action.

---

## 4. Settings Page (`src/pages/Settings.tsx`)

- **Writing Style Tuning**:
  - Narrative Perspective: First person (`1st`), Third person limited (`3rd_limited`), Omniscient (`3rd_omniscient`).
  - Tense: Past (`past`) or Present (`present`).
  - Dialogue-to-Narration Ratio: Slider from 0.2 to 0.8.
  - Pacing Preset: Fast, Moderate, Detailed/Slow.
- **Model & Telemetry**:
  - View configured Gemini model (`gemini-3.7-flash`).
  - Cumulative token usage meter and estimated cost tracking.

---

## 5. Verification

1. Load a completed episode in the Reading Room; confirm correct scene dividers and reader typography.
2. Edit a paragraph in Edit Mode, save, reload, and verify persistence.
3. Download `.md`, `.docx`, and `.zip` files and verify proper formatting.
4. Execute a semantic search query in the Memory Inspector and verify relevant memories are returned.
