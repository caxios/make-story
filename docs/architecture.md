# Architecture

StoryWeaver turns an author's rough episode outline into a written chapter, and
remembers what it wrote so the next episode can build on it.

The system is a LangGraph pipeline of specialised agents over a shared memory
layer. Every agent is a prompt plus a Pydantic output schema; the interesting
engineering is in what each one is *shown*, and in what happens when a model
misbehaves.

---

## 1. The shape of the system

```
                        ┌─────────────────────────────┐
   author input ───────►│         Project             │  world, cast, queue, style
   (UI or JSON)         │      ui/project.py          │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │      Episode pipeline       │  agents/episode_runner.py
                        │     (LangGraph, 7 nodes)    │
                        └──────────────┬──────────────┘
                                       │
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
   Director      Scene runner     Lore Checker      Writer      Summarizer
  (casts the    (turn-by-turn     (continuity      (prose)      (what to
   scenes)       simulation)        gate)                        remember)
        │              │               │               │              │
        └──────────────┴───────────────┼───────────────┴──────────────┘
                                       ▼
                        ┌─────────────────────────────┐
                        │        Memory layer         │  memory/manager.py
                        │  vectors · JSON · threads   │
                        └─────────────────────────────┘
```

---

## 2. The episode pipeline

`agents/episode_runner.py` is the spine. One LangGraph graph, run once per
episode:

```
START ─┬─ (no scenes) ─► director_plan_scenes ─┐
       └─ (resuming) ───────────────────────┐  │
                                            ▼  ▼
                                       simulate_scene
                                            │
                                            ▼
                                        check_lore
                                     ┌──────┴───────┐
                            violations│             │clean
                                      ▼             ▼
                                 rerun_scene    write_scene
                                      │             │
                                      └──► (loop)   ▼
                                                write_transition
                                                    │
                                                    ▼
                                              advance_scene ──┐
                                                    │         │
                                          more scenes ────────┘
                                                    │
                                                 no │
                                                    ▼
                                            assemble_episode ─► END
```

Nodes, and what each is for:

| Node | Does | Model stage |
|---|---|---|
| `director_plan_scenes` | Breaks the storyline into 3–5 scenes with objectives, casts and beats | `director` |
| `simulate_scene` | Runs the inner scene graph, turn by turn | `character`, `supervisor` |
| `check_lore` | Validates the log against world rules and character sheets | `lore` |
| `rerun_scene` | Re-simulates from the earliest offending turn, fixes injected | `character` |
| `write_scene` | Turns the log into prose | `writer` |
| `write_transition` | Bridges the seam to the previous scene | `transition` |
| `advance_scene` | Moves on, and writes a checkpoint | — |
| `assemble_episode` | Joins the scenes, titles the chapter | `titler` |

### The scene loop

`agents/scene_runner.py` is a second, inner graph, run once per scene:

```
select_next_character ─► character_act ─► check_scene_complete ─┬─ continue ─┐
                                                                │            │
                                                          done  ▼            │
                                                               END ◄─────────┘
```

Turn order is round-robin with one exception: a turn addressed at a specific
character is answered by that character next. The rota cursor is **not**
advanced for such a reply — otherwise, in a three-person scene where A always
addresses C, B never speaks.

The scene ends on whichever comes first: the turn cap, or the supervisor judging
the objective met. The supervisor is consulted once per full round, and never
before every participant has spoken twice.

---

## 3. Memory

Three stores behind one `MemoryManager`, because the questions a serial asks of
its own history are not all the same shape.

| Store | Holds | Answers |
|---|---|---|
| `vector_store.py` (ChromaDB) | Episode summaries, interaction records, world lore | "What does Ron know about the Stone?" |
| `structured_store.py` (JSON) | Relationships, goals, emotional state | "What is Hermione's relationship with Draco, exactly?" |
| `plot_tracker.py` (JSON) | Named 떡밥 with status and history | "What is unresolved — and what has gone quiet?" |

### What gets remembered

After each episode the **Summarizer** (`memory/summarizer.py`) applies a
granularity policy: discoveries, betrayals, promises, foreshadowing and
world-state changes become individual `InteractionRecord`s; walking to the Great
Hall does not. Everything else survives only in the 300–500 word episode summary.

Its output is sanitised before it is committed — hallucinated character ids are
dropped from participants, emotional impact, relationships and thread links, and
the episode number is stamped on rather than trusted. A record filed under an
invented id is a memory nobody can ever retrieve.

### What each agent is shown

Context is assembled per agent, not broadcast:

- **Director** — the last 3 episode summaries, active plot threads, threads going
  cold, the current relationship graph, and memories semantically matching this
  episode's storyline.
- **Character** — only what *they* were present for (retrieval filtered by
  participant), their current emotional state, their goals, and how they now feel
  about the others in this scene.
