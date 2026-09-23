# The Concept Session — Implementation Plan

**Status:** specification. Nothing here is built yet.
**Language:** this document is English; all author-facing strings and all model
output stay Korean, as the rest of the app already is.

**Companion:** `docs/implementation_plan.md` (the wiki and the chronicle). This
plan writes into the structures that one built, and assumes all five of its
phases are in place. They are.

---

## 1. What is missing

Every path into this app starts from something the author has already written.

| Entry point | Requires |
|---|---|
| `POST /api/parse/world` | a non-empty paragraph from the author |
| `POST /api/parse/character` | a non-empty paragraph from the author |
| `POST /api/episodes` | `author_storyline: str = Field(min_length=1)` |
| `POST /api/episodes/plan-all` | `summaries`, `min_length=1`, each line non-blank |

The parse stage is not merely unhelpful at originating — it is **instructed not
to**. It runs at temperature `0.1`, the coldest setting in the app, and its
prompt says:

> Infer as much as the description genuinely implies, and no more. Where it says
> nothing, use empty lists and null — an invented detail is worse than a blank
> field, because the author will not know it was invented.

That is the right instruction for a transcriber. It is the wrong one for a
collaborator. Nothing in the app proposes a premise, a cast, or an arc.

Of the ten LLM stages in `STAGE_TEMPERATURES`, every one takes something and
transforms it. None decides what the story is.

---

## 2. What this adds

A **concept session**: the author opens it with nothing (or with a hint), the
model proposes whole concepts, and the two of them refine one in free text until
the author is satisfied. Committing it fills in the world, the cast, the work's
arc, and a rough line per episode — all of it editable afterwards, because all
of it lands as the first entry in a chronicle chain rather than as a decision.

```
   (optional seed)          "학원물인데 오컬트가 섞였으면"
          ↓
   propose                  3 concepts, each a logline + world + cast + arc
          ↓
   the author picks one
          ↓
   refine  ◄──────┐         free text: "주인공을 더 어리게"
          ↓       │         the model returns a revised concept, changes marked
          └───────┘         as many times as the author wants
          ↓
   commit                   world · cast · story document · episode queue
```

### 2.1 The one genuinely new thing

**The app has never held a multi-turn exchange with a model.** All twenty
`.invoke()` calls are one-shot; the single `.stream()` is LangGraph advancing a
graph, not a conversation. There is no session, no message history, no chat
surface anywhere in the codebase.

Everything else here attaches to machinery that already exists.

### 2.2 Refinement is not chat

The refinement loop is **propose → react → revise**, not a chat transcript. That
is the pattern the app already uses twice — plan approval, and chronicle review —
and it has a property a chat does not: **the concept itself carries the state**,
so the model is sent the current concept plus this one instruction, never the
whole conversation.

This matters because the author refines until satisfied, with no cap. Replaying
a transcript would make the fiftieth refinement cost twenty times the first. With
the concept as the state, the fiftieth costs what the first did.

The transcript is still **stored** — the author wants to see what they asked for
and how it changed — it simply is not **sent**.

---

## 3. Where the output goes

Nothing here invents a new home for anything. Each part of a concept lands in a
structure that already exists and is already editable.

| Concept part | Lands in | Editable via |
|---|---|---|
| Title, genre, tone, era, overview, factions, rules, places | `WorldLore` | 세계관 빌더, and the wiki |
| Characters | `CharacterProfile[]` | 캐릭터 워크숍, and the wiki |
| Logline, premise, arc, planned ending | a new `story` wiki subject | the wiki |
| One rough line per episode | `Episode.author_storyline` in the queue | 에피소드 큐 |

Because the wiki's write path appends rather than overwrites, a concept-stage
value becomes **the first entry in its chain** and every later edit — by the
author or by a chapter — becomes the next one. That is the whole reason the
author asked for the output to land in the wiki: it is the surface where nothing
is fixed.

### 3.1 The per-episode lines stay rough on purpose

The concept session writes **one abstract line per episode**, matching the arc.
It does not write detailed episode plans, because the app already plans each
episode in detail immediately before writing it, and the author approves that
plan. That gate is unchanged:

```
rough line  →  [기획서 만들기 / Director]  →  scenes  →  [author approves]  →  prose
```

The Director is already built for this. `prompts/director.md` carries **RULE 2 —
Expand A Sparse Outline**:

> If the storyline is brief — a single sentence, or one bare event — do not
> deliver one thin scene. Build it into a full episode arc: opening/aftermath,
> inciting movement, the core event, falling action and hook.

So a one-line storyline is not a degraded input to the existing pipeline. It is
the input that rule was written for.

---

## 4. The story document

### 4.1 Why a new subject type

The wiki currently holds `character | world | location | rule | faction`. A
logline, a premise, a three-act arc and a planned ending belong to none of them.

They cannot go on the **world** page, and the reason is the important part.

### 4.2 The arc must never reach a character

`context.format_world_summary(world)` is rendered into **five** prompts:
`director.py`, `character.py`, `lore_checker.py`, `writer.py` and the summarizer.
Putting the arc into `WorldLore` would therefore put the planned ending into
every character's system prompt — and **characters would act as though they knew
how the story ends.**

That failure is quiet. It does not raise; it just produces prose where nobody is
surprised by anything.

So the story document is read by **the planning stages only**:

| Stage | Sees the arc? | Why |
|---|---|---|
| Concept session | yes | it wrote it |
| Story Planner (`_expand_summary`) | yes | it is expanding toward it |
| Director (`decompose_episode`) | yes | §4.3 |
| Character agent | **no** | would play the ending |
| Writer | **no** | would foreshadow knowingly |
| Lore Checker | **no** | would flag the story for not having got there yet |
| Summarizer | **no** | records what happened, not what is planned |

The test suite must assert the four `no` rows, not only the `yes` rows. A leak
here is invisible in any single chapter.

### 4.3 The Director should see the arc

Today the Director is given the world, its rules, its locations, the cast, the
memory context and **this episode's storyline**. It does not know where the work
is going.

Asking it to expand a one-line storyline into a full episode (RULE 2) without
showing it the arc means the expansion can drift off the arc — plausibly, and
invisibly, one episode at a time. Since the story document now exists, the
Director gets a short arc digest.

Kept short deliberately: the Director needs the direction, not the ending in
detail.

### 4.4 Sections

```python
STORY_SECTIONS = [
    SectionSpec(key="logline",   title="로그라인",   order=10),
    SectionSpec(key="premise",   title="기획 의도",  order=20),
    SectionSpec(key="arc",       title="전체 아크",  order=30),
    SectionSpec(key="ending",    title="계획된 결말", order=40),
    SectionSpec(key="episodes",  title="회차 구상",  kind="log", order=50),
    SectionSpec(key="decisions", title="기획 기록",  kind="log", order=60),
]
```

All unbound: there is no typed model behind a story document, so these are prose
sections like an author's own. `decisions` is a log of what was asked for during
the session and what changed — the record of how the concept came to be.

`SubjectType` gains `"story"`, and the subject id is the constant `"story"`, as
`world` already does.

---

## 5. Data model

New module `backend/storyweaver/models/concept.py`:

```python
class ConceptCharacter(BaseModel):
    """A proposed character, before it is a CharacterProfile."""
    name: str
    role: str = Field(description="주인공, 적대자 / 악역, 조연, … one of parse.ROLES")
    age: int | None = None
    gender: str | None = None
    appearance: str = ""
    personality: str = Field(description="2-3 sentences")
    speech: str = Field(description="how they talk")
    goal: str = ""
    secret: str = ""
    relationships: list[str] = Field(
        default_factory=list, description="'시월 — 경계하는 상대' 형식"
    )

class ConceptEpisode(BaseModel):
    """One episode, at the resolution the arc needs and no finer."""
    number: int
    line: str = Field(description="one or two sentences, not a plan")

class StoryConcept(BaseModel):
    """One whole proposal. This is the unit the author picks and refines."""
    logline: str
    title: str
    genre: str
    tone: str
    era: str | None = None
    premise: str = Field(description="2-3 paragraphs: the world and the hook")
    arc: str = Field(description="beginning, middle, end — 3-5 paragraphs")
    ending: str = Field(description="where it is meant to land")
    rules: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    characters: list[ConceptCharacter] = Field(default_factory=list)
    episodes: list[ConceptEpisode] = Field(default_factory=list)

class ConceptTurn(BaseModel):
    """One round of the session, kept for the author to look back at."""
    turn: int
    instruction: str = ""        # empty on the opening proposal
    created_at: datetime
    changed: list[str] = Field(default_factory=list)  # human-readable, §6.3

class ConceptSession(BaseModel):
    seed: str = ""
    status: Literal["proposing", "refining", "committed"] = "proposing"
    proposals: list[StoryConcept] = Field(default_factory=list)  # the opening spread
    chosen: StoryConcept | None = None
    turns: list[ConceptTurn] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None = None
```

