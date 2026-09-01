# Phase 4: Memory & RAG System

## Goal

Build a persistent, query-able memory layer that ensures **story continuity across episodes**. Characters must remember what happened, who they met, what promises were made, and what plot threads (떡밥) are still open — even after 50+ episodes. The system must handle **Harry Potter-scale** volumes of lore and narrative history without losing critical details.

This is the phase that transforms the system from "generate one chapter" to "write a coherent long-form serial."

---

## 4.1 Memory Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Memory Layer                         │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │   ChromaDB    │  │  Structured   │  │  Plot Thread  │ │
│  │  Vector Store │  │  JSON Store   │  │   Tracker     │ │
│  │  (semantic)   │  │  (exact)      │  │  (떡밥 관리)   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘ │
│         │                  │                  │          │
│         └──────────┬───────┘──────────────────┘          │
│                    │                                     │
│           ┌────────▼────────┐                            │
│           │  Memory Manager │   ← single API surface     │
│           └─────────────────┘                            │
└─────────────────────────────────────────────────────────┘
```

We use a **hybrid memory** approach — not just a vector database:

| Store | What it holds | When to query |
|---|---|---|
| **ChromaDB (Vector)** | Episode summaries, interaction records, lore entries — all as embeddings | Semantic retrieval: "What does Ron know about the Philosopher's Stone?" |
| **Structured JSON** | Character relationship graphs, current goals, emotional states — exact data | Direct lookups: "What is Hermione's current relationship with Draco?" |
| **Plot Thread Tracker** | Named threads with status (open/progressing/resolved), linked events | "What unresolved threads should influence Episode 12?" |

---

## 4.2 ChromaDB Collections

### Collection: `episode_summaries`

One document per completed episode.

```python
{
    "id": "episode_7",
    "document": "Episode 7 summary text (~500 words)...",
    "metadata": {
        "episode_number": 7,
        "characters_involved": ["harry", "ron", "hermione"],
        "locations": ["hogwarts_library", "forbidden_corridor"],
        "key_events": ["discovered fluffy", "learned about nicolas flamel"],
        "mood": "mysterious, tense"
    }
}
```

### Collection: `interaction_records`

One document per meaningful interaction (not every single dialogue line — see §4.4 for what qualifies).

```python
{
    "id": "ep7_scene2_interaction_3",
    "document": "Harry, Ron, and Hermione accidentally discovered a three-headed dog guarding a trapdoor on the forbidden third floor. Hermione noticed it was standing on a trapdoor. Ron was terrified, Harry was curious.",
    "metadata": {
        "episode_number": 7,
        "scene_number": 2,
        "participants": ["harry", "ron", "hermione"],
        "type": "discovery",
        "emotional_impact": {"harry": "intrigued", "ron": "scared", "hermione": "analytical"},
        "plot_threads": ["whats_under_trapdoor", "fluffy_the_dog"]
    }
}
```

### Collection: `world_lore`

All world rules, location descriptions, faction info, etc. — seeded from the author's initial `WorldLore` input and enriched as the story progresses.

```python
{
    "id": "rule_wand_magic",
    "document": "In this world, witches and wizards require a wand to perform most spells. Wandless magic is possible but extremely rare and limited to the most powerful practitioners.",
    "metadata": {
        "category": "magic_system",
        "source": "author_defined",
        "episode_introduced": 0
    }
}
```

---

## 4.3 Memory Manager

### Implementation: `src/storyweaver/memory/manager.py`

A unified interface that both agents and the pipeline use:

```python
class MemoryManager:
    def __init__(self, chroma_client, data_dir: Path):
        self.vector_store = chroma_client
        self.structured_store = StructuredStore(data_dir)
        self.plot_tracker = PlotThreadTracker(data_dir)

    # === WRITE ===
    def record_episode_completion(self, episode: Episode, interaction_records: list[InteractionRecord]):
        """Called after each episode finishes. Stores summary + interactions."""

    def update_character_state(self, character_id: str, updates: dict):
        """Update a character's current emotional state, goals, relationships."""

    def open_plot_thread(self, thread_name: str, description: str, episode: int):
        """Register a new 떡밥."""

    def resolve_plot_thread(self, thread_name: str, resolution: str, episode: int):
        """Mark a 떡밥 as resolved."""

    # === READ (for agents) ===
    def get_relevant_memories(self, query: str, character_id: str | None = None, top_k: int = 10) -> list[str]:
        """Semantic search across all memory. Optionally filtered by character."""

    def get_character_state(self, character_id: str) -> CharacterMemory:
        """Get exact current state: relationships, goals, emotional state."""

    def get_active_plot_threads(self) -> list[PlotThread]:
        """All unresolved 떡밥."""

    def get_episode_summary(self, episode_number: int) -> str:
        """Get the summary of a specific past episode."""

    def get_recent_context(self, n_episodes: int = 3) -> str:
        """Get summaries of the last N episodes for context injection."""