- **Writer** — the previous episode's voice, and the callbacks a reader would
  expect this scene to make.
- **Lore Checker** — the world's rules and the sheets of the characters present.

### Chroma and list metadata

Chroma metadata values must be scalars, but the fields worth filtering on are
lists (`participants`, `key_events`) and maps (`emotional_impact`). Non-scalars
are stored as JSON behind a `__json__:` tag and decoded on the way out.

Chroma cannot match inside a stored list, so character filtering is done in
Python over an over-fetched candidate set (`OVERFETCH = 4`).

---

## 4. LLM call audit

Every call, what it is worth, and how it is configured. Temperatures are set per
stage in `llm.py`:

| Stage | Calls per episode (4 scenes, 3 chars, 12 turns) | Temp | Priority | Notes |
|---|---|---|---|---|
| `director` | 1 | 0.7 | High | Shapes everything downstream |
| `character` | ~48 | 0.8 | High | The bulk of the spend by far |
| `supervisor` | ~8 | 0.0 | Low | A judgement; once per round, not per turn |
| `lore` | 4–12 | 0.0 | Medium | Once per scene, plus retries |
| `writer` | 4 | 0.8 | **Critical** | The only output a reader sees |
| `transition` | 3 | 0.8 | Low | One or two sentences per seam |
| `titler` | 0–1 | 0.5 | Low | Skipped when the author titled it |
| `summarizer` | 1 | 0.2 | Medium | Note-taking, not invention |

Two structural cost decisions follow from this table:

- **The supervisor runs once per round, not per turn.** Per-turn would roughly
  triple the cheapest-but-most-frequent call for no narrative gain.
- **A lore violation re-runs only the tail of the scene.** Turns before the first
  violation were already validated; redoing them would pay for them twice and
  re-roll dice that had landed well.

Measured, not estimated: `telemetry.py` records every call and reports the
per-stage breakdown. See `docs/user_guide.md` for how to read it.

---

## 5. Resilience

`resilience.py` wraps every model. One implementation covers all eight call
sites, and tests can still inject a bare fake.

| Failure | Response |
|---|---|
| Malformed / unparseable output | Retry (up to 3), raising temperature by 0.15 each time |
| Still malformed on the last attempt | A repair call: hand the raw text back with the schema and ask for valid JSON |
| Rate limit / 429 / 503 / timeout | Exponential backoff with jitter, capped at 60s — temperature untouched |
| Persistent failure | `ModelCallError`, with the original exception as `__cause__` |

Jitter matters: without it, several agents throttled at the same moment retry in
lockstep and throttle each other again.

### Partial recovery

`agents/checkpoint.py` writes the finished scenes to
`data/state/checkpoints/episode_N.json` after each one. A later run of the same
episode resumes from there, entering the graph at `simulate_scene` and skipping
the Director. A checkpoint whose storyline no longer matches is discarded — a
different storyline means different scenes.

### Durable state

`storage.py` writes every JSON state file to a `.tmp` beside the target,
`fsync`s it, then `os.replace`s it. A crash mid-write leaves the previous
version intact rather than a truncated file.

---

## 6. Module map

```
src/storyweaver/
  config.py          settings from .env
  llm.py             the model factory: per-stage temperature, retries
  resilience.py      retry, backoff, repair
  telemetry.py       per-stage token and cost accounting
  storage.py         atomic writes, backups
  export.py          TXT / Markdown / DOCX, whole-story assembly
  models/            the data the author authors
  agents/
    director.py        storyline -> scenes
    character.py       one character, one turn
    scene_runner.py    the turn loop (inner graph)
    lore_checker.py    the continuity gate
    writer.py          prose, and scene transitions
    episode_runner.py  the pipeline (outer graph)
    checkpoint.py      partial-episode recovery
    context.py         models -> prompt text
    prompts/           every prompt, as editable .md
  memory/
    manager.py         the one API agents talk to
    vector_store.py    ChromaDB
    structured_store.py JSON character + story state
    plot_tracker.py    떡밥 lifecycle
    summarizer.py      what is worth remembering
  ui/                Streamlit workbench (see user_guide.md)
```

---

## 7. Testing

309 tests, none of which touch the network.

Agents take an optional `llm=`; `tests/conftest.py` supplies a `FakeLLM` that
records prompts and returns scripted structured output. ChromaDB runs against a
per-test directory with a deterministic bag-of-words embedder. Streamlit pages
are executed by `AppTest`, the same way the server runs them.

`tests/test_integration_wizarding_world.py` runs the whole flagship arc — 8
characters, 15 rules, 10 episodes — and asserts that memory accumulates, that
threads open and resolve across ten episodes, and that a planted lore violation
is caught and repaired. What it cannot assert is prose quality; that is what
`scripts/run_wizarding_world.py` and a human reader are for.
