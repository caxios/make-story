# Phase 4: Episode Studio & Real-Time Generation

## 1. Goal

Build the core creative workflow in React: managing sequential chapter outlines and delivering a state-of-the-art **real-time AI generation experience** using Server-Sent Events (SSE) that replaces Streamlit's clunky full-page status reruns with smooth, responsive animations and live agent telemetry.

---

## 2. Episode Queue (`src/pages/EpisodeQueue.tsx`)

### 2.1 Queue Management
- Ordered list of episode cards showing:
  - Episode Number (`#1`, `#2`, etc.) and Chapter Title.
  - Status pill: `Queued` (violet), `In Progress` (amber animate-pulse), `Completed` (emerald).
  - Word count badge for completed chapters.
  - Outline preview snippet (expandable).
- **Reordering Controls**:
  - Drag-and-drop handles and 1-click Up/Down buttons (`↑`, `↓`).
  - Automatically triggers `/api/episodes/{num}/move` and updates local state without page refresh.

### 2.2 Episode Operations
- **Add Single Episode**: Modal with Title and rich Storyline textarea.
- **Batch Add**: Textarea supporting delimiter (`---`) to queue 5~10 chapters at once.
- **Re-queue / Regenerate**: Completed episodes can be re-queued with one click.
- **Delete with Confirmation**: Modal confirmation to avoid accidental data loss for completed chapters.

---

## 3. Real-Time Generation Experience

When the author clicks **"Generate Episode"**:

### 3.1 Live Generation Modal / Full-Screen Overlay
The generation window opens with high-polish dark glassmorphism and connects to `/api/generation/stream/{episode_number}`:

```
+-------------------------------------------------------------------+
|  Generating Episode 3: The Chamber of Echoes                      |
+-------------------------------------------------------------------+
|  [ ✓ Director ] -> [ ▶ Simulating Scene 2/4 ] -> [ Lore ] -> [ Write ] |
+-------------------------------------------------------------------+
|  Progress: [=====================>           ] 45%               |
|                                                                   |
|  Current Stage: Simulating Scene 2 - Dialogue Interaction         |
|  - Active Characters: Harry, Ron, Hermione                        |
|  - Scene Goal: Discover the cipher engraved on the brass statue   |
|                                                                   |
|  Agent Live Checklist:                                            |
|  ✓ Director planned 4 scenes                                      |
|  ✓ Scene 1 simulated (12 turns)                                   |
|  ✓ Scene 1 lore verified (Passed - 0 violations)                  |
|  ✓ Scene 1 prose drafted (842 words)                              |
|  ▶ Simulating Scene 2 (Turn 6/12)...                              |
|                                                                   |
|  Live Stats: 1,420 tokens generated · Elapsed: 18s                |
+-------------------------------------------------------------------+
```

### 3.2 Key Features of the Generation View
1. **Pipeline Stepper**: Visual node progression matching the LangGraph flow:
   - `Director` -> `Scene Runner` -> `Lore Checker` -> `Writer` -> `Memory Recorder`.
2. **Dynamic Checklist**: Real-time event log updating smoothly as SSE chunks arrive.
3. **Checkpoint Resumption Indicator**: If a previous generation was aborted, the UI detects saved scene checkpoints and displays: *"Resuming from Scene 3 (Scenes 1 & 2 already saved)"*.
4. **Error Handling & Recovery**: If an API error or network drop occurs, the modal displays the exact error message while confirming that completed scenes remain safely saved on disk.

---

## 4. Verification

1. Queue 3 episodes and reorder them; verify backend `project.json` matches the new sequence.
2. Trigger episode generation:
   - Verify SSE connection opens and streams progress in real time.
   - Verify that completed scenes advance the visual stepper.
   - Verify final prose is saved and status updates to `Completed`.
3. Test regeneration of an existing completed episode with user confirmation.
