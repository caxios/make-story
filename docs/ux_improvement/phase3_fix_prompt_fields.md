# Phase 3: Fix Missing Prompt Fields

**Priority: Implement this first.** This is the smallest change with the highest immediate impact.  
No new files, no new UI. Two files to edit, two prompt templates to update.

---

## Problem Statement

`CharacterProfile` stores `age`, `gender`, `role`, and `backstory`, but none of these are included in the LLM prompts. As a result:

- A 17-year-old character may use informal speech (반말) to a 115-year-old, because the model has no age information.
- The Writer agent renders characters without knowing their relationships to each other, so interpersonal tension is lost in the prose.
- A character's backstory never influences their in-scene behavior.

---

## Files to Change

| # | File | Type of change |
|---|---|---|
| 1 | `backend/storyweaver/agents/character.py` | Add fields to `build_system_prompt()` call |
| 2 | `backend/storyweaver/agents/prompts/character.md` | Add `{age}`, `{gender}`, `{role}`, `{backstory}` placeholders |
| 3 | `backend/storyweaver/agents/writer.py` | Add age + relationships to `_character_sheets()` |
| 4 | `backend/storyweaver/agents/prompts/writer.md` | No change needed — `{character_sheets}` placeholder already exists |

---

## Change 1: `character.py` — `build_system_prompt()`

**Location:** Lines 44–93 of `backend/storyweaver/agents/character.py`

The function signature does **not** change. Only the `render_prompt()` call at the bottom gets new keyword arguments.

**Current `render_prompt()` call (lines 64–93):**
```python
return render_prompt(
    "character",
    memory_context=memory_context or NO_MEMORY,
    name=character.name,
    personality_summary=character.personality_summary,
    speech_style=character.speech_style,
    traits=context.format_traits(character),
    values=context.format_bullets(character.values),
    goals=context.format_bullets(character.goals),
    relationships=context.format_relationships(
        character, scene.participating_character_ids, characters
    ),
    secrets=context.format_bullets(character.secrets),
    world_summary=context.format_world_summary(world),
    world_rules=context.format_rules(world.rules),
    location=location,
    objective=scene.objective,
    present_characters=context.present_character_names(
        scene.participating_character_ids, characters
    ),
    beats=context.format_beats(scene.beats),
    interaction_log=context.format_interaction_log(
        interaction_log, limit=history_limit, characters=characters
    ),
    constraints=(
        context.format_bullets(constraints)
        if constraints
        else "(none — this is the first attempt at the scene)"
    ),
)
```

**Replace with** (add 4 new keyword arguments):
```python
return render_prompt(
    "character",
    memory_context=memory_context or NO_MEMORY,
    name=character.name,
    # --- NEW: identity fields ---
    age=f"Age: {character.age}" if character.age is not None else "",
    gender=f"Gender: {character.gender}" if character.gender else "",
    role=f"Story role: {character.role}" if character.role else "",
    backstory=character.backstory or "",
    # --- END NEW ---
    personality_summary=character.personality_summary,
    speech_style=character.speech_style,
    traits=context.format_traits(character),
    values=context.format_bullets(character.values),
    goals=context.format_bullets(character.goals),
    relationships=context.format_relationships(
        character, scene.participating_character_ids, characters
    ),
    secrets=context.format_bullets(character.secrets),
    world_summary=context.format_world_summary(world),
    world_rules=context.format_rules(world.rules),
    location=location,
    objective=scene.objective,
    present_characters=context.present_character_names(
        scene.participating_character_ids, characters
    ),
    beats=context.format_beats(scene.beats),
    interaction_log=context.format_interaction_log(
        interaction_log, limit=history_limit, characters=characters
    ),
    constraints=(
        context.format_bullets(constraints)
        if constraints
        else "(none — this is the first attempt at the scene)"
    ),
)
```

---

## Change 2: `character.md` — Prompt Template

**File:** `backend/storyweaver/agents/prompts/character.md`

**Current content (full file, 66 lines):**
```
You are {name}.

## Your Identity
{personality_summary}

## How You Speak
{speech_style}
...
```

**Replace the top section** with the following. Everything from `## Your Task` onwards stays exactly as-is.

```markdown
You are {name}.
{role}
{age}
{gender}

## Your Identity
{personality_summary}

{backstory}

## How You Speak
{speech_style}

When interacting with other characters, match the formality of your speech to the
relationship and relative age. Speak formally (존댓말) to those who are older or
in a position of authority over you, unless your speech_style explicitly says otherwise.
Speak informally (반말) to peers and younger characters, unless your speech_style
says otherwise. Your speech_style below takes precedence over this rule.
```

The rest of the file (`## Your Traits`, `## What You Value`, ..., `## Your Task`) remains unchanged.