`StoryConcept` deliberately holds **strings, not typed models** for rules,
locations and factions. The concept stage is about whether the idea is right; ids
and hierarchies are settled at commit (§8), where the existing `parse.py`
helpers (`_slugify`, `_unique_id`) already do that work.

---

## 6. The agent

New module `backend/storyweaver/agents/concept.py`, prompts
`prompts/concept_propose.md` and `prompts/concept_refine.md`.

New stage in `STAGE_TEMPERATURES`:

```python
# Inventing a story from nothing. The warmest stage in the app, and the only
# one whose job is to originate rather than to transform.
"concept": 0.9,
```

### 6.1 Proposing

```python
def propose(seed: str = "", count: int = 3, llm=None) -> list[StoryConcept]
```

One model call returning `count` concepts. They must differ **in kind**, not in
detail — three variations on one premise is a worse spread than three premises.
The prompt says so explicitly, and names the axes to differ on: the central
conflict, whose story it is, and what the reader is there for.

With an empty `seed`, the spread runs across genres. With a seed, all three aim
at it and differ underneath it.

### 6.2 Refining

```python
def refine(concept: StoryConcept, instruction: str, llm=None) -> tuple[StoryConcept, list[str]]
```

Sent: the current concept and this one instruction. **Not** the transcript
(§2.2).

The prompt's central constraint:

> Change what the author asked for, and what genuinely must follow from it.
> Nothing else. If they asked for a younger protagonist, their age changes and
> anything that depended on their age changes with it — do not also rewrite the
> ending, rename the world, or replace a character they never mentioned.

This is the same class of rule as the chronicle's justification gate, and for the
same reason: an author refining forty times cannot check forty whole concepts,
so each round has to be small enough to read.

### 6.3 `changed`

The second return value is a list of human-readable lines — `"주인공 나이 17 →
14"`, `"세계관 제목 그대로"` — produced by diffing the returned concept against
the one that was sent. Computed in code, not asked of the model: a model asked
to report its own changes will describe what it meant to do.

---

## 7. Storage

New `ConceptStore` in `backend/storyweaver/concept_store.py`, one session per
project:

```
data/state/concept_session.json
```

Same construction as the other stores: JSON, written through
`storage.write_text_atomic`. Reached through `deps.get_store().state_dir`, not
through `MemoryManager` — a concept session is work in progress, not something
the story remembers.

```python
class ConceptStore:
    def __init__(self, data_dir: Path | str)
    def load(self) -> ConceptSession | None
    def save(self, session: ConceptSession) -> ConceptSession
    def clear(self) -> None
```

One session at a time. An author concepting two novels at once needs multi-project
support (`docs/multi_project_support.md`), which is a separate and larger job.

A committed session is kept, not deleted — it is the record of how the work
began, and §4.4's `decisions` section links to it.

---

## 8. Committing

`POST /api/concept/commit` is the only endpoint here that writes to the project.
It is the riskiest call in this plan: it touches the world, the cast, the wiki
and the queue in one go.

Order, and why:

1. **Refuse if the project is not empty.** A concept session overwrites the world
   and adds a cast; running it over an existing novel would quietly merge two
   stories. If `project.world.overview` is non-empty or `project.characters` is
   non-empty, return **409** and say so. Starting over is `ProjectStore.reset()`,
   which already exists and which the author already knows.
2. **World.** Ids for rules and locations via `parse._slugify` / `_unique_id`;
   then the same three-step write `applyParsedWorld` does — `PUT /api/world`,
   then `POST /api/world/rules` per rule, then `.../locations` per location.
   (The header endpoint takes only the header; rules and locations are separate
   upserts. Writing the whole object to `PUT /api/world` looks like it worked and
   silently drops both.)
3. **Characters.** `ConceptCharacter → CharacterProfile`, ids from the name via
   `_unique_id` against the ids already taken. Relationship strings
   (`"시월 — 경계하는 상대"`) resolve against the cast being created; one that
   names nobody is dropped with a warning rather than pointing at an id that does
   not resolve.
4. **The story document.** `logline`, `premise`, `arc`, `ending` as author
   entries on the `story` subject; each `ConceptEpisode` line as an entry in the
   `episodes` log section; a `decisions` entry per turn of the session.
