# Phase 1: Foundation & Data Models

## Goal

Set up the project skeleton, install all dependencies, define the core data structures (Pydantic models) that every subsequent phase depends on, and verify that the Gemini 3.7 Flash API is reachable and responding.

By the end of this phase we should be able to run a trivial "hello world" LangGraph graph that calls Gemini and returns a response.

---

## 1.1 Project Initialization

### Directory Structure

```
make-story/
├── pyproject.toml          # Project metadata & dependency management
├── .env                    # API keys (GOOGLE_API_KEY, etc.)
├── .env.example            # Template without secrets
├── README.md
├── src/
│   └── storyweaver/
│       ├── __init__.py
│       ├── config.py           # Central settings (model name, temperature, etc.)
│       ├── models/
│       │   ├── __init__.py
│       │   ├── world.py        # WorldLore, Location, MagicSystem, Rule …
│       │   ├── character.py    # CharacterProfile, Relationship, Trait …
│       │   ├── episode.py      # Episode, Scene, StoryBeat …
│       │   └── memory.py       # MemoryEntry, InteractionLog …
│       ├── agents/             # (empty for now, populated in Phase 2)
│       │   └── __init__.py
│       ├── memory/             # (empty for now, populated in Phase 4)
│       │   └── __init__.py
│       └── ui/                 # (empty for now, populated in Phase 5)
│           └── __init__.py
├── tests/
│   ├── __init__.py
│   └── test_models.py
└── data/
    └── examples/
        └── harry_potter_sample.json   # Sample input for smoke tests
```

### Dependencies (pyproject.toml / requirements.txt)

| Package | Purpose |
|---|---|
| `langgraph` | Agent orchestration framework |
| `langchain-google-genai` | Gemini model binding |
| `pydantic >= 2.0` | Data validation & schema |
| `chromadb` | Vector store for RAG (Phase 4, install early) |
| `streamlit` | Web UI (Phase 5, install early) |
| `python-dotenv` | Env var management |
| `pytest` | Testing |

### Steps

1. Create virtualenv (`python -m venv .venv`) and activate.
2. `pip install langgraph langchain-google-genai pydantic chromadb streamlit python-dotenv pytest`.
3. Create `.env` with `GOOGLE_API_KEY=<key>`.
4. Create `config.py` that loads env and exposes constants:
   ```python
   MODEL_NAME = "gemini-3.7-flash"
   TEMPERATURE = 0.8          # creative writing benefits from higher temp
   MAX_OUTPUT_TOKENS = 8192
   ```

---

## 1.2 Core Data Models

All models use Pydantic v2 `BaseModel`.

### 1.2.1 `models/character.py`

```python
class Trait(BaseModel):
    """A single personality trait with intensity."""
    name: str                       # e.g. "courageous"
    intensity: float = 0.8          # 0.0 – 1.0
    description: str | None = None  # optional elaboration

class Relationship(BaseModel):
    """Directed relationship from this character to another."""
    target_character_id: str
    type: str                       # e.g. "friend", "rival", "mentor"
    sentiment: float = 0.0          # -1.0 (hatred) to 1.0 (love)
    description: str | None = None  # free-text nuance

class CharacterProfile(BaseModel):
    """Complete author-defined character sheet."""
    id: str                         # unique slug, e.g. "harry-potter"
    name: str
    aliases: list[str] = []
    age: int | None = None
    gender: str | None = None
    appearance: str                 # free-text physical description
    personality_summary: str        # short paragraph
    traits: list[Trait] = []
    speech_style: str               # how they talk — dialect, formality, quirks
    values: list[str] = []          # what they care about
    goals: list[str] = []           # current motivations
    backstory: str = ""
    relationships: list[Relationship] = []
    secrets: list[str] = []         # things other characters don't know
    author_notes: str = ""          # meta-notes only visible to the system
```

### 1.2.2 `models/world.py`

