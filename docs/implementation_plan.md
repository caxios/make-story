# The Wiki and the Chronicle — Implementation Plan

**Status:** specification. Nothing here is built yet.
**Language of the artefact:** this document is English; all author-facing UI
strings and all prompt output stay Korean, as the rest of the app already is.

---

## 1. The problem

A serial novel's settings are not constants. A character who begins prickly
becomes generous after twenty episodes with people who wore him down; a gate
that worked is attacked, breaks, and is later repaired; a rule that held is
abolished. StoryWeaver currently cannot express any of that.

Three concrete failures today:

1. **Settings are typed once and then frozen.** `CharacterProfile.appearance`
   is whatever the author typed into a form. If episode 1 cuts the character's
   hair, nothing records it, and episode 2 grows it back.
2. **What memory does record, it overwrites.** `CharacterMemory.internal_state`
   and `relationship_updates` hold only the latest value. The trajectory — the
   thing an author needs when auditing a finished arc — is destroyed on every
   write. `StoryMemory.world_lore_updates` is a bare `list[str]` with no episode
   attribution at all.
3. **Some authored fields reach no prompt.** `WorldLore.factions` and
   `WorldLore.additional_lore` are stored, exported, and seeded into the vector
   store, but no agent prompt includes them. `additional_lore` has no React UI
   at all — the input path was lost in the Streamlit → Vite migration. An author
   can write a faction and the model will never hear of it.

There is one exception that already works, and it is the model for everything
below: **plot threads**. `PlotThread` carries `opened_in_episode`,
`last_referenced_episode`, `resolved_in_episode`, and a list of per-episode
`events`. It is already a chronicle. The work is to generalise it.

---

## 2. The concept

### 2.1 One store, two faces

The wiki is **not** a second store that syncs with the database. Two stores
that sync will drift, and the moment an author edits a page while a generation
commits a record, neither is authoritative.

Instead: **there is one store, and the wiki and the typed models are two views
of it.** Editing the "외모" section of a character's wiki page *is* editing
`appearance`. There is no synchronisation step, so there is nothing to drift.

### 2.2 The unit is (subject, section)

The chronicle key is not a subject. It is a subject *and one of its sections*:

    (character, "박동혁", "appearance")   → its own ordered chain
    (character, "박동혁", "personality")  → a different chain
    (location,  "차원게이트", "state")     → a different chain

Each chain is an append-only list of entries in chronological order.

### 2.3 An entry

| Field | Meaning |
|---|---|
| `entry_id` | ULID-style sortable id |
| `subject_type` | `character \| world \| location \| rule \| faction` |
| `subject_id` | the id of the subject |
| `section_key` | which section of that subject |
| `source` | `author \| episode` |
| `episode_number` | set when `source == "episode"`, else `null` |
| `sequence` | monotonic integer; the real ordering key (see §2.5) |
| `kind` | `initial \| changed \| added \| revealed \| removed \| restored` |
| `value` | the new value **after** this entry |
| `previous` | the value before it, copied at write time for display |
| `reason` | why it changed — required when `source == "episode"` |
| `created_at` | timestamp |
| `superseded` | `false`, or `true` when an author retracts it (§7.3) |

`previous` is denormalised on purpose: the wiki must render "c → b" without
walking the chain, and the chain is the thing that must never be rewritten.

### 2.4 The author's own writing is an entry

There is no separate "base setting" record. What the author types is simply the
first entry, with `source: "author"` and `kind: "initial"`. A later author edit
appends another entry with `source: "author"`, `kind: "changed"`.

    박동혁 · appearance
      [author] initial   단정한 단발
      [ep 1]   changed   한쪽 눈을 덮은 앞머리   (시월과의 실랑이 중 잘림)
      [author] changed   헝클어진 앞머리         (작가 메모)
      [ep 7]   changed   짧게 친 머리            (사념세계 진입 전 직접 자름)
      ───────────────────────────────────────────
      current = 짧게 친 머리

