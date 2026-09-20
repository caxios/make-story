# UX Improvement Plan: From Form-Based Setup to Conversational Story Planning

## Overview

The current StoryWeaver UI requires authors to fill out complex, form-heavy pages to configure their story world, characters, and episode outlines. This plan redesigns the authoring experience around two key principles:

1. **Free-text first, structured second** — Authors write naturally; the AI extracts structure.
2. **AI proposes, author approves** — The AI generates episode plans from one-line author summaries; the author reviews and approves before prose is written.

This document describes what to change, why, and exactly how to implement it. It is written for an AI coding tool implementing the changes from scratch.

---

## Background: Current Architecture

Before making changes, understand the existing system:

### Data Model (`backend/storyweaver/ui/project.py`)
All author settings live in a single file: `data/project.json`. It has four top-level sections:
- `world` — a `WorldLore` object (title, genre, tone, overview, rules, locations, factions)
- `characters` — a list of `CharacterProfile` objects (each with ~15 fields)
- `episodes` — a list of `Episode` objects (each with `author_storyline`, `status`, `scenes`, `final_text`)
- `style` — a `WritingStyle` object (perspective, tense, density, language, etc.)

### Frontend Pages (`frontend/src/pages/`)
- `WorldBuilder.tsx` (829 lines) — Three-tab form: Overview, Rules, Locations
- `CharacterWorkshop.tsx` (1008 lines) — Cast list + drawer editor with ~15 input fields per character
- `EpisodeQueue.tsx` (896 lines) — Queue of episodes; author writes the `author_storyline` free-text per episode manually

### Backend API (`backend/storyweaver/api/`)
- `world.py` — CRUD for world settings
- `characters.py` — CRUD for characters
- `episodes.py` — CRUD for episodes + plan generation (`POST /api/episodes/{n}/plan`)
- `generation.py` — SSE streaming for actual story generation

### Key existing types (`frontend/src/types/storyweaver.ts`)
```typescript
interface CharacterProfile {
  id: string; name: string; role: string; aliases: string[]
  age: number | null; gender: string | null; appearance: string
  personality_summary: string; traits: Trait[]; speech_style: string
  values: string[]; goals: string[]; backstory: string
  relationships: Relationship[]; secrets: string[]; author_notes: string
}

interface Episode {
  episode_number: number; title: string; author_storyline: string
  scenes: Scene[]; final_text: string; summary: string
  status: EpisodeStatus; pacing: Pacing
}

type EpisodeStatus = 'queued' | 'planned' | 'in_progress' | 'completed'
```

---

## Goals

| Pain Point (Current) | Target State |
|---|---|
| 15+ form fields to create a character | Write a paragraph; AI fills the fields |
| World rules/locations in separate tabs requiring structured input | Free-text world description; AI extracts rules and locations |
| Author must manually write every episode's storyline | Author writes one line per episode; AI drafts a detailed plan |
| No preview of how settings affect the story | AI-generated plan shows exactly which characters appear in which scene |
| Character relationships require entering A→B and B→A separately | Describe relationships in prose; AI creates bidirectional entries |
| Age and gender are set but never sent to the LLM | Include `age` and `gender` in all character prompt contexts |

---

## Scope: Three Phases

```
Phase 1 — Natural Language Setup
  Redesign WorldBuilder and CharacterWorkshop to accept free-text input
  and parse it into structured data via a new backend endpoint.

Phase 2 — AI-Driven Episode Planning
  Add a "plan all episodes" flow: author writes one-line summaries;
  LLM drafts detailed scene plans; author reviews each before writing begins.

Phase 3 — Fix Missing Prompt Fields
  Pass age, gender, backstory, and role to character and writer agents
  (a small but high-impact fix that can be done independently).
```

---

## Phase 1: Natural Language Setup

### 1.1 New Backend Endpoint: `POST /api/parse/character`

**File to create:** `backend/storyweaver/api/parse.py`

This endpoint takes a free-text description of a character and returns a fully-populated `CharacterProfile`.

