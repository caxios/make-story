# Phase 2: AI-Driven Episode Planning

**Depends on:** Phase 1 Backend and Frontend should be done first, but this phase can be implemented in parallel if needed.  
**Goal:** Add a new "Story Planner" page where the author writes one-line episode summaries, the AI expands them into detailed episode plans, and the author approves each plan before actual prose generation begins.

---

## Files to Create / Modify

| # | File | Action |
|---|---|---|
| 1 | `backend/storyweaver/api/episodes.py` | **MODIFY** — add `POST /api/episodes/plan-all` endpoint |
| 2 | `frontend/src/api/client.ts` | **MODIFY** — add `planAllEpisodes()` function |
| 3 | `frontend/src/pages/StoryPlanner.tsx` | **CREATE** — new page |
| 4 | `frontend/src/App.tsx` | **MODIFY** — register `/planner` route |
| 5 | `frontend/src/components/AppLayout.tsx` | **MODIFY** — add nav link |

---

## Change 1: `backend/storyweaver/api/episodes.py` (MODIFY)

### 1a — New request/response models

Add these Pydantic models after the existing `BatchRequest` model (around line 52):

```python
class ExpandedEpisodeSummary(BaseModel):
    """One episode: the author's one-line summary + the AI-expanded storyline."""
    episode_number: int
    title: str
    author_one_line: str        # the raw author input, preserved unchanged
    author_storyline: str       # the AI-expanded version


class PlanAllRequest(BaseModel):
    summaries: list[str] = Field(
        min_length=1,
        description="One entry per episode, in order. Each is a one-line or short description.",
    )


class PlanAllResponse(BaseModel):
    episodes: list[ExpandedEpisodeSummary]
```

### 1b — Helper: `_expand_summary()`

Add this function after the existing helper functions (`_check_pacing`, `_check_density`, `_check_status`):

```python
def _expand_summary(
    summary: str,
    episode_number: int,
    project: Project,
    prior_summaries: list[str],
) -> str:
    """
    Use the LLM to expand a one-line episode summary into a detailed outline.

    The result is a multi-paragraph text written for the Director/Writer agents
    to use as `author_storyline`. It should specify which characters appear,
    what the main conflict or event is, the emotional arc, and the ending beat.
    """
    from storyweaver.agents import context as ctx
    from storyweaver.llm import get_llm

    char_summaries = ctx.format_character_summaries(list(project.char_map.values()))
    world_overview = ctx.format_world_summary(project.world)

    prior_text = ""
    if prior_summaries:
        numbered = "\n".join(
            f"Episode {i + 1}: {s}" for i, s in enumerate(prior_summaries)
        )
        prior_text = f"\n\nPrevious episodes (for continuity):\n{numbered}"

    prompt = f"""\
You are a story planning assistant for the serial novel "{project.world.title}".
The author has provided a one-line summary for episode {episode_number}.

Your job is to expand it into a detailed episode outline (4–6 paragraphs) that:
1. Names the characters who appear in this episode
2. Describes the main conflict, event, or revelation of the episode
3. Describes the emotional arc — how the characters feel at the start and end
4. Suggests 2–3 key scenes with their location and mood
5. States the ending beat clearly — what the reader is left with

Do NOT write prose fiction. Write a planning document in clear, concise Korean.
Do NOT invent characters or events that contradict the world and cast provided below.

--- CAST ---
{char_summaries}

--- WORLD ---
{world_overview}
{prior_text}

--- AUTHOR'S ONE-LINE SUMMARY FOR EPISODE {episode_number} ---
{summary}

Return only the expanded outline text. No headers, no JSON, no markdown fences.
"""

    llm = get_llm()
    result = llm.invoke(prompt)
    return result.content.strip()
```

> **Note on `project.char_map`:** Check `backend/storyweaver/ui/project.py` for the exact attribute name. The `Project` model may expose characters as a list (`project.characters`) rather than a dict. If so, build the map: `char_map = {c.id: c for c in project.characters}` and call `ctx.format_character_summaries(project.characters)`.

### 1c — New endpoint: `POST /api/episodes/plan-all`

Add this endpoint function after the existing endpoints in `episodes.py` (before the end of the file):