This single decision satisfies every requirement at once: the original survives
as entry one; no intermediate step is ever deleted; the latest entry always
wins; the author can correct the AI by appending or retracting; and there is
only one place the data lives, so "two-way linkage" needs no machinery.

### 2.5 Ordering

Entries sort by `sequence`, a store-wide monotonic counter assigned at write
time — **not** by `episode_number`, and not by timestamp.

Episode numbers are unusable as an ordering key because `delete_episode` and
`move_episode` both call `project.renumber_episodes()`, so an episode's number
is positional, not an identity. Timestamps are unusable because an author may
edit episode 3's record after episode 7 has been written, and that edit belongs
where the author put it, not at the end.

`episode_number` is kept for display and for grouping, and §7.4 covers keeping
it honest across renumbering.

### 2.6 Two shapes of section

| Shape | Examples | Has a current value? | Fold |
|---|---|---|---|
| **stateful** | appearance, personality, speech, a relationship, a location's state | yes | last non-superseded entry wins |
| **log** | 작중 행적 (what the character did this episode) | no | the entries *are* the content, shown oldest-first |

This is exactly the author's two requirements — "how they changed" and "what
they did" — and they need different rendering and different fold behaviour.

### 2.7 Bound and free sections

| | Bound section | Free section |
|---|---|---|
| Backed by | a field on a typed model | nothing; wiki-only |
| Examples | 외모 → `appearance`, 말투 → `speech_style` | 능력, 과거사, 명대사 |
| Reaches agents as | the typed field it feeds | a labelled prose block in the prompt |
| Lore Checker can cite it | yes, by field | no, only as general context |
| Author may add/delete | delete yes, add no (the set is fixed by the models) | yes, freely |
| AI records into it | yes | **yes** — free sections affect the story too |

Deleting a bound section empties its field. Prompt builders already omit blank
fields, so this degrades cleanly.

---

## 3. Data model

### 3.1 New module: `backend/storyweaver/models/chronicle.py`

```python
SubjectType = Literal["character", "world", "location", "rule", "faction"]
EntrySource = Literal["author", "episode"]
EntryKind   = Literal["initial", "changed", "added", "revealed", "removed", "restored"]
SectionKind = Literal["stateful", "log"]

class ChronicleEntry(BaseModel):
    entry_id: str
    subject_type: SubjectType
    subject_id: str
    section_key: str
    source: EntrySource
    episode_number: int | None = None
    sequence: int
    kind: EntryKind
    value: str
    previous: str = ""
    reason: str = ""
    created_at: datetime
    superseded: bool = False

class SectionSpec(BaseModel):
    """What a section is. Bound sections are declared in code; free ones are data."""
    key: str
    title: str                     # Korean, shown in the wiki
    kind: SectionKind
    bound_field: str | None = None # dotted path into the typed model, or None
    order: int = 0

class WikiSubject(BaseModel):
    """A page. Bound subjects mirror a typed model; free sections live here."""
    subject_type: SubjectType
    subject_id: str
    title: str
    summary: str = ""              # the 개요 paragraph at the top
    free_sections: list[SectionSpec] = Field(default_factory=list)
```

`kind` values earn their keep:

- `revealed` vs `changed` — "시월은 사실 300살이었다" is a reveal to the reader;
  "머리가 잘렸다" is a change in the world. A chronicle that conflates them
  cannot produce an honest timeline.
- `removed` / `restored` — a destroyed ruin, a gate that breaks and is later
  repaired. State can oscillate; the chain must allow it.

### 3.2 Bound section registry

A single table in `backend/storyweaver/wiki/sections.py` maps model fields to
sections. Not configuration — code, so a rename fails a test rather than
silently orphaning a chain.