```python
# backend/storyweaver/api/parse.py

from fastapi import APIRouter
from pydantic import BaseModel
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, WorldLore
from storyweaver.api.deps import get_project

router = APIRouter(prefix="/api/parse", tags=["parse"])

class ParseCharacterRequest(BaseModel):
    text: str            # free-form author description
    existing_character_ids: list[str] = []  # to avoid id collisions

class ParseWorldRequest(BaseModel):
    text: str            # free-form world description

@router.post("/character", response_model=CharacterProfile)
def parse_character(body: ParseCharacterRequest):
    """
    Ask the LLM to extract a CharacterProfile from free text.
    The prompt instructs the model to return valid JSON matching CharacterProfile.
    """
    llm = get_llm()  # existing helper that returns a configured LangChain LLM
    # Build the prompt using the existing CharacterProfile schema
    prompt = _build_character_parse_prompt(body.text, body.existing_character_ids)
    result = llm.invoke(prompt)
    # Parse the JSON out of the response (use existing pattern from director.py)
    return CharacterProfile.model_validate_json(_extract_json(result.content))

@router.post("/world", response_model=WorldLore)
def parse_world(body: ParseWorldRequest):
    """
    Extract WorldLore fields from a free-text world description.
    """
    llm = get_llm()
    prompt = _build_world_parse_prompt(body.text)
    result = llm.invoke(prompt)
    return WorldLore.model_validate_json(_extract_json(result.content))
```

**Prompt design for character parsing:**
```python
def _build_character_parse_prompt(text: str, existing_ids: list[str]) -> str:
    return f"""
You are a story assistant. Extract a character profile from the author's description.
Return ONLY valid JSON matching this schema (no markdown, no explanation):

{{
  "id": "<slug: lowercase, hyphens, unique, not in {existing_ids}>",
  "name": "<full name>",
  "role": "<one of: 주인공 | 적대자 / 악역 | 서브 주인공 | 조연 | 스승 / 조력자 | 라이벌 / 대조 인물 | 연인 / 히로인 | 단역 / 엑스트라>",
  "aliases": [],
  "age": <number or null>,
  "gender": "<string or null>",
  "appearance": "<physical description>",
  "personality_summary": "<2-3 sentence personality summary>",
  "traits": [{{"name": "...", "intensity": 0.0-1.0, "description": "..."}}],
  "speech_style": "<how they talk: formality, dialect, verbal habits>",
  "values": ["...", "..."],
  "goals": ["...", "..."],
  "backstory": "<background>",
  "relationships": [
    {{"target_character_id": "...", "type": "...", "sentiment": -1.0-1.0, "description": "..."}}
  ],
  "secrets": ["..."],
  "author_notes": ""
}}

Author's description:
{text}
"""
```

**Register the router** in `backend/storyweaver/api/__init__.py`:
```python
from storyweaver.api import parse
app.include_router(parse.router)
```

---

### 1.2 New Backend Endpoint: `POST /api/parse/world`

Use the same `parse.py` file (already shown above). The world prompt:

```python
def _build_world_parse_prompt(text: str) -> str:
    return f"""
You are a story assistant. Extract a WorldLore from the author's description.
Return ONLY valid JSON (no markdown):

{{
  "title": "<world/story title>",
  "genre": "<fantasy|science fiction|mystery|modern|historical|horror|romance|thriller|literary>",
  "tone": "<mood/atmosphere in 2-3 words>",
  "era": "<time period or null>",
  "overview": "<multi-paragraph world description>",
  "rules": [
    {{"id": "rule-1", "category": "<magic|physics|society|politics|technology|taboo|economy|biology>",
      "statement": "...", "exceptions": []}}
  ],
  "locations": [
    {{"id": "loc-1", "name": "...", "description": "...",
      "parent_location_id": null, "notable_features": []}}
  ],
  "factions": [],
  "additional_lore": {{}}
}}

Author's description:
{text}
"""
```

---

### 1.3 Frontend: Add "Describe in Natural Language" entry point to CharacterWorkshop

**File to modify:** `frontend/src/pages/CharacterWorkshop.tsx`

Add a second way to create a character alongside the existing blank form. Specifically:

1. When the user clicks **"+ Add Character"**, show a choice modal:
   - **"Write a description"** — opens a textarea for free text
   - **"Fill out form"** — opens the existing drawer (current behavior)

2. If "Write a description" is chosen, show a modal with:
   - A large `<textarea>` with placeholder: `"Describe your character freely. Include their name, age, appearance, personality, relationships, goals, and anything else relevant. The AI will extract the details for you."`
   - A **"Parse Character"** button
   - Below the button, the parsed `CharacterProfile` is shown as a preview in the existing drawer form (pre-filled)
   - The author can then edit any field before saving