```python
@router.post("/plan-all", response_model=PlanAllResponse)
def plan_all_episodes(
    body: PlanAllRequest,
    project: Project = Depends(deps.get_project),
) -> PlanAllResponse:
    """
    Expand a list of one-line episode summaries into detailed planning documents.

    This endpoint does NOT save anything to disk and does NOT generate prose.
    The frontend receives the expanded plans, shows them to the author for
    review/editing, and only saves them after the author approves each one.

    Saving is done via the existing POST /api/episodes endpoint, called once
    per approved episode.
    """
    results: list[ExpandedEpisodeSummary] = []
    prior_summaries: list[str] = []

    for i, raw_summary in enumerate(body.summaries):
        episode_number = i + 1
        expanded = _expand_summary(
            summary=raw_summary.strip(),
            episode_number=episode_number,
            project=project,
            prior_summaries=prior_summaries,
        )
        # Use the one-liner as a title placeholder; the author will rename it.
        short_title = raw_summary.strip()[:40] + ("…" if len(raw_summary.strip()) > 40 else "")

        results.append(
            ExpandedEpisodeSummary(
                episode_number=episode_number,
                title=f"Episode {episode_number}",
                author_one_line=raw_summary.strip(),
                author_storyline=expanded,
            )
        )
        prior_summaries.append(raw_summary.strip())

    return PlanAllResponse(episodes=results)
```

---

## Change 2: `frontend/src/api/client.ts` (MODIFY)

Add the following after the existing `parseWorld` function added in Phase 1:

```typescript
// ── Episode planning (Phase 2) ─────────────────────────────────────────────

export interface ExpandedEpisodeSummary {
  episode_number: number
  title: string
  author_one_line: string
  author_storyline: string
}

export interface PlanAllResponse {
  episodes: ExpandedEpisodeSummary[]
}

export async function planAllEpisodes(summaries: string[]): Promise<PlanAllResponse> {
  return request<PlanAllResponse>('/api/episodes/plan-all', {
    method: 'POST',
    body: { summaries },
  })
}
```

Then, to save an approved episode, use the **existing** `createEpisode` function in `client.ts` (look for `POST /api/episodes` — it may be named `addEpisode` or `createEpisode`). Each approved episode is saved with:
```typescript
await api.createEpisode({
  author_storyline: episode.author_storyline,
  title: episode.title,
  pacing: 'normal',
})
```

---

## Change 3: `frontend/src/pages/StoryPlanner.tsx` (CREATE)

This is a new file. Create it from scratch.