```python
CHARACTER_SECTIONS = [
    SectionSpec(key="summary",      title="개요",     kind="stateful", bound_field="personality_summary", order=10),
    SectionSpec(key="appearance",   title="외모",     kind="stateful", bound_field="appearance",  order=20),
    SectionSpec(key="personality",  title="성격",     kind="stateful", bound_field="traits",      order=30),
    SectionSpec(key="speech",       title="말투",     kind="stateful", bound_field="speech_style",order=40),
    SectionSpec(key="values",       title="가치관",   kind="stateful", bound_field="values",      order=50),
    SectionSpec(key="goals",        title="목표",     kind="stateful", bound_field="goals",       order=60),
    SectionSpec(key="backstory",    title="과거",     kind="stateful", bound_field="backstory",   order=70),
    SectionSpec(key="relationships",title="인간관계", kind="stateful", bound_field="relationships", order=80),
    SectionSpec(key="secrets",      title="비밀",     kind="stateful", bound_field="secrets",     order=90),
    SectionSpec(key="deeds",        title="작중 행적", kind="log",      bound_field=None,          order=100),
]
```

Equivalent tables for `world` (개요/분위기/시대/세력), `location`
(개요/특징/상태), `rule` (조문/예외), `faction` (개요/구성/작중 행적).

**Relationships are special.** One character has many relationships, so the
section key is parameterised: `relationships:<target_id>`. Each pair gets its
own chain, which is what makes "시월과의 관계: 경계 → 동료 → 연인" render as
one readable history. Per §4 of the author's brief, list-shaped sections are
recorded in time order; no attempt is made to diff list members.

### 3.3 Model changes

| Model | Change | Why |
|---|---|---|
| `Location` | add `status: str = ""` | "파괴됨", "고장" has nowhere to live; `description` is prose, not state |
| `Rule` | add `active: bool = True` | a rule can be abolished mid-story; `statement` cannot express that |
| `WorldLore.factions` | `list[str]` → `list[Faction]` (`id`, `name`, `description`) | a faction needs a page; a bare name cannot have sections |
| `CharacterStateUpdate` | add `field_changes: list[FieldChange]` | today it carries only internal_state / goals / relationships — appearance and the rest have no slot |
| `EpisodeMemory.world_lore_updates` | `list[str]` → `list[LoreUpdate]` (`subject_type`, `subject_id`, `section_key`, `value`, `reason`, `kind`) | strings carry no subject, no episode, no justification |

`FieldChange`: `subject_type`, `subject_id`, `section_key`, `previous`, `value`,
`reason`, `kind`.

Migration is trivial: the project was reset to empty on 2026-09-21, so there is
no stored data in the old shapes. The bundled samples under `data/examples/`
must still load — they are test fixtures — so new fields carry defaults.

---

## 4. Storage

A new `ChronicleStore` in `backend/storyweaver/memory/chronicle_store.py`,
built the same way as `StructuredStore`: JSON under `config.STATE_DIR`, written
through `storage.write_text_atomic`.

- `state/chronicle/<subject_type>/<safe_name>_<digest>.json` — one file per
  subject, holding its entries in `sequence` order.
- `state/chronicle/_sequence.json` — the monotonic counter, bumped under
  `deps.write_lock()`.
- `state/wiki/<subject_type>/<...>.json` — `WikiSubject` records (summary and
  free sections).

**Filenames must use `memory.structured_store._character_filename`'s scheme**
(readable part + 8-char SHA-1 of the NFC-normalised id). That function exists
because the previous ASCII-only scheme collapsed every three-syllable Korean
name onto `character____.json` and five characters overwrote each other for six
episodes. Factor it out to `storage.safe_filename(prefix, raw_id)` and use it
for every subject type. A regression here is silent and destroys exactly the
data this feature exists to keep.

API surface:

```python
class ChronicleStore:
    def append(self, entry: ChronicleEntry) -> ChronicleEntry
    def append_many(self, entries: Sequence[ChronicleEntry]) -> list[ChronicleEntry]
    def chain(self, subject_type, subject_id, section_key) -> list[ChronicleEntry]
    def subject(self, subject_type, subject_id) -> list[ChronicleEntry]
    def by_episode(self, episode_number: int) -> list[ChronicleEntry]
    def retract(self, entry_id: str) -> None            # sets superseded, never deletes
    def edit(self, entry_id: str, **fields) -> ChronicleEntry
    def drop_episode(self, episode_number: int) -> int   # §7.3
    def renumber(self, mapping: dict[int, int | None]) -> int  # §7.4
```