**New API call to add** in `frontend/src/api/client.ts`:
```typescript
export async function parseCharacter(
  text: string,
  existingCharacterIds: string[]
): Promise<CharacterProfile> {
  return request<CharacterProfile>('/api/parse/character', {
    method: 'POST',
    body: { text, existing_character_ids: existingCharacterIds },
  })
}

export async function parseWorld(text: string): Promise<WorldLore> {
  return request<WorldLore>('/api/parse/world', {
    method: 'POST',
    body: { text },
  })
}
```

**New state to add** in `CharacterWorkshop`:
```typescript
const [parseMode, setParseMode] = useState(false)         // show the parse modal
const [parseText, setParseText] = useState('')             // author's free text
const [parsePending, setParsePending] = useState(false)   // loading state
```

**New UI flow:**
```tsx
// Replace the current single "Add Character" button behavior:
<Button onClick={() => setParseMode(true)}>+ Add Character</Button>

// New modal for choosing entry method
<Modal open={parseMode} onClose={() => setParseMode(false)} title="Add Character">
  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
    <TextArea
      label="Describe your character"
      placeholder="Write freely about your character..."
      rows={8}
      value={parseText}
      onChange={e => setParseText(e.target.value)}
    />
    <Button
      loading={parsePending}
      onClick={async () => {
        setParsePending(true)
        try {
          const existingIds = project.characters.map(c => c.id)
          const parsed = await api.parseCharacter(parseText, existingIds)
          setEditing(parsed)   // opens the existing drawer, pre-filled
          setIsNew(true)
          setParseMode(false)
        } catch (err) {
          fromError(err)
        } finally {
          setParsePending(false)
        }
      }}
    >
      Parse with AI
    </Button>
    <Button variant="ghost" onClick={() => { setEditing(blankCharacter()); setIsNew(true); setParseMode(false) }}>
      Fill out form manually
    </Button>
  </div>
</Modal>
```

---

### 1.4 Frontend: Add "Describe your world" panel to WorldBuilder

**File to modify:** `frontend/src/pages/WorldBuilder.tsx`

Add a new "Quick Setup" tab (as the first tab) with a single large textarea and a parse button. This tab is shown first for new projects with an empty world.

```tsx
// Add to the TABS array at the top of the component:
const TABS = ['quick-setup', 'overview', 'rules', 'locations'] as const

// New Quick Setup tab content:
{tab === 'quick-setup' && (
  <Panel>
    <p>Describe your world freely. The AI will extract the overview, rules, and locations for you.</p>
    <TextArea
      rows={12}
      placeholder="e.g. 'A dark fantasy world set in the late medieval era. Magic exists but is rare and dangerous...'"
      value={worldParseText}
      onChange={e => setWorldParseText(e.target.value)}
    />
    <Button loading={worldParsePending} onClick={handleParseWorld}>
      Parse with AI
    </Button>
    {/* After parsing, show a diff preview: what changed vs current world */}
  </Panel>
)}
```

The `handleParseWorld` function calls `api.parseWorld(worldParseText)` and then calls `api.updateWorld(parsed)` to save.

---

## Phase 2: AI-Driven Episode Planning

### 2.1 New Backend Endpoint: `POST /api/episodes/plan-all`

**File to modify:** `backend/storyweaver/api/episodes.py`

This endpoint accepts a list of one-line episode summaries and generates detailed `EpisodePlan` objects for all of them at once.

```python
class PlanAllRequest(BaseModel):
    summaries: list[str]   # one per episode, in order
    # Optional: override existing episodes or create new ones
    replace_existing: bool = False

class PlanAllResponse(BaseModel):
    episodes: list[Episode]  # episodes with author_storyline filled + status='planned'

@router.post("/episodes/plan-all", response_model=PlanAllResponse)
def plan_all_episodes(body: PlanAllRequest, project: Project = Depends(get_project)):
    """
    Batch-create episodes from one-line summaries.
    Each summary is expanded by the LLM into a full author_storyline.
    The Director agent is NOT run yet — that happens per-episode on approval.
    """
    episodes = []
    for i, summary in enumerate(body.summaries, start=1):
        expanded = _expand_summary(summary, project, episode_number=i)
        episode = Episode(
            episode_number=i,
            author_storyline=expanded,
            status='queued',
        )
        episodes.append(episode)
    # Persist
    ...
    return PlanAllResponse(episodes=episodes)
```