5. **The queue.** One `project.add_episode(line)` per `ConceptEpisode`, in order.
6. **Mark the session committed** and stamp `committed_at`.

Steps 2–5 run inside one `deps.write_lock()`. Partial commits are the failure to
avoid: half a cast and no world is worse than nothing, because the author cannot
tell what happened by looking.

No model calls. Everything was decided during refinement.

---

## 9. API

New router `backend/storyweaver/api/concept.py`, registered in
`api/__init__.py`'s `ROUTERS` list — **both** the import block and the list; the
file has two places and missing either one is a silent 404.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/concept` | the session, or `null` — this is what survives a browser restart |
| POST | `/api/concept/propose` | `{seed?, count?}` → opens or restarts a session |
| POST | `/api/concept/choose` | `{index}` → picks one of the proposals |
| POST | `/api/concept/refine` | `{instruction}` → one revision, returns the concept and `changed` |
| POST | `/api/concept/commit` | §8 |
| DELETE | `/api/concept` | discard the session |

`/refine` on a session with no `chosen` is **409**. `/commit` on a non-empty
project is **409** (§8.1). An empty `instruction` is **422** — a refinement with
nothing asked would spend a call to return roughly what it was given.

---

## 10. Frontend

| File | Action |
|---|---|
| `frontend/src/types/storyweaver.ts` | `StoryConcept`, `ConceptCharacter`, `ConceptEpisode`, `ConceptSession`, `ConceptTurn` |
| `frontend/src/api/client.ts` | the §9 calls |
| `frontend/src/pages/ConceptStudio.tsx` | CREATE — the session |
| `frontend/src/components/ConceptCard.tsx` | CREATE — one proposal, and the chosen concept |
| `frontend/src/App.tsx` | `<Route path="concept" element={<ConceptStudio />} />` |
| `frontend/src/components/AppLayout.tsx` | `{ to: '/concept', label: '작품 기획', icon: Lightbulb }` — **first** in `NAV`, above 세계관 빌더 |
| `frontend/src/pages/Dashboard.tsx` | on an empty project, point at 작품 기획 first |

### 10.1 The screen

Three states, one route.

**Proposing** — a seed box that may be left empty, and a button. Then three
cards side by side: logline, genre and tone, the cast in one line each, and the
arc folded away. One "이걸로 시작" per card.

**Refining** — the chosen concept in full, and a free-text box under it. After
each round the `changed` lines appear above the concept, the way the chronicle
review shows what a chapter recorded. The turn history is reachable but folded:
the current concept is what matters, and forty turns of history would bury it.

**Committing** — a confirm dialog naming exactly what will be created: *"세계관
1개, 인물 5명, 규칙 3개, 장소 4곳, 회차 구상 12개."* Then a summary of where
each part went, with links.

### 10.2 House rules

Stated because earlier plan documents in this repo got them wrong and each cost
a fix: `EmptyState` requires an `icon`; `IconButton` takes `title` and `variant`,
not `label`/`tone`; `Modal` and `Drawer` render through `createPortal`; there are
no `var(--color-muted)` / `var(--color-border)` CSS variables — use the Tailwind
tokens (`text-ink-muted`, `border-line`); the episode-creating client function is
`addEpisode(storyline, title, pacing)`.

---

## 11. Deleting a concept-stage character

The author's requirement — *"기획 단계의 캐릭터가 나중에 삭제될 수도 있어야
해"* — lands on a gap that exists today.

`delete_character` removes the character from the project and drops relationships
pointing at them. **It does not touch the chronicle.** So a character invented
during concepting and deleted later leaves a wiki page behind, with its whole
history, belonging to nobody.

Policy, decided by whether the story ever used them — implemented as
`wiki.forget_subject`, called from `delete_character`:

- **No episode entries** — they were a concept-stage mistake. Remove the page and
  the chain with it.
- **Episode entries exist** — they were in the story. Keep the page, mark it
  삭제된 인물, and exclude it from prompts. That someone was written out is part
  of the record.

`ChronicleStore.drop_subject(subject_type, subject_id)` covers the first case,
and `episode_entries()` is what decides between them — any episode entry at all,
including one still awaiting review, counts as the story having used them.

The second case is `retired` / `retired_note` on `WikiSubject`, surfaced on
`SubjectPage` and `SubjectRow` and shown as a 삭제된 인물 badge. The retired
page also pins its `title`, because a page title is normally looked up from the
cast the character is no longer in. Nothing has to filter them out of prompts:
the agents are given the project's cast, and they are not in it.

---

## 12. Phases

**Phase 1 — the story document.** `SubjectType` gains `"story"`,
`STORY_SECTIONS`, and the wiki renders it. Pure addition; a page with nothing on
it. *Done when:* an author can write a logline and an arc by hand in the wiki and
see it chronicled.

**Phase 2 — the agent.** `models/concept.py`, `agents/concept.py`, the two
prompts, the `concept` stage. No API, no UI. *Done when:* `propose()` returns
three genuinely different concepts and `refine()` changes what was asked for and
little else — verified against a stubbed model for shape, and once against the
real one for quality, because this is the one thing here a stub cannot judge.

**Phase 3 — session and API.** `ConceptStore`, the §9 endpoints, commit. *Done
when:* a session survives a restart, and committing fills world, cast, story
document and queue in one locked write.

**Phase 4 — the screen.** Propose, refine, commit. *Done when:* an author starts
from an empty project and ends with a queue they can generate from.

**Phase 5 — the seams.** The Director gets the arc digest (§4.3), and character
deletion cleans up after itself (§11).

Phases 1–3 are invisible to the author; phase 4 is the whole feature as they
experience it; phase 5 is what keeps it honest over a long serial.

---

## 13. Tests

Following the repo's conventions: behaviour-named, no live model calls
(`conftest._no_live_model_calls` patches `llm.build_model`), the real `data/`
never touched.

- **The arc does not leak.** After a story document exists, assert the arc and
  the planned ending appear in the Director's prompt and appear in **neither**
  `build_system_prompt` (character), the Writer's sheets, the Lore Checker's
  prompt, nor the summarizer's. This is the quiet one; it gets the most tests.
- **Refinement is bounded.** The prompt sent for turn 50 is the same size as
  turn 1 — the transcript is stored, not sent.
- **Session.** Survives a reopen; `/refine` before `/choose` is 409; an empty
  instruction is 422.
- **Commit.** Refuses a non-empty project with 409; on success creates world,
  cast, story document and queue; ids are unique and slugified; a relationship
  naming nobody is dropped rather than dangling; a failure part-way leaves
  nothing behind.
- **Korean ids.** A cast proposed with Korean names gets distinct ids and
  distinct chronicle files — the same property verified for the rest of the app.
- **The story page.** Sections render; an author edit appends rather than
  overwrites; the `episodes` log accumulates in order.

---

## 14. Risks

**The arc leaking into prose.** §4.2. Characters who know the ending stop being
surprised, and nothing in any single chapter looks wrong. Tested hardest.

**Commit is the one destructive call.** It writes four structures at once. It is
refused on a non-empty project and runs under one lock; without both, a
mis-click costs an existing novel.

**Refinement drift.** Forty small revisions can walk a concept somewhere the
author never chose, each step reasonable. The `changed` list is the mitigation —
per round it is short enough to actually read — and the turn history is there to
look back through.

**Quality is the part a stub cannot check.** Everything else here is verifiable
against a stubbed model. Whether three proposals are genuinely different, and
whether a refinement changes only what was asked, needs one real run. Budget for
it in phase 2 rather than discovering it in phase 4.

---

## 15. Decisions already made

1. The model proposes first, from nothing; the author refines from there.
2. Refinement is free text, unlimited, until the author is satisfied.
3. The seed box may be left empty.
4. The concept produces the work's arc **and** a rough line per episode — both
   editable afterwards.
5. Per-episode lines stay abstract. Detailed planning stays where it is: before
   each chapter, approved by the author.
6. That approval gate is unchanged.
7. Output lands in the wiki so the author can change any of it later.
8. The session survives a browser restart.
9. The arc reaches planning stages only, never a character or the Writer.
10. Concept-stage characters can be added to, changed, and deleted afterwards.

## 16. Open questions

1. **`count` for proposals** — three is proposed. More costs one call either way
   (they come back together) but more tokens, and a spread of six is harder to
   read than three.
2. **Re-running `propose` after choosing** — does asking for a fresh spread
   discard the refinement history, or keep it alongside? Discarding is simpler;
   keeping is kinder to an author who explores and comes back.
3. **Episode count** — should the author say how many episodes the arc covers,
   or does the model decide from the shape of the story?
4. **Committing into a non-empty project** — refused outright in §8.1. If that
   turns out to be too strict in practice, the alternative is a merge review, at
   considerably more cost.
