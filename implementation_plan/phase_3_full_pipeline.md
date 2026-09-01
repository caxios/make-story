# Phase 3: Full Episode Generation Pipeline

## Goal

Connect the Director, Character Agents, **Lore Checker**, and **Writer Agent** into a complete end-to-end pipeline. Given a single episode's storyline, the system should output a fully written chapter of prose — not just an interaction log, but actual novel-quality text with narration, dialogue, description, and internal monologue.

---

## 3.1 New Agent: Lore Checker

### Responsibility
Validate that character interactions do not violate world rules or character settings. Acts as a quality gate between the Character simulation and the Writer.

### Implementation: `src/storyweaver/agents/lore_checker.py`

```
Input:  interaction_log (from scene simulation) + WorldLore.rules + CharacterProfiles
Output: ValidationResult (pass/fail + list of violations + suggested fixes)
```

**Prompt:**
```
You are a meticulous lore editor and continuity checker.

## World Rules
{world_lore.rules — all rules listed}

## Character Constraints
{For each character: key personality traits, current relationships, secrets}

## Interaction Log to Validate
{interaction_log}

## Your Task
Check every entry in the interaction log against the world rules and character
definitions. Flag any violations:
1. World rule violations (e.g., a character uses magic without a wand in a
   world where wands are required)
2. Character inconsistencies (e.g., a cowardly character suddenly acts
   heroically without justification)
3. Relationship contradictions (e.g., enemies acting friendly without
   narrative reason)
4. Logical/continuity errors

For each violation, provide:
- The offending log entry (turn number)
- The rule or setting it violates
- A suggested fix that preserves the narrative intent

If there are NO violations, respond with: {"passed": true, "violations": []}
```

### Retry Loop
If violations are found, the system re-runs the scene simulation for the affected turns with the fix suggestions injected into the character prompts as additional constraints. Maximum 2 retry attempts before accepting with warnings.

```
┌────────────┐     ┌────────────┐     ┌──────────────┐
│  Director   │────►│  Character  │────►│  Lore Checker │
│  (scenes)   │     │  Simulation │     │  (validate)   │
└────────────┘     └─────▲──────┘     └──────┬───────┘
                         │                    │
                         │   violations?      │
                         │◄───── YES ─────────┘
                         │                    │
                         │        NO ─────────▼
                         │              ┌───────────┐
                         │              │   Writer   │
                         │              │  (prose)   │
                         │              └───────────┘
```

---

## 3.2 New Agent: Writer Agent

### Responsibility
Transform the raw interaction log into polished, novel-style prose. This is the "voice" of the story.

### Implementation: `src/storyweaver/agents/writer.py`

```
Input:  Scene (with completed interaction_log) + WorldLore + CharacterProfiles + style_guide
Output: str  (prose text for this scene)
```

**Prompt:**
```
You are an accomplished novelist. Your task is to transform a scene's
interaction log into vivid, immersive prose.

## Story Context
Genre: {world_lore.genre}
Tone: {world_lore.tone}
Location: {scene.location — full description}
Scene Objective: {scene.objective}

## Characters in This Scene
{For each character: name, appearance, personality_summary, speech_style}

## The Interaction Log
{interaction_log — the raw sequence of actions/dialogue/thoughts}

## Writing Guidelines
1. Write in {perspective} (third-person limited / omniscient / first-person —
   configurable by author).
2. SHOW, don't tell. Convert "thought: Harry felt nervous" into vivid prose
   with physical sensations and imagery.
3. Weave narration BETWEEN dialogue lines. Describe body language, setting
   details, and atmosphere.
4. Preserve each character's unique speech style exactly as defined.
5. Internal thoughts should be rendered as italicized passages or free
   indirect discourse.
6. Add sensory details: sounds, smells, textures, lighting.
7. Maintain the scene's mood ({scene.mood}) throughout.
8. The prose should read as a complete, self-contained section of a novel.
   Include a natural opening and closing.

## Output
Write the scene as continuous prose. Do NOT include metadata, headers, or
stage directions. Just the story text.
```

### Style Configuration

The author can set global style preferences:

```python
class WritingStyle(BaseModel):
    perspective: str = "third_person_limited"   # or "first_person", "omniscient"
    pov_character_id: str | None = None          # for limited perspective
    prose_density: str = "moderate"              # "sparse", "moderate", "lush"
    dialogue_ratio: float = 0.4                  # rough target dialogue-to-narration ratio
    target_word_count_per_scene: int = 1500
    language: str = "ko"                         # output language
    author_style_notes: str = ""                 # e.g., "Write like Brandon Sanderson"
```

---

## 3.3 Episode-Level LangGraph Workflow

The full pipeline orchestrates multiple scenes sequentially:

```python
class EpisodePipelineState(TypedDict):
    # Inputs
    world_lore: WorldLore
    characters: dict[str, CharacterProfile]
    episode: Episode
    writing_style: WritingStyle
    # Working
    current_scene_index: int
    scenes: list[Scene]
    scene_prose_outputs: list[str]
    # Output
    final_episode_text: str

episode_graph = StateGraph(EpisodePipelineState)

episode_graph.add_node("director_plan_scenes", director_plan_scenes)
episode_graph.add_node("simulate_scene", simulate_current_scene)
episode_graph.add_node("check_lore", lore_check_current_scene)
episode_graph.add_node("rerun_scene", rerun_with_fixes)
episode_graph.add_node("write_scene", write_current_scene)
episode_graph.add_node("advance_scene", advance_to_next_scene)
episode_graph.add_node("assemble_episode", assemble_final_text)

episode_graph.add_edge(START, "director_plan_scenes")
episode_graph.add_edge("director_plan_scenes", "simulate_scene")
episode_graph.add_edge("simulate_scene", "check_lore")

episode_graph.add_conditional_edges("check_lore", lore_check_result, {
    "passed": "write_scene",
    "failed": "rerun_scene"
})
episode_graph.add_edge("rerun_scene", "check_lore")    # retry loop
episode_graph.add_edge("write_scene", "advance_scene")

episode_graph.add_conditional_edges("advance_scene", more_scenes, {
    "yes": "simulate_scene",
    "no": "assemble_episode"
})
episode_graph.add_edge("assemble_episode", END)
```

### `assemble_episode` Node

Concatenates all scene prose with appropriate scene breaks / transitions. Optionally adds:
- An episode title (auto-generated if author didn't provide one)
- A brief "Previously on…" teaser (for web novel format)
- Scene transition markers (e.g., `***` or `◇◇◇`)

---

## 3.4 Output Format

The final `episode.final_text` is a complete chapter. Example structure:

```
[Episode 3: 숲 속의 조우]

(scene 1 prose — ~1500 words)

◇◇◇

(scene 2 prose — ~1200 words)

◇◇◇

(scene 3 prose — ~1800 words)
```

Total estimated output per episode: **3,000 – 8,000 words** depending on scene count and density settings.

---

## 3.5 Testing Strategy

### Test 1: End-to-End Single Episode
- Input: Sample episode ("Harry receives his Hogwarts letter. Uncle Vernon tries to prevent it. Hagrid arrives.")
- Verify: Output is readable prose with multiple scenes, character-consistent dialogue, and world-consistent events.

### Test 2: Lore Checker Rejection
- Deliberately inject an interaction where a character violates a world rule.
- Verify: Lore Checker catches it, scene is re-simulated, violation is resolved.

### Test 3: Writer Quality
- Compare Writer output against the raw interaction log.
- Verify: Prose includes narration, sensory detail, and atmosphere — not just dialogue transcription.

---

## Deliverables Checklist

- [ ] `agents/lore_checker.py` — Validates interaction logs against world rules and character settings
- [ ] `agents/writer.py` — Transforms interaction logs into novel-quality prose
- [ ] `models/style.py` — `WritingStyle` configuration model
- [ ] `agents/episode_runner.py` — Full episode LangGraph pipeline (Director → Simulate → Check → Write → Assemble)
- [ ] Retry loop for lore violations works correctly (max 2 retries)
- [ ] End-to-end test: episode storyline in → finished chapter text out
