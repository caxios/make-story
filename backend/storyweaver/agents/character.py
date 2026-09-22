"""Character Agent — one shared LLM, a different system prompt per character.

A character's whole identity lives in the prompt built from their
`CharacterProfile`, so adding a character costs nothing but data.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import (
    CharacterProfile,
    InteractionEntry,
    InteractionType,
    Scene,
    WorldLore,
)

logger = logging.getLogger(__name__)

# How many prior turns a character can see. Keeps the prompt bounded on long
# scenes; Phase 4 replaces this window with retrieved memory.
DEFAULT_HISTORY_LIMIT = 12
NO_MEMORY = "(nothing yet — this is the first time we meet you)"


class CharacterTurn(BaseModel):
    """A single in-character contribution, as returned by the model."""

    type: InteractionType = Field(description="dialogue, action, thought, or reaction")
    content: str = Field(description="The line, act, thought, or reaction itself")
    directed_at: str | None = Field(
        default=None, description="Id of the character this is aimed at, or null"
    )


def _identity_line(character: CharacterProfile) -> str:
    """Role, age and gender on one line — the parts that are actually filled in.

    These live on every `CharacterProfile` and reached no prompt until now,
    which is why a seventeen-year-old could address a forty-seven-year-old in
    반말: the model had never been told either age.

    One line rather than one line each, so a character with none of the three
    does not open their prompt with three blank lines.
    """
    parts = []
    if character.role.strip():
        parts.append(context.describe_role(character.role))
    if character.age is not None:
        parts.append(f"{character.age}세")
    if (character.gender or "").strip():
        parts.append(character.gender.strip())
    # The newline belongs to the line, not to the template — a character with
    # none of the three should leave no gap behind at all.
    return "\n" + " · ".join(parts) if parts else ""


def build_system_prompt(
    character: CharacterProfile,
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    interaction_log: Sequence[InteractionEntry] = (),
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    constraints: Sequence[str] = (),
    memory_context: str = "",
    extra_sections: str = "",
) -> str:
    """Render this character's system prompt for the current point in the scene.

    `constraints` carries the Lore Checker's suggested fixes on a re-run, so a
    corrected scene is steered rather than merely re-rolled.
    """
    location = "an unspecified place"
    if scene.location_id:
        loc = next((l for l in world.locations if l.id == scene.location_id), None)
        location = f"{loc.name} — {loc.description}" if loc else scene.location_id

    return render_prompt(
        "character",
        memory_context=memory_context or NO_MEMORY,
        name=character.name,
        identity_line=_identity_line(character),
        # Sections the author added to this character's wiki page. They have no
        # typed field to land in, so this is the only way they reach the model.
        extra_sections=extra_sections,
        # Like the identity line, this carries its own spacing so that a
        # character without one leaves no gap in the prompt.
        backstory=f"\n\n{character.backstory.strip()}" if character.backstory.strip() else "",
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


def _clean_directed_at(
    turn: CharacterTurn, speaker_id: str, present_ids: Sequence[str]
) -> str | None:
    """Keep `directed_at` only when it names another character actually in the scene."""
    target = (turn.directed_at or "").strip()
    if not target or target == speaker_id:
        return None
    if target not in present_ids:
        logger.warning("%s directed a turn at %r, who is not in the scene", speaker_id, target)
        return None
    return target


def act(
    character: CharacterProfile,
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    interaction_log: Sequence[InteractionEntry] = (),
    turn: int = 1,
    llm=None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    constraints: Sequence[str] = (),
    memory_context: str = "",
    extra_sections: str = "",
) -> InteractionEntry:
    """Produce this character's contribution for one turn of the scene."""
    prompt = build_system_prompt(
        character,
        scene,
        world,
        characters,
        interaction_log,
        history_limit,
        constraints,
        memory_context,
        extra_sections,
    )
    model = telemetry.meter(llm or get_llm(stage="character"), "character")
    result: CharacterTurn = model.with_structured_output(CharacterTurn).invoke(prompt)

    return InteractionEntry(
        turn=turn,
        character_id=character.id,
        type=result.type,
        content=result.content.strip(),
        directed_at=_clean_directed_at(result, character.id, scene.participating_character_ids),
    )