```

---

## 4.4 What Gets Remembered (Granularity Policy)

Not every line of dialogue is stored verbatim. The **Episode Summarizer** (a specialized LLM call at the end of each episode) decides what is "memory-worthy":

### Always Remembered (stored as `InteractionRecord` + vector embedding):
- **Plot-advancing events:** discoveries, decisions, confrontations
- **Relationship changes:** new alliances, betrayals, confessions
- **Foreshadowing / 떡밥:** mysterious clues, ominous warnings, unresolved mysteries
- **Emotional milestones:** first meeting, heartbreak, triumph, loss
- **World-state changes:** new locations discovered, rules revealed, political shifts
- **Character development moments:** values challenged, growth, regression

### Summarized Only (captured in episode summary but not as individual records):
- Routine dialogue that doesn't advance plot
- Repeated information (e.g., a character explaining something already known)
- Transitional actions (walking, eating, sleeping — unless narratively significant)

### Granularity Policy Prompt (for the Summarizer):

```
You are a story editor creating a memory record for a serialized novel.

Episode {N} has just been completed. Your job is to extract everything that
a future episode might need to reference.

Think like a reader who takes notes: What would you jot down to remember
for later chapters? What 떡밥 (foreshadowing/plot threads) were planted?
What changed about the characters or their relationships?

Be thorough. It is better to over-record than to miss a detail that becomes
important later. Imagine this is a Harry Potter-length series — small details
in Book 1 become critical in Book 7.
```

---

## 4.5 Context Injection into Agents

Before each episode generation, the Memory Manager assembles a **context packet** for each agent:

### For the Director Agent:
```
## Story So Far (last 3 episode summaries)
{recent_context}

## Active Plot Threads (떡밥)
{active_threads with descriptions}

## Character Relationship Graph (current state)
{formatted relationship data}
```

### For each Character Agent:
```
## Your Memory ({character.name})
Recent events you remember:
{semantic search: top 5 relevant memories for this character in this scene}

Your current emotional state: {character_memory.internal_state}
Your current goals: {character_memory.goals}

Relationships:
{current relationship data for characters in this scene}
```

### For the Writer Agent:
```
## Established Prose Tone
(last 500 words of the previous episode's final text — for style continuity)

## Relevant Past References
{memories that the reader would connect to this scene}
```

---

## 4.6 Plot Thread Tracker

### Implementation: `src/storyweaver/memory/plot_tracker.py`

```python
class PlotThread(BaseModel):
    id: str                          # e.g., "philosophers_stone_mystery"
    name: str                        # human-readable name
    description: str                 # what the thread is about
    status: str = "open"             # "open" | "progressing" | "resolved"
    opened_in_episode: int
    last_referenced_episode: int
    resolved_in_episode: int | None = None
    linked_characters: list[str] = []
    events: list[str] = []          # chronological list of related event summaries
    resolution: str | None = None

class PlotThreadTracker:
    def open(self, thread: PlotThread) -> None: ...
    def progress(self, thread_id: str, event: str, episode: int) -> None: ...
    def resolve(self, thread_id: str, resolution: str, episode: int) -> None: ...
    def get_active(self) -> list[PlotThread]: ...
    def get_stale(self, episodes_since_last_ref: int = 5) -> list[PlotThread]: ...
```

The `get_stale()` method is particularly important — it identifies plot threads that haven't been referenced in a while. The Director can use this to weave dormant threads back into the narrative, preventing dropped storylines.

---

## 4.7 Persistence

- **ChromaDB:** Persistent storage mode (file-based), stored in `data/chromadb/`.
- **Structured JSON:** Stored in `data/state/` as JSON files (one per character + one global).
- **Plot Threads:** Stored in `data/state/plot_threads.json`.

All stores are initialized from disk on startup and written after each episode completion.

---

## 4.8 Testing Strategy

### Test 1: Memory Retrieval Accuracy
- Generate 5 episodes. Store memories. Query "What does Harry know about the trapdoor?"
- Verify: Returns the relevant interaction record from the correct episode.

### Test 2: Plot Thread Lifecycle
- Open thread in Ep 1, progress it in Ep 3, resolve in Ep 5.
- Verify: Thread status transitions correctly. After resolution, it no longer appears in `get_active()`.

### Test 3: Stale Thread Detection
- Open a thread in Ep 1, never reference it again.
- After Ep 6, call `get_stale(episodes_since_last_ref=5)`.
- Verify: The stale thread is returned.

### Test 4: Cross-Episode Continuity
- In Ep 1, character A makes a promise to character B.
- In Ep 3, A and B meet again.
- Verify: Character A's memory includes the promise. The generated interaction references or acknowledges it.

---

## Deliverables Checklist

- [ ] `memory/manager.py` — Unified MemoryManager with read/write APIs
- [ ] `memory/vector_store.py` — ChromaDB wrapper with collections (episodes, interactions, lore)
- [ ] `memory/structured_store.py` — JSON-based exact-match store for character states
- [ ] `memory/plot_tracker.py` — Plot thread lifecycle management
- [ ] `memory/summarizer.py` — LLM-based episode summarizer with granularity policy
- [ ] Integration with episode pipeline (inject context before generation, store after completion)
- [ ] `data/` directory structure for persistence
- [ ] All 4 test scenarios pass