`retract` marks rather than deletes, so a mistaken retraction is recoverable and
the audit trail the author asked for stays complete. The wiki shows retracted
entries struck through, collapsed by default.

---

## 5. The fold

`backend/storyweaver/wiki/fold.py`:

```python
def current_value(store, subject_type, subject_id, section_key) -> str | None:
    """The last non-superseded entry's value, or None if the chain is empty."""

def fold_character(store, base: CharacterProfile) -> CharacterProfile:
    """`base` with every bound section replaced by its chronicle's current value."""

def fold_world(store, base: WorldLore) -> WorldLore
def fold_location(store, base: Location) -> Location
def fold_rule(store, base: Rule) -> Rule
```

Rules:

- A section with no chronicle keeps the model's own value. A fresh project with
  no chronicle folds to exactly what it is today, so the feature is inert until
  it has something to say.
- A section with a chronicle takes the chain's last value **and ignores the
  model field**. An author editing a field goes through the wiki, which appends
  an entry, so this is not a way to lose an edit — but it does mean a direct
  `PUT /api/characters` write to a field that has a chronicle will not take
  effect. Those endpoints must be routed through the wiki write path (§8).
- `relationships` folds by replaying every `relationships:<target>` chain and
  rebuilding the list.
- Folding is memoised per request, keyed by the store's sequence counter.

---

## 6. Where the fold has to be applied

This is the load-bearing change. Every place below reads a raw model today and
must read the folded one. Missing any of them produces a specific, visible bug.

| Call site | Reads | Bug if missed |
|---|---|---|
| `agents/character.py::build_system_prompt` | `speech_style`, `traits`, `relationships`, `appearance` via `_identity_line` | the character acts out a version of themselves the story left behind |
| `agents/writer.py::_character_sheets` | age, gender, role, appearance, personality, speech, relationships | **the haircut grows back in the next episode** |
| `agents/lore_checker.py` | `Speech: {speech_style}`, `format_rules(world.rules)` | **silent and worst:** every scene where the character behaves as they now are is reported as a setting violation, and the pipeline re-runs scenes to "fix" correct prose |
| `agents/director.py` | `format_character_summaries`, `format_rules` | scenes are cast for people who no longer exist in that form |
| `agents/context.py` formatters | traits, relationships, rules, locations | the shared bottom layer; fixing it here covers most callers |
| `memory/manager.py::build_director_context`, `build_character_context`, `build_writer_context`, `_relationship_graph` | character map | recalled memory contradicts the current state |
| `api/episodes.py::_expand_summary` (Story Planner) and `draft_plan` | project cast and world | **the author approves a plan built on stale facts** — the gate that is supposed to catch drift becomes a source of it |

Free sections are appended to the character and world prompts as labelled prose
under a `## 그 밖의 설정` heading. The same mechanism finally carries
`factions` and `additional_lore` into prompts, closing the third failure in §1.

Implementation note: add one helper, `deps.folded_project()`, returning a
`Project` whose world and cast are already folded, and change call sites to take
it. That keeps the fold in one place instead of scattering `fold_*` calls
through four agents.

---

## 7. Recording after an episode

### 7.1 What the summarizer is asked for

`agents/prompts/episode_summarizer.md` gains a section. The existing
`character_updates` and `world_lore_updates` instructions are replaced by one
that asks for **subject, section, before, after, reason, kind** — and gates it:

> For every change, name the moment in this episode that caused it. A change you
> cannot ground in something that happened here is not a change — it is a guess,
> and you must leave it out. The author's setting is where this character
> started, not a cage: a prickly character may soften over episodes of being
> worn down by people who care about him. What is not allowed is a character who
> changes with nothing in the text to earn it.