```tsx
/**
 * 📋 Story Planner — write one-line episode summaries, get detailed plans back.
 *
 * Workflow:
 *   1. Author fills in one row per episode (one-line or short summary)
 *   2. Clicks "Generate Plans" — LLM expands each into a detailed outline
 *   3. Author reviews/edits each plan and approves or skips
 *   4. Approved plans are saved to the episode queue one by one
 */

import { CheckCircle, Circle, Loader, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import type { ExpandedEpisodeSummary } from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Button,
  EmptyState,
  IconButton,
  PageHeader,
  Panel,
  TextArea,
  TextField,
} from '@/components/ui'
import { useProject } from '@/state/ProjectContext'

export function StoryPlanner() {
  const { project, refresh } = useProject()
  const { success, fromError } = useToast()
  const navigate = useNavigate()

  // Step 1: Author's one-line summaries
  const [summaries, setSummaries] = useState<string[]>(['', '', ''])

  // Step 2: AI-expanded plans (null = not generated yet)
  const [plans, setPlans] = useState<ExpandedEpisodeSummary[] | null>(null)

  // Which episodes the author has approved (by index into `plans`)
  const [approved, setApproved] = useState<Set<number>>(new Set())

  // Editable titles and storylines for the review step
  const [editedTitles, setEditedTitles] = useState<string[]>([])
  const [editedStorylines, setEditedStorylines] = useState<string[]>([])

  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)

  // ── Step 1 handlers ──────────────────────────────────────────────────────

  function updateSummary(index: number, value: string) {
    const next = [...summaries]
    next[index] = value
    setSummaries(next)
  }

  function addRow() {
    setSummaries([...summaries, ''])
  }

  function removeRow(index: number) {
    setSummaries(summaries.filter((_, i) => i !== index))
  }

  async function handleGenerate() {
    const nonEmpty = summaries.filter((s) => s.trim())
    if (nonEmpty.length === 0) return
    setGenerating(true)
    try {
      const result = await api.planAllEpisodes(nonEmpty)
      setPlans(result.episodes)
      setEditedTitles(result.episodes.map((e) => e.title))
      setEditedStorylines(result.episodes.map((e) => e.author_storyline))
      setApproved(new Set())
    } catch (err) {
      fromError(err)
    } finally {
      setGenerating(false)
    }
  }

  // ── Step 2 handlers ──────────────────────────────────────────────────────

  function toggleApprove(index: number) {
    const next = new Set(approved)
    if (next.has(index)) {
      next.delete(index)
    } else {
      next.add(index)
    }
    setApproved(next)
  }

  function approveAll() {
    if (!plans) return
    setApproved(new Set(plans.map((_, i) => i)))
  }

  async function handleSaveApproved() {
    if (!plans) return
    setSaving(true)
    try {
      for (const index of Array.from(approved).sort()) {
        await api.createEpisode({
          author_storyline: editedStorylines[index],
          title: editedTitles[index],
          pacing: 'normal',
        })
      }
      await refresh()
      success(`${approved.size} episode(s) added to the queue.`)
      navigate('/episodes')
    } catch (err) {
      fromError(err)
    } finally {
      setSaving(false)
    }
  }

  // ── Guard: no world or characters yet ───────────────────────────────────

  if (!project?.world?.overview) {
    return (
      <EmptyState
        title="Set up your world first"
        description="Go to World Builder and describe your story's setting before planning episodes."
        action={<Button onClick={() => navigate('/world')}>Open World Builder</Button>}
      />
    )
  }

  // ── Step 1: Summary Input ────────────────────────────────────────────────

  if (!plans) {
    return (
      <>
        <PageHeader
          title="Story Planner"
          description="Write one line per episode. The AI will expand each into a full planning document."
        />

        <Panel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {summaries.map((summary, i) => (
              <div
                key={i}
                style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}
              >
                <span
                  style={{
                    minWidth: '2rem',
                    paddingTop: '0.5rem',
                    color: 'var(--color-muted)',
                    fontSize: '0.875rem',
                    textAlign: 'right',
                  }}
                >
                  {i + 1}.
                </span>
                <TextArea
                  rows={2}
                  placeholder={`Episode ${i + 1} — e.g. "지민이 오랜 친구 유나와 재회하고, 유나의 비밀을 눈치챈다"`}
                  value={summary}
                  onChange={(e) => updateSummary(i, e.target.value)}
                  style={{ flex: 1 }}
                />
                <IconButton
                  icon={Trash2}
                  label="Remove"
                  tone="bad"
                  onClick={() => removeRow(i)}
                  disabled={summaries.length <= 1}
                  style={{ marginTop: '0.25rem' }}
                />
              </div>
            ))}
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '1.25rem',
            }}
          >
            <Button variant="ghost" onClick={addRow}>
              <Plus size={16} /> Add Episode
            </Button>
            <Button
              disabled={summaries.every((s) => !s.trim()) || generating}
              onClick={handleGenerate}
            >
              {generating ? (
                <>
                  <Loader size={16} style={{ animation: 'spin 1s linear infinite' }} />
                  Generating plans…
                </>
              ) : (
                <>
                  <Sparkles size={16} /> Generate Episode Plans
                </>
              )}
            </Button>
          </div>
        </Panel>
      </>
    )
  }

  // ── Step 2: Review Plans ─────────────────────────────────────────────────

  return (
    <>
      <PageHeader
        title="Review Episode Plans"
        description={`${plans.length} episode(s) planned. Approve the ones you want to add to the queue.`}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {plans.map((plan, i) => (
          <Panel key={plan.episode_number}>
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '1rem',
                marginBottom: '1rem',
              }}
            >
              {/* Approve toggle */}
              <button
                onClick={() => toggleApprove(i)}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: approved.has(i) ? 'var(--color-accent)' : 'var(--color-muted)',
                  padding: 0,
                  marginTop: '0.25rem',
                  flexShrink: 0,
                }}
              >
                {approved.has(i) ? <CheckCircle size={22} /> : <Circle size={22} />}
              </button>

              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <span style={{ color: 'var(--color-muted)', fontSize: '0.8rem' }}>
                    Episode {plan.episode_number}
                  </span>
                  <span style={{ color: 'var(--color-muted)' }}>·</span>
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-muted)', fontStyle: 'italic' }}>
                    "{plan.author_one_line}"
                  </span>
                </div>

                <TextField
                  label="Title"
                  value={editedTitles[i]}
                  onChange={(e) => {
                    const next = [...editedTitles]
                    next[i] = e.target.value
                    setEditedTitles(next)
                  }}
                  style={{ marginBottom: '0.75rem' }}
                />

                <TextArea
                  label="Episode plan (edit freely)"
                  rows={10}
                  value={editedStorylines[i]}
                  onChange={(e) => {
                    const next = [...editedStorylines]
                    next[i] = e.target.value
                    setEditedStorylines(next)
                  }}
                />
              </div>
            </div>
          </Panel>
        ))}
      </div>

      {/* Action bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: '1.5rem',
          paddingTop: '1rem',
          borderTop: '1px solid var(--color-border)',
        }}
      >
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <Button variant="ghost" onClick={() => setPlans(null)}>
            ← Back to summaries
          </Button>
          <Button variant="ghost" onClick={approveAll}>
            Approve all
          </Button>
        </div>

        <Button
          disabled={approved.size === 0 || saving}
          onClick={handleSaveApproved}
        >
          {saving
            ? 'Saving…'
            : `Save ${approved.size} episode(s) to queue →`}
        </Button>
      </div>
    </>
  )
}
```