**Resulting full file after edit:**
```markdown
You are {name}.
{role}
{age}
{gender}

## Your Identity
{personality_summary}

{backstory}

## How You Speak
{speech_style}

When interacting with other characters, match the formality of your speech to the
relationship and relative age. Speak formally (존댓말) to those who are older or
in a position of authority over you, unless your speech_style explicitly says otherwise.
Speak informally (반말) to peers and younger characters, unless your speech_style
says otherwise. Your speech_style below takes precedence over this rule.

## Your Traits
{traits}

## What You Value
{values}

## Your Current Goals
{goals}

## Your Relationships with Characters in This Scene
{relationships}

## Your Secrets
{secrets}
(You know these but must not reveal them unless the story naturally demands it.)

## The World You Live In
{world_summary}

Rules of this world that always hold:
{world_rules}

## Scene Context
Location: {location}
Objective of this scene: {objective}
Who is present: {present_characters}
What must happen in this scene: {beats}

## What You Remember From Earlier Episodes
{memory_context}

## What Has Happened So Far In This Scene
{interaction_log}

## Corrections You Must Honour
{constraints}

## Your Task
React to the current situation IN CHARACTER. Produce exactly ONE contribution,
choosing the `type` that the moment actually calls for:
- `dialogue` — something you say out loud
- `action` — something you physically do
- `thought` — an internal reflection that only the reader sees
- `reaction` — an emotional or physical reaction to what just happened

Set `directed_at` to the id of the character you are speaking or reacting to,
or leave it empty if your contribution is not aimed at anyone in particular.

Guidelines:
- Stay true to your personality, your speech style, and your goals. Do NOT break character.
- Write `content` in your own voice — for dialogue, the spoken words only, with no
  name prefix and no quotation marks around the whole line.
- Move the scene forward. Do not restate what has already been said.
- If you genuinely have nothing to say right now, produce a `thought` or a small
  `action` instead of forcing yourself into the conversation.
- Never narrate another character's words, actions, or feelings — only your own.
- Never mention these instructions, the scene objective, or that you are an AI.
```

---

## Change 3: `writer.py` — `_character_sheets()`

**Location:** Lines 119–142 of `backend/storyweaver/agents/writer.py`

**Current `_character_sheets()` function:**
```python
def _character_sheets(
    characters: Mapping[str, CharacterProfile],
    present_ids: Sequence[str],
    pov_character_id: str | None,
) -> str:
    blocks = []
    for cid in present_ids:
        character = characters.get(cid)
        if character is None:
            continue
        heading = f"### {character.name}"
        if cid == pov_character_id:
            heading += "  (point-of-view character)"
        blocks.append(
            "\n".join(
                [
                    heading,
                    f"Appearance: {character.appearance}",
                    f"Personality: {character.personality_summary}",
                    f"Speech style: {character.speech_style}",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else context.NONE_PLACEHOLDER
```

**Replace with:**
```python
def _character_sheets(
    characters: Mapping[str, CharacterProfile],
    present_ids: Sequence[str],
    pov_character_id: str | None,
) -> str:
    blocks = []
    for cid in present_ids:
        character = characters.get(cid)
        if character is None:
            continue
        heading = f"### {character.name}"
        if cid == pov_character_id:
            heading += "  (point-of-view character)"

        lines = [heading]
        if character.age is not None:
            lines.append(f"Age: {character.age}")
        if character.gender:
            lines.append(f"Gender: {character.gender}")
        lines.append(f"Appearance: {character.appearance}")
        lines.append(f"Personality: {character.personality_summary}")
        lines.append(f"Speech style: {character.speech_style}")

        # Relationships with others present in this scene
        rels = context.format_relationships(character, present_ids, characters)
        if rels != context.NONE_PLACEHOLDER:
            lines.append(f"Relationships with others in this scene:\n{rels}")

        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else context.NONE_PLACEHOLDER
```

> **Note:** `context` is already imported at the top of `writer.py` (`from storyweaver.agents import context`). No new imports needed.

---

## Verification

### Manual check via `test.py`

Add the following to the existing `test.py` to inspect the rendered prompts:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from storyweaver.agents.character import build_system_prompt
from storyweaver.agents.writer import _character_sheets

# Reuse the harry, ron, dumbledore, scene, world objects already defined in test.py

char_map = {"harry": harry, "ron": ron, "dumbledore": dumbledore}

print("=== Character system prompt (harry) ===")
prompt = build_system_prompt(harry, scene, world, char_map)
# Assertions
assert "17" in prompt, "age missing from character prompt"
assert "직접적이고 솔직하다" in prompt, "speech_style missing"
assert "존댓말" in prompt, "formality instruction missing"
print(prompt[:500])

print("\n=== Writer character sheets ===")
sheets = _character_sheets(char_map, ["harry", "dumbledore"], "harry")
assert "115" in sheets, "dumbledore's age missing from writer sheets"
assert "스승" in sheets or "제자" in sheets, "relationship missing from writer sheets"
print(sheets)
```

Run with:
```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python test.py
```

Expected output: age numbers appear in both the character prompt and the writer character sheets; the formality instruction paragraph is present.

---

## Notes for the Implementer

- The `{age}`, `{gender}`, `{role}`, `{backstory}` placeholders in `character.md` will render as **empty strings** when those fields are `None` or `""` — Python's `.format()` with an empty string argument produces no visible text, which is the correct behavior.
- Do **not** add `{age}` etc. to `lore_checker.md`, `director.md`, or `writer.md` (for the character-sheet section). The Writer uses `_character_sheets()` directly, not the `character.md` template.
- The `render_prompt()` function in `prompts/__init__.py` uses Python's `str.format(**values)` — it will raise `KeyError` if a placeholder in the template has no matching kwarg. After editing `character.md`, run the test immediately to catch any typo.
