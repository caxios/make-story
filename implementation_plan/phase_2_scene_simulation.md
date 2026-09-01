# Phase 2: Single-Scene Agent Simulation

## Goal

Implement the **Director Agent** and **Character Agents** using LangGraph so that, given a single scene objective and two or more character profiles, the system produces a realistic interaction log — a transcript of dialogue, actions, thoughts, and reactions that stay true to each character's defined personality.

This is the creative heart of the system. By the end of this phase, we should see characters "acting in character" within a constrained scenario.

---

## 2.1 LangGraph State Design

The workflow state for scene simulation extends from Phase 1 models:

```python
class SceneSimulationState(TypedDict):
    # --- Inputs (set before graph starts) ---
    world_lore: WorldLore
    characters: dict[str, CharacterProfile]       # id -> profile
    scene: Scene                                   # from Director
    # --- Working state ---
    current_turn: int                              # which interaction turn we're on
    max_turns: int                                 # cap to prevent infinite loops
    interaction_log: list[dict]                     # accumulated log entries
    # --- Outputs ---
    completed: bool
```

Each entry in `interaction_log` is a dict:
```python
{
    "turn": 3,
    "character_id": "hermione",
    "type": "dialogue" | "action" | "thought" | "reaction",
    "content": "We can't just break into the restricted section!",
    "directed_at": "harry"   # optional
}
```

---

## 2.2 Director Agent

### Responsibility
Takes the author's episode storyline and decomposes it into ordered **Scenes**.

### Implementation: `src/storyweaver/agents/director.py`

```
Input:  Episode.author_storyline + WorldLore + list[CharacterProfile]
Output: list[Scene]   (each with objective, participating characters, location, beats)
```

**Prompt strategy (structured output with Pydantic):**

```
You are a seasoned story director. Given the author's storyline for this episode,
break it into 3–5 scenes. For each scene specify:
- A clear narrative objective (what must be accomplished)
- Which characters are present
- The location (from the provided world locations)
- 1–3 story beats (atomic plot points)
- The intended mood / tone

IMPORTANT:
- Between the major plot beats given by the author, ADD connective tissue:
  transitional scenes, character moments, small interactions that make the
  story feel organic rather than a bullet-point list.
- Respect all world rules provided.

Author's storyline: {episode.author_storyline}
World: {world_lore (summarized)}
Available characters: {character summaries}
Available locations: {location list}
```

The Director uses **structured output** (Gemini's JSON mode or LangChain's `with_structured_output`) to return a `list[Scene]` directly.

---

## 2.3 Character Agent

### Responsibility
Given a scene and a character profile, produce that character's contribution (dialogue, actions, thoughts) for one turn of the interaction.

### Implementation: `src/storyweaver/agents/character.py`

Each character is driven by the **same LLM** but with a **unique system prompt** constructed from their `CharacterProfile`:

```
You are {character.name}.

## Your Identity
{character.personality_summary}

## How You Speak
{character.speech_style}

## Your Traits
{formatted traits with intensities}

## Your Current Goals
{character.goals}

## Your Relationships with Characters in This Scene
{relevant relationships}

## Your Secrets
{character.secrets}
(You know these but must not reveal them unless the story naturally demands it.)

## Scene Context
Location: {scene.location}
Objective: {scene.objective}
What has happened so far:
{interaction_log (last N entries)}

## Your Task
React to the current situation IN CHARACTER. Produce exactly ONE of:
- dialogue: something you say out loud
- action: something you physically do
- thought: an internal reflection (only the reader sees this)
- reaction: an emotional or physical reaction to something that just happened

Stay true to your personality. Do NOT break character.
Respond in the following JSON format:
{{"type": "...", "content": "...", "directed_at": "..." (optional)}}
```

### Turn-Taking Mechanism

Characters take turns in a round-robin fashion within each scene. The flow:

```
┌───────────────────────────────────┐
│         Scene Simulation          │
│                                   │
│  ┌─────────┐    ┌─────────┐      │
│  │  Char A  │───►│  Char B  │     │
│  └────▲─────┘    └────┬─────┘     │
│       │               │           │
│       └───────────────┘           │
│         (round-robin)             │
│                                   │
│  Exit when:                       │
│   • max_turns reached             │
│   • scene objective fulfilled     │
│   • natural stopping point        │
└───────────────────────────────────┘
```

A **scene supervisor** node checks after each round whether the scene's objective has been met. It uses a lightweight LLM call:

```
Given the scene objective: "{scene.objective}"
And the interaction log so far:
{log}

Has the scene's narrative objective been sufficiently addressed?
Answer: YES or NO (with brief reason)
```

---

## 2.4 LangGraph Workflow (Scene Level)

```python
# Simplified graph structure
scene_graph = StateGraph(SceneSimulationState)

scene_graph.add_node("select_next_character", select_next_character)
scene_graph.add_node("character_act", character_act)
scene_graph.add_node("check_scene_complete", check_scene_complete)

scene_graph.add_edge(START, "select_next_character")
scene_graph.add_edge("select_next_character", "character_act")
scene_graph.add_edge("character_act", "check_scene_complete")

scene_graph.add_conditional_edges(
    "check_scene_complete",
    should_continue,
    {
        "continue": "select_next_character",
        "done": END
    }
)
```

**Node implementations:**

| Node | Logic |
|---|---|
| `select_next_character` | Round-robin through `scene.participating_character_ids`. Increment `current_turn`. |
| `character_act` | Build the character's system prompt, call Gemini, parse JSON response, append to `interaction_log`. |
| `check_scene_complete` | If `current_turn >= max_turns` → done. Else, lightweight LLM check on objective. |

---

## 2.5 Handling Multi-Character Dynamics

For scenes with 3+ characters:
- Round-robin order is determined by the Director (e.g., based on initiative or narrative importance).
- Characters can "direct" their dialogue/action at a specific other character, which gives that character context priority on the next turn.
- A character may also "pass" (produce a `thought` instead of dialogue) if they have nothing to contribute — this prevents forced, unnatural participation.

---

## 2.6 Testing Strategy

### Test 1: Director Scene Decomposition
- Input: Harry Potter Episode 1 storyline ("Harry receives Hogwarts letter, goes to Diagon Alley, boards the train, gets sorted")
- Verify: 3–5 scenes output, each with valid character IDs and locations from the sample data.

### Test 2: Two-Character Dialogue
- Input: Scene = "Harry and Ron meet on the Hogwarts Express." Characters: Harry (curious, orphaned, humble), Ron (loyal, insecure, humorous).
- Verify: Harry asks questions about the wizarding world. Ron explains things in a casual, slightly self-deprecating way. Neither breaks character.

### Test 3: Stopping Condition
- Set `max_turns = 20`. Verify the scene ends either when objective is met or max turns reached, whichever comes first.

---

## Deliverables Checklist

- [ ] `agents/director.py` — Decomposes episode storyline into scenes
- [ ] `agents/character.py` — Character agent that produces in-character actions
- [ ] `agents/scene_runner.py` — LangGraph workflow that orchestrates a full scene simulation
- [ ] `agents/prompts/` — All prompt templates externalized as separate files
- [ ] Scene simulation produces a coherent interaction log for a 2-character and a 3-character scene
- [ ] Turn count is bounded; scene ends when objective is met