The `_expand_summary` function calls the LLM with a prompt like:
```
You are a story planning assistant for the novel "{project.world.title}".
The author has written a one-line summary for episode {n}:

"{summary}"

The cast: {character_summaries}
The world: {world_overview}
Previous episodes (for continuity): {prior_episode_summaries}

Expand this into a detailed episode outline (3-4 paragraphs) that:
- Specifies which characters appear
- Describes the main conflict or event
- Notes the emotional arc of the episode
- Suggests the ending beat

Write in Korean. Return only the expanded outline text.
```

---

### 2.2 New Frontend Page: `StoryPlanner.tsx`

**File to create:** `frontend/src/pages/StoryPlanner.tsx`

This page replaces the current "write one episode at a time" flow. The workflow is:

1. Author opens the Planner
2. Author sees a numbered list of text inputs (one per episode)
3. Author writes one-line summaries (or a full paragraph) for each episode
4. Author clicks **"Generate Episode Plans"**
5. LLM expands each summary into a detailed plan
6. Author reviews each plan and can edit the expanded text
7. Author clicks **"Approve All"** or approves episode by episode
8. Approved episodes go to the queue with `status: 'queued'` and the full `author_storyline`

**Component structure:**
```tsx
export function StoryPlanner() {
  const [summaries, setSummaries] = useState<string[]>(['', '', ''])  // start with 3 rows
  const [plans, setPlans] = useState<Episode[] | null>(null)
  const [generating, setGenerating] = useState(false)
  const [approved, setApproved] = useState<Set<number>>(new Set())

  async function handleGeneratePlans() {
    setGenerating(true)
    const result = await api.planAllEpisodes(summaries.filter(Boolean))
    setPlans(result.episodes)
    setGenerating(false)
  }

  return (
    <div>
      {/* Step 1: Summary input grid */}
      {!plans && (
        <>
          {summaries.map((s, i) => (
            <div key={i}>
              <label>Episode {i + 1}</label>
              <TextArea
                rows={2}
                placeholder="One-line summary, e.g. 'Jimin discovers the hidden letter and confronts Yuna'"
                value={s}
                onChange={e => {
                  const next = [...summaries]
                  next[i] = e.target.value
                  setSummaries(next)
                }}
              />
            </div>
          ))}
          <Button onClick={() => setSummaries([...summaries, ''])}>+ Add Episode</Button>
          <Button loading={generating} onClick={handleGeneratePlans}>
            Generate Episode Plans
          </Button>
        </>
      )}

      {/* Step 2: Review generated plans */}
      {plans && plans.map((episode, i) => (
        <Panel key={episode.episode_number}>
          <h3>Episode {episode.episode_number}</h3>
          <TextArea
            rows={8}
            value={episode.author_storyline}
            onChange={e => {
              const next = [...plans]
              next[i] = { ...episode, author_storyline: e.target.value }
              setPlans(next)
            }}
          />
          <Button
            variant={approved.has(i) ? 'accent' : 'default'}
            onClick={() => {
              const next = new Set(approved)
              next.has(i) ? next.delete(i) : next.add(i)
              setApproved(next)
            }}
          >
            {approved.has(i) ? 'Approved' : 'Approve'}
          </Button>
        </Panel>
      ))}

      {plans && (
        <Button onClick={handleApproveAll}>
          Save Approved Episodes to Queue ({approved.size})
        </Button>
      )}
    </div>
  )
}
```

**Register the new page** in `frontend/src/App.tsx`:
```tsx
import { StoryPlanner } from '@/pages/StoryPlanner'
// In <Routes>:
<Route path="planner" element={<StoryPlanner />} />
```

**Add to navigation** in `frontend/src/components/AppLayout.tsx` (or wherever nav links live).

---

### 2.3 New API call in `client.ts`

```typescript
export async function planAllEpisodes(summaries: string[]): Promise<{ episodes: Episode[] }> {
  return request<{ episodes: Episode[] }>('/api/episodes/plan-all', {
    method: 'POST',
    body: { summaries, replace_existing: false },
  })
}
```

---

## Phase 3: Fix Missing Prompt Fields

This phase is independent and can be merged before or after Phases 1–2.

### 3.1 Add `age`, `gender`, `backstory`, `role` to Character Agent prompt

**File to modify:** `backend/storyweaver/agents/character.py`

Find the function that builds the character's system prompt (likely `build_system_prompt` or `_character_system_prompt`). Add the missing fields:

```python
def build_system_prompt(character: CharacterProfile, ...) -> str:
    # EXISTING fields already included:
    # name, personality_summary, traits, speech_style, values, goals, secrets, relationships

    # ADD THESE:
    age_line = f"Age: {character.age}" if character.age else ""
    gender_line = f"Gender: {character.gender}" if character.gender else ""
    backstory_line = f"Backstory:\n{character.backstory}" if character.backstory else ""
    role_line = f"Story role: {character.role}" if character.role else ""

    return f"""
You are {character.name}.
{role_line}
{age_line}
{gender_line}

Personality: {character.personality_summary}
{backstory_line}

Speech style: {character.speech_style}
...
"""
```

**Important note on age and speech style:** After adding `age`, update the speech style guidance in the prompt to say:
```
When speaking to characters significantly older than you, use formal speech (존댓말).
When speaking to peers or younger characters, use informal speech (반말) unless your speech_style says otherwise.
Your speech_style: {character.speech_style}
```

### 3.2 Add relationship context to Writer Agent

**File to modify:** `backend/storyweaver/agents/writer.py`

Find `_character_sheets()` or the equivalent. Add relationships between the characters present in the scene:

```python
def _character_sheets(characters: list[CharacterProfile], present_ids: list[str]) -> str:
    char_map = {c.id: c for c in characters}
    blocks = []
    for c in characters:
        if c.id not in present_ids:
            continue
        # EXISTING: name, appearance, personality_summary, speech_style
        # ADD: relationships with others in this scene
        rels = context.format_relationships(c, present_ids, char_map)
        blocks.append(f"""
### {c.name}
Age: {c.age or 'unknown'}
Appearance: {c.appearance}
Personality: {c.personality_summary}
Speech style: {c.speech_style}
Relationships with others in this scene:
{rels}
""")
    return "\n".join(blocks)
```

---

## File Change Summary

### New Files
| File | Purpose |
|---|---|
| `backend/storyweaver/api/parse.py` | `POST /api/parse/character` and `POST /api/parse/world` |
| `frontend/src/pages/StoryPlanner.tsx` | New episode planning page |

### Modified Files
| File | Change |
|---|---|
| `backend/storyweaver/api/__init__.py` | Register `parse.router` |
| `backend/storyweaver/api/episodes.py` | Add `POST /api/episodes/plan-all` |
| `backend/storyweaver/agents/character.py` | Add `age`, `gender`, `role`, `backstory` to prompt |
| `backend/storyweaver/agents/writer.py` | Add relationships + age to character sheets |
| `frontend/src/api/client.ts` | Add `parseCharacter()`, `parseWorld()`, `planAllEpisodes()` |
| `frontend/src/pages/CharacterWorkshop.tsx` | Add "describe in natural language" entry modal |
| `frontend/src/pages/WorldBuilder.tsx` | Add "Quick Setup" tab with free-text parse |
| `frontend/src/App.tsx` | Register `/planner` route |
| `frontend/src/components/AppLayout.tsx` | Add "Story Planner" nav link |

---

## Implementation Order

1. **Phase 3 first** — Small, self-contained, high-value. Fix `character.py` and `writer.py`. No new UI needed.
2. **Phase 1 backend** — Create `parse.py` and test via `curl` or the existing test harness.
3. **Phase 1 frontend** — Add the parse modal to `CharacterWorkshop.tsx` and the Quick Setup tab to `WorldBuilder.tsx`.
4. **Phase 2 backend** — Add `plan-all` endpoint to `episodes.py`.
5. **Phase 2 frontend** — Build `StoryPlanner.tsx` and wire it into the nav.

---

## Testing Each Change

### Phase 3 (prompt fields)
```python
# Add to test.py — check that age appears in the prompt:
from storyweaver.agents.character import build_system_prompt
prompt = build_system_prompt(harry, ...)
assert "17" in prompt
assert "직접적이고 솔직하다" in prompt
```

### Phase 1 (parse endpoints)
```bash
curl -X POST http://localhost:8000/api/parse/character \
  -H "Content-Type: application/json" \
  -d '{"text": "Ji-min is a 19-year-old art student with short black hair. She is determined but socially anxious. Her best friend is Yuna.", "existing_character_ids": []}'
```
Expected: a valid `CharacterProfile` JSON with `id`, `name`, `age=19`, populated `relationships`.

### Phase 2 (plan-all endpoint)
```bash
curl -X POST http://localhost:8000/api/episodes/plan-all \
  -H "Content-Type: application/json" \
  -d '{"summaries": ["Jimin meets Yuna for the first time", "The secret letter is discovered"]}'
```
Expected: two `Episode` objects with expanded `author_storyline` and `status: "queued"`.