This is the mechanism that makes "the chronicle wins" safe. The author's point
was never that settings are disposable — it is that they should be allowed to
evolve **when the story has earned it**. `reason` is therefore not decoration;
it is the gate. Entries from an episode with an empty `reason` are rejected at
the API boundary, not merely discouraged in the prompt.

Free sections are listed in the prompt by title with their current value so the
model can record into them (`능력`, `과거사`, …) rather than inventing a place.

### 7.2 The author's second gate

The project already gates *before* writing: 기획서 → author approves → prose.
Recording adds a gate *after*:

```
plan → [author approves] → prose → chronicle proposal → [author approves] → committed
```

Proposals are held as entries with `superseded=true` plus a pending marker, or
in a separate `pending/` file — decided at implementation time; the constraint
is that an unreviewed proposal must never fold into a prompt. The review UI is
the same shape as `components/PlanReview.tsx`: a list, per-item accept or
discard, edit in place before accepting.

Skipping review must be possible for authors who trust it (a setting), because
a gate that is always in the way gets clicked through blindly.

### 7.3 Regeneration

`record_episode_summary` currently **appends** `world_lore_updates` and
interactions with no per-episode replacement, so regenerating episode 3 already
leaves two sets of records for episode 3 today. With a chronicle this is fatal:
"c → b" and "c → d" would coexist in one chain and the fold would pick whichever
landed last.

Therefore: **before recording an episode, drop every chronicle entry for that
episode number** (`ChronicleStore.drop_episode`). Dropping here is real deletion,
not supersession — a regenerated episode's old records describe prose that no
longer exists.

### 7.4 Renumbering

`delete_episode` and `move_episode` renumber the whole queue. After either,
`ChronicleStore.renumber(mapping)` rewrites `episode_number` on affected
entries; entries whose episode was deleted are dropped.

`sequence` is untouched — the chain's order is its own, and a reordering of the
queue does not reorder history that already happened. This is why §2.5 does not
order by episode number.

---

## 8. API

New router `backend/storyweaver/api/wiki.py`, registered in `api/__init__.py`'s
`ROUTERS` list (both the import block and the list — the file has two places).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/wiki/subjects` | every page: type, id, title, section count, last touched episode |
| GET | `/api/wiki/{subject_type}/{subject_id}` | one page: summary, sections in order, each with current value and full chain |
| PUT | `/api/wiki/{subject_type}/{subject_id}/summary` | edit the 개요 |
| POST | `/api/wiki/{subject_type}/{subject_id}/sections` | add a free section |
| PUT | `/api/wiki/{subject_type}/{subject_id}/sections/{key}` | rename / reorder |
| DELETE | `/api/wiki/{subject_type}/{subject_id}/sections/{key}` | delete a section (bound → empties the field) |
| POST | `/api/wiki/{subject_type}/{subject_id}/sections/{key}/entries` | append an author entry — **this is how all setting edits happen now** |
| PUT | `/api/wiki/entries/{entry_id}` | edit an entry's value or reason |
| POST | `/api/wiki/entries/{entry_id}/retract` | mark superseded |
| GET | `/api/wiki/timeline` | all entries across all subjects, by episode — the "history of the work" view |
| GET | `/api/wiki/episodes/{n}/pending` | the proposal awaiting review |
| POST | `/api/wiki/episodes/{n}/pending/apply` | accept selected entries |

Existing `PUT /api/characters` and `PUT /api/world` become thin wrappers that
append author entries, so no write path bypasses the chronicle. `parse.py` and
`applyParsedWorld` in the client write through the same path, emitting `initial`
entries for a fresh subject.

---

## 9. Frontend

### 9.1 A page

```
박동혁                                          1학년 4반 · 주인공
목차  1. 개요  2. 외모  3. 성격  4. 말투  5. 인간관계  6. 능력  7. 작중 행적

2. 외모                                          현재  짧게 친 머리   [편집]
   작가      단정한 단발
   1화  →    한쪽 눈을 덮은 앞머리     시월과의 실랑이 중 머리카락이 잘림
   작가 →    헝클어진 앞머리           잘린 느낌을 더 살리고 싶음
   7화  →    짧게 친 머리              사념세계에 들어가기 전 직접 자름

