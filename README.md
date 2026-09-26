# StoryWeaver

Multi-agent long-form fiction. You supply the world, the cast, and a rough
outline per episode; a LangGraph pipeline casts the scenes, plays them out in
character, checks its own continuity, writes the chapter, and remembers what it
wrote so the next episode can build on it.

Powered by Gemini via `langchain-google-genai`.

```
Episode outline ──► Director ──► Character agents ──► Lore Checker ──► Writer ──► Chapter
                        ▲              ▲                                             │
                        └──────── Memory (what the story already established) ◄───────┘
```

---

## Quickstart

```bash
git clone <this repo> && cd make-story
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on POSIX
pip install -e ".[dev]"

cp .env.example .env               # then paste your Gemini API key in
cd frontend && npm install && cd ..

python scripts/dev.py              # backend on :8001, the studio on :5173
```

Get a key at <https://aistudio.google.com/apikey>.

## Starting it

Everything after the first time, from the project root:

```bash
start.bat                                # Windows — double-click it, or run it
.venv\Scripts\python.exe scripts\dev.py  # the same thing, spelled out
python scripts/dev.py                    # POSIX, or with the venv activated
```

One command brings up both halves: the backend on `:8001` and the studio on
`:5173`. **Auto-reload is on**: saving a backend file — code or a prompt under
`agents/prompts/` — restarts the backend by itself, and the frontend hot-reloads
as usual, so there is nothing to restart while you edit. Wait for `✅ Both servers are running!` before opening
<http://localhost:5173> — the backend loads its memory store first, and a
generation started before that is refused.

On a fresh project the order is:

0. **💡 작품 기획** — if you have no story yet, start here and the world, the
   cast, the arc and a rough line per chapter are all written for you. Two ways
   in: take three finished concepts and pick one, or open **대화하며 함께
   기획하기** and work it out a message at a time. Either way it lands in the
   wiki as the first entry in each chain, so all of it stays editable. Skip
   this if you already know what you are writing.
1. **🌍 세계관 빌더** opens on **빠른 설정**, because the world is empty. Describe
   the setting in a paragraph and it fills in the title, genre, tone, rules and
   places.
2. **👤 캐릭터 워크숍 → 캐릭터 추가** — describe a character in your own words, or
   fill the sheet in by hand.
3. **📋 스토리 플래너** — one line per episode, expanded into outlines you approve.
4. **📝 에피소드 큐 → 기획서 만들기** — check the scene layout, approve it, generate.
5. When the chapter is done you are shown **what it recorded** about the cast and
   the world. Only what you accept reaches the next chapter.
6. **📖 위키** — every setting, and the history of how it got that way. Anything
   can be deleted from here: one record, a section's contents, or a whole page.

To start a different novel, **⚙️ 설정 → 새 작품으로 시작 (초기화)** clears the
world, cast, chapters, wiki and memory. The concept you are working on in 작품
기획 and your writing style are kept, so you can reset and then commit the new
concept straight away. Take the backup it offers first if you want the old one.

Only the backend restarts; the studio stays up. If the file you saved has an
error, the backend stays down and says so, and the next save brings it back. A
restart does interrupt a chapter that is being generated (it resumes from its
checkpoint), so for a long writing session rather than editing the app, turn it
off:

```bash
start.bat --no-reload
.venv\Scripts\python.exe scripts\dev.py --no-reload
```

### The HTTP API on its own

```bash
uvicorn storyweaver.server:app --app-dir backend --port 8001
```

Interactive docs at <http://localhost:8001/docs>. Generation streams over
Server-Sent Events at `GET /api/generation/stream/{episode}`; the run itself is
a job that saves its own result, so closing the stream never costs a chapter.

---

## What it does

| | |
|---|---|
| **Director** | Breaks your outline into 3–4 scenes, keeping every beat you wrote and inventing the connective tissue between them. You approve the plan — scenes, objectives, cast, length budget — before anything is written |
| **Character agents** | One shared model, a different prompt per character: their traits, voice, goals, secrets, and what *they* personally remember |
| **Lore Checker** | Validates every scene against your world's rules and the characters' own definitions; re-runs the offending turns with a correction injected |
| **Writer** | Turns the interaction log into prose, in your perspective, density, pacing and language |
| **Summarizer** | Decides what was worth remembering — discoveries, betrayals, promises, 떡밥 — and files it away |

Over many episodes the memory layer is what keeps the serial coherent: episode
12 can refer to episode 3, characters remember what they were present for, and
plot threads that have gone quiet get flagged before a reader decides they were
dropped.

---

## The workbench