---

## Change 4: `frontend/src/App.tsx` (MODIFY)

**Add import** at the top of the file with the other page imports:
```tsx
import { StoryPlanner } from '@/pages/StoryPlanner'
```

**Add route** inside `<Routes>`:
```tsx
<Route path="planner" element={<StoryPlanner />} />
```

---

## Change 5: `frontend/src/components/AppLayout.tsx` (MODIFY)

**Add import** for the `ClipboardList` icon (already imported in `EpisodeQueue.tsx`, check if it needs adding to `AppLayout.tsx`):
```tsx
import { ..., ClipboardList } from 'lucide-react'
```

**Add nav item** to the `NAV` array, after the `캐릭터 워크숍` entry and before `에피소드 큐`:

```typescript
const NAV: NavItem[] = [
  { to: '/', label: '대시보드', icon: Home },
  { to: '/world', label: '세계관 빌더', icon: BookOpen },
  { to: '/characters', label: '캐릭터 워크숍', icon: Users },
  { to: '/planner', label: '스토리 플래너', icon: ClipboardList },  // <-- ADD
  { to: '/episodes', label: '에피소드 큐', icon: ListOrdered },
  { to: '/reading', label: '리딩룸 (본문 열람)', icon: Feather },
  { to: '/memory', label: '메모리 인스펙터', icon: Brain },
  { to: '/settings', label: '설정', icon: Settings },
]
```

---

## Verification Checklist

### Backend
```powershell
# Start backend
.venv\Scripts\python -m uvicorn storyweaver.app:app --reload --port 8000

# Test plan-all with 2 summaries
$body = '{"summaries": ["지민이 유나와 재회하고 유나의 비밀을 눈치챈다", "지민이 유나를 미행하다 위험한 진실을 발견한다"]}'
Invoke-RestMethod -Uri "http://localhost:8000/api/episodes/plan-all" -Method POST -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 10
```

Expected: A `PlanAllResponse` JSON with `episodes` array, each containing `episode_number`, `author_one_line`, and a multi-paragraph `author_storyline` in Korean.

### Frontend
1. Navigate to `/planner` in the browser.
2. Three empty input rows appear with placeholder text.
3. Type a one-liner in each row → click **"Generate Episode Plans"** → spinner appears.
4. After ~10–20 seconds, the review step appears with expanded plans.
5. Each plan shows the original one-liner in italics, an editable title, and an editable multi-paragraph plan.
6. Click the circle icon next to an episode to approve it (circle turns to checkmark).
7. Click **"Save 1 episode(s) to queue →"** → navigated to `/episodes` with the new episode in the queue.
8. The new episode has `status: queued` and the approved `author_storyline`.

---

## Notes for the Implementer

### `api.createEpisode` function name
Check `frontend/src/api/client.ts` for the exact function that creates an episode (calls `POST /api/episodes`). It is likely named `createEpisode` or `addEpisode`. Use whatever name exists, or add one:

```typescript
export async function createEpisode(body: {
  author_storyline: string
  title?: string
  pacing?: string
}): Promise<Episode> {
  return request<Episode>('/api/episodes', {
    method: 'POST',
    body,
  })
}
```

### Performance: sequential LLM calls
The `plan_all_episodes` endpoint expands summaries **sequentially** (one at a time), passing each completed summary to the next as context. For 10+ episodes, this will take a while. If speed is a concern, run the first expansion independently and parallelize the rest — but for correctness, sequential is simpler.

### The `EmptyState` component
Check `frontend/src/components/ui/` for the exact props the `EmptyState` component accepts. If it does not accept an `action` prop, remove the action and just show the description text with a separate `<Button>` below.

### Error handling during Save
If saving one episode fails (e.g., duplicate `episode_number`), the loop continues to save the remaining approved episodes. Consider wrapping each `createEpisode` call in a try/catch and collecting errors, then reporting them after the loop rather than stopping on the first failure.