5. 인간관계
   시월                                          현재  신뢰하는 동료
     작가    모르는 사이
     2화 →   경계하는 상대
     3화 →   신뢰하는 동료             사념세계에서 시월이 감싸 주는 것을 봄

7. 작중 행적
   1화   시월을 본관 뒤로 데려가 정체를 캐물음. 일진 무리와 대치.
   2화   한병호의 추궁을 몸으로 막아섬.
```

The **current value is shown beside the section heading**, because the single
most useful thing this page can tell an author is *what the AI currently
believes* — which is the one thing no existing screen shows.

### 9.2 Files

| File | Action |
|---|---|
| `frontend/src/types/storyweaver.ts` | add `ChronicleEntry`, `SectionSpec`, `WikiSubject`, `WikiPage` |
| `frontend/src/api/client.ts` | add the §8 calls beside the existing exports |
| `frontend/src/pages/Wiki.tsx` | CREATE — subject list |
| `frontend/src/pages/WikiSubject.tsx` | CREATE — the page above |
| `frontend/src/components/Chronicle.tsx` | CREATE — one chain, rendered |
| `frontend/src/components/SectionEditor.tsx` | CREATE — edit → appends an entry |
| `frontend/src/components/ChronicleReview.tsx` | CREATE — the §7.2 gate; model it on `PlanReview.tsx` |
| `frontend/src/App.tsx` | routes `wiki`, `wiki/:type/:id` |
| `frontend/src/components/AppLayout.tsx` | NAV entry `{ to: '/wiki', label: '위키', icon: BookMarked }` |
| `WorldBuilder.tsx`, `CharacterWorkshop.tsx` | phase 5: forms shrink to links into the wiki |

House rules that have bitten previous plan documents in this repo, stated so
this one does not repeat them: `EmptyState` requires an `icon`; `IconButton`
takes `title` and `variant`, not `label`/`tone`; `Modal`/`Drawer` render through
`createPortal`; there are no `var(--color-muted)` / `var(--color-border)` CSS
variables — use the Tailwind tokens (`text-ink-muted`, `border-line`); the
episode-creating client function is `addEpisode(storyline, title, pacing)`.

---

## 10. Phases

Each phase is independently useful and independently shippable.

**Phase 1 — the record.** `models/chronicle.py`, `ChronicleStore`,
`storage.safe_filename`, the section registry. Pure addition; nothing reads it
yet. *Done when:* entries can be appended, chained and retracted, ids cannot
collide across a Korean cast, and the full suite still passes.

**Phase 2 — recording from episodes.** Extend `CharacterStateUpdate` and
`EpisodeMemory`, rewrite the summarizer prompt with the justification gate, wire
`record_episode_completion` to append entries, add `drop_episode` on
regeneration. Still nothing reads the fold. *Done when:* generating an episode
produces a reviewable chain for every character who appeared, with a reason on
every entry, and regenerating replaces rather than duplicates. **No new model
calls** — the summarizer already runs once per episode; only its output grows.

**Phase 3 — the fold, and the prompts.** `wiki/fold.py`, `deps.folded_project()`,
and the §6 call sites. *This is the irreversible one:* from here the story is
written from folded state. Verify the Lore Checker first and hardest — a false
violation loop is the failure that costs real quota. *Done when:* a character
whose appearance changed in episode 1 is described the new way in episode 2, and
the Lore Checker does not flag them for it.

**Phase 4 — the wiki UI.** Pages, sections, chronicle rendering, author editing,
free sections, the timeline view. *Done when:* an author can add a section, edit
a value, see the change appear as a new entry, and watch the current value
update. This is also where "entering settings should be easier" is delivered.

**Phase 5 — the review gate, and retiring the forms.** `ChronicleReview` after
generation; World Builder and Character Workshop reduced to entry points into
the wiki. Last because until phases 1–4 are proven the old forms are the safety
net.

---

## 11. Tests

Following this repo's convention: behaviour-named tests, no live model calls
(`conftest._no_live_model_calls` patches `llm.build_model`), real `data/` never
touched.

- **Store** — append/chain/retract ordering; a five-strong Korean cast gets five
  files; NFC and NFD of one name are one subject; `../..` cannot escape.
- **Fold** — empty chronicle folds to the model's own value; last entry wins;
  a retracted last entry falls back to the one before; relationships rebuild
  from per-target chains; an author entry after an episode entry wins.
- **Ordering** — an entry appended for episode 3 after episode 7 exists sorts by
  `sequence`, not by episode number or timestamp.
- **Recording** — an episode with no justified change records nothing; an entry
  with an empty `reason` and `source="episode"` is rejected with 422;
  regenerating an episode replaces its entries; deleting an episode drops them;
  moving an episode renumbers them without reordering the chain.
- **Prompts** — after a recorded appearance change, `_character_sheets` and
  `build_system_prompt` carry the new value; the Lore Checker prompt does too;
  `_expand_summary` and `draft_plan` see folded state. A free section reaches
  the character prompt. `factions` and `additional_lore` reach the world prompt.
- **API** — every §8 route; a bound-section delete empties the field; a direct
  `PUT /api/characters` still works and appends an entry.

---

## 12. Risks

**A false record deforms the character permanently.** The chronicle wins, so an
invented change becomes the truth of the next episode. Mitigated by the §7.1
justification gate, the §7.2 author review, and `retract`. This is the reason
review exists at all.

**The Lore Checker turning on the author.** The quietest failure in §6: if it
reads the original while the prose follows the fold, it reports violations on
correct writing and the pipeline burns real quota re-running good scenes. Verify
this specific path before anything else in phase 3.

**Prompt growth.** Every character gains a chronicle; naively including it would
balloon every prompt. Prompts carry **current values only** — the chain is for
the author's screen. The one exception worth considering later is showing the
Director a short recent-changes digest so it can write continuity deliberately.

**Half-migration.** The state this repo must not end in is settings living in
forms *and* in the wiki. Phase 5 exists to close that, and phases 1–3 are
deliberately invisible to the author so there is never a period with two
competing input surfaces.

**Episode identity.** §2.5 sidesteps renumbering for ordering, but
`episode_number` is still shown to the author and still renumbers. A stable
episode id is the cleaner fix and is worth doing if this area is touched again;
it is out of scope here because `ChronicleStore.renumber` covers the symptom.

---

## 13. Decisions already made

Recorded so they are not relitigated mid-build.

1. The chronicle key is `(subject, section)`, not `(subject)`. — author, §2.2
2. It applies to every wiki subject: character, world, location, rule, faction.
3. The author's own writing is the first entry, not a separate base record.
4. The latest entry wins — **and** change must be earned by something in the
   episode. "Evolving organically with justification", not "settings ignored".
5. Every intermediate step is preserved. c→b and b→d both survive, so the author
   can audit a finished arc for errors and omissions.
6. Sections are freely added, edited and deleted by the author.
7. The AI records into free sections too — they affect the story.
8. The wiki and the DB are one store with two faces, not two stores that sync.
9. List-shaped sections are recorded chronologically; no member-level diffing.
10. No spoiler folding.
11. The pre-writing author gate (기획서 approval) stays exactly as it is.

## 14. Open questions

1. **Where do pending proposals live** — flagged entries in the main chain, or a
   separate pending file? Affects how hard it is to guarantee an unreviewed
   entry never folds.
2. **Should the Director see recent changes**, not just current values? It would
   let an episode deliberately build on last episode's shift rather than merely
   being consistent with it. Costs prompt budget.
3. **Timeline view scope** — all subjects on one page, or per-episode "what
   changed in this chapter"? The second is likely more useful when auditing.
4. **Skip-review setting** — per project, or per episode? §7.2 argues it must
   exist; where it lives is undecided.