```
📖 StoryWeaver
├── 🏠 Dashboard          stats, what to generate next, threads going cold
├── 🌍 World Builder      overview, rules, a location tree, factions, lore
├── 👤 Character Workshop full profiles, trait sliders, a relationship graph
├── 📝 Episode Queue      outlines in, generation with live progress
├── 📖 Reading Room       the prose, side by side with your outline, export
├── 🧠 Memory Inspector   plot threads, character memory, semantic search
└── ⚙️ Settings           writing style, model & cost, backups, import/export
```

Generation reports real progress, driven by the pipeline itself:

```
✅ Planned 4 scenes
✅ Simulated scene 1/4 — 9 turns
✅ Lore check scene 1/4 — passed
✅ Wrote scene 1/4 — 1,423 words
⚠️ Lore check scene 2/4 — 1 violation, re-running
🔄 Working on scene 2/4…
⬜ Scene 3/4
⬜ Assembling final text
```

---

## Documentation

- **[docs/user_guide.md](docs/user_guide.md)** — every page, and what to do with it
- **[docs/author_tips.md](docs/author_tips.md)** — how to write rules, characters and outlines that produce good output
- **[docs/architecture.md](docs/architecture.md)** — the pipeline, the memory layer, the LLM call audit, resilience

---

## Command line

```bash
pytest                                        # 835 tests, no API key and no network (enforced, not assumed)
python -m storyweaver.smoke_test              # is the model binding working?
python -m storyweaver.demo_scene --two        # one scene, printed
python -m storyweaver.demo_episode --memory   # one episode, with continuity
python scripts/run_wizarding_world.py --episodes 10 --out build/
```

The last is the flagship run: ten episodes of an 8-character, 15-rule world, with
a measured cost breakdown per episode and Markdown / TXT / DOCX exports at the
end.

---

## Layout

```
backend/storyweaver/
  config.py          settings from .env
  llm.py             model factory: per-stage temperature, retries
  resilience.py      retry, backoff, output repair
  telemetry.py       per-stage token and cost accounting
  storage.py         atomic writes, backups
  export.py          TXT / Markdown / DOCX, whole-story assembly
  server.py          FastAPI app: CORS, lifespan, /api/health
  api/               REST + SSE routes (project, world, characters, episodes,
                     generation, memory, export)
  models/            WorldLore, CharacterProfile, Episode, WritingStyle, memory
  agents/            director, character, scene_runner, lore_checker, writer,
                     episode_runner, checkpoint, prompts/
  memory/            manager, vector_store, structured_store, plot_tracker,
                     summarizer
  ui/                project.py and progress.py (no Streamlit), plus the old
                     Streamlit workbench
frontend/            Vite + React + TypeScript studio
  src/types/         the domain, mirrored from the Pydantic models
  src/api/           typed REST client and the generation stream hook
  src/components/    shell, toasts
  src/pages/
data/
  examples/          bundled datasets
  project.json       your story (gitignored)
  state/             memory + checkpoints (gitignored)
  chromadb/          vector store (gitignored)
docs/
tests/
```

---

## Configuration

Read from the environment or `.env` at startup:

| Variable | Default |
|---|---|
| `GOOGLE_API_KEY` | *(required for any model call)* |
| `STORYWEAVER_MODEL` | `gemini-3.7-flash` |
| `STORYWEAVER_TEMPERATURE` | `0.8` |
| `STORYWEAVER_MAX_OUTPUT_TOKENS` | `8192` |
| `STORYWEAVER_RECENT_EPISODES` | `3` |
| `STORYWEAVER_STALE_THREAD_EPISODES` | `5` |

Per-stage temperatures are set in `llm.py`: judgement calls run cold, prose runs
warm.

---

## Cost and resilience

Every model call is metered. A generation reports its own breakdown per stage —
the Character agent is typically the overwhelming majority of the spend, and the
report tells you so rather than making you guess. A four-scene episode with three
characters runs roughly 150k–250k tokens.

Calls retry up to three times: malformed output is retried at a higher
temperature and then repaired, and rate limits are backed off exponentially with
jitter. An episode that fails partway keeps its finished scenes and resumes from
there. State files are written atomically.

---

## Development

```bash
pytest                     # the whole suite
pytest -q --ignore=tests/test_ui_pages.py   # faster, skips the Streamlit renders
```

The suite never touches the network, and that is enforced rather than assumed:
an autouse fixture in `tests/conftest.py` makes `llm.build_model` raise, so a
test that forgets its stub fails instead of quietly spending your quota. Agents
take an optional `llm=` and `conftest.py` supplies a `FakeLLM` that records
prompts and returns scripted structured output; ChromaDB runs against a per-test directory with a
deterministic embedder; Streamlit pages are executed by `AppTest`.