```python
class Rule(BaseModel):
    """A binding rule of the world (e.g. 'wands are required for magic')."""
    id: str
    category: str               # "magic", "politics", "physics", …
    statement: str              # natural-language rule
    exceptions: list[str] = []

class Location(BaseModel):
    id: str
    name: str
    description: str
    parent_location_id: str | None = None   # for hierarchy (Hogwarts > Great Hall)
    notable_features: list[str] = []

class WorldLore(BaseModel):
    """Top-level container for the entire fictional universe."""
    title: str                          # e.g. "The Wizarding World"
    genre: str                          # "fantasy", "sci-fi", …
    tone: str                           # "dark", "lighthearted", "epic", …
    era: str | None = None
    overview: str                       # multi-paragraph world description
    rules: list[Rule] = []
    locations: list[Location] = []
    factions: list[str] = []
    additional_lore: dict[str, str] = {}  # open-ended key-value pairs
```

### 1.2.3 `models/episode.py`

```python
class StoryBeat(BaseModel):
    """An atomic plot point inside a scene."""
    description: str                # what must happen
    involved_character_ids: list[str] = []
    location_id: str | None = None
    mood: str | None = None         # "tense", "comedic", …

class Scene(BaseModel):
    """A scene within an episode, generated by the Director."""
    scene_number: int
    title: str
    location_id: str | None = None
    participating_character_ids: list[str]
    objective: str                  # what the scene should accomplish narratively
    beats: list[StoryBeat] = []
    # Filled after Character Agent simulation:
    interaction_log: list[str] = []
    # Filled after Writer Agent:
    prose: str = ""

class Episode(BaseModel):
    """One chapter / 회차. The author provides the storyline; the system fills the rest."""
    episode_number: int
    title: str = ""
    author_storyline: str           # the author's rough outline for this episode
    scenes: list[Scene] = []        # populated by Director Agent
    final_text: str = ""            # assembled prose from all scenes
    summary: str = ""               # generated after completion for memory
    status: str = "queued"          # queued | in_progress | completed
```

### 1.2.4 `models/memory.py`

```python
class InteractionRecord(BaseModel):
    """A record of a meaningful interaction between characters."""
    episode_number: int
    scene_number: int
    participants: list[str]         # character IDs
    summary: str                    # what happened
    emotional_impact: dict[str, str] = {}   # char_id -> how it affected them
    plot_threads_opened: list[str] = []     # foreshadowing / 떡밥
    plot_threads_resolved: list[str] = []

class CharacterMemory(BaseModel):
    """Accumulated memory for a single character."""
    character_id: str
    interaction_history: list[InteractionRecord] = []
    relationship_updates: list[Relationship] = []   # evolving relationships
    internal_state: str = ""        # current emotional/mental state summary

class StoryMemory(BaseModel):
    """Global story memory — the 'bible' that grows with each episode."""
    world_lore_updates: list[str] = []   # newly revealed lore
    active_plot_threads: list[str] = []  # unresolved 떡밥
    resolved_plot_threads: list[str] = []
    episode_summaries: dict[int, str] = {}   # episode_number -> summary
    character_memories: dict[str, CharacterMemory] = {}
```

---

## 1.3 Gemini + LangGraph Smoke Test

Create `src/storyweaver/smoke_test.py`:

```python
"""Minimal test: call Gemini 3.7 Flash via LangGraph."""
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import TypedDict

class SimpleState(TypedDict):
    prompt: str
    response: str

llm = ChatGoogleGenerativeAI(model="gemini-3.7-flash")

def call_llm(state: SimpleState) -> dict:
    result = llm.invoke(state["prompt"])
    return {"response": result.content}

graph = StateGraph(SimpleState)
graph.add_node("llm", call_llm)
graph.add_edge(START, "llm")
graph.add_edge("llm", END)
app = graph.compile()

if __name__ == "__main__":
    out = app.invoke({"prompt": "Write one sentence about a wizard.", "response": ""})
    print(out["response"])
```

**Success criteria:** Running the above prints a coherent sentence with no errors.

---

## 1.4 Unit Tests

`tests/test_models.py` — verify that every model can be instantiated, serialized to JSON, and deserialized without loss.

---

## Deliverables Checklist

- [ ] Project directory created with structure above
- [ ] All dependencies installed and importable
- [ ] `.env` with valid Gemini API key
- [ ] All Pydantic models defined and unit-tested
- [ ] `smoke_test.py` successfully calls Gemini 3.7 Flash via LangGraph
- [ ] Sample data file (`harry_potter_sample.json`) with 2 characters, 1 location, 3 rules, and 1 episode outline
