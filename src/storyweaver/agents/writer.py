"""Writer Agent — turns a scene's interaction log into novel prose.

This is the voice of the story: everything upstream produces structure, and
this is the only agent whose output the reader actually sees.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import (
    CharacterProfile,
    Episode,
    InteractionEntry,
    Scene,
    WorldLore,
    WritingStyle,
)
from storyweaver.models.style import describe_pacing

logger = logging.getLogger(__name__)

NO_MEMORY = "(no earlier episodes to carry forward)"
NO_PREVIOUS = "(this is the first scene of the episode — set the tone)"

# How much of the previous scene the Writer sees. Enough to catch the voice and
# the tics worth avoiding; not so much that it starts continuing it.
PREVIOUS_PROSE_CHARS = 1200


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


def _scene_mood(scene: Scene) -> str:
    """Scenes carry mood on their beats; take the first one that has it."""
    return next((beat.mood for beat in scene.beats if beat.mood), "as the scene dictates")


def _resolve_pov(scene: Scene, style: WritingStyle) -> tuple[str | None, str]:
    """Pick the POV character and the sentence naming them, for limited perspectives.

    A `pov_character_id` that isn't in the scene is useless to the writer, so
    fall back to whoever opens it — the Director orders participants by who
    drives the scene.
    """
    if "omniscient" in style.perspective:
        return None, ""

    pov = style.pov_character_id
    if pov not in scene.participating_character_ids:
        if pov is not None:
            logger.warning(
                "POV character %r is not in scene %d; using %r instead",
                pov,
                scene.scene_number,
                scene.participating_character_ids[0],
            )
        pov = scene.participating_character_ids[0]
    return pov, f" The point-of-view character for this scene is {pov}."


def build_prompt(
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    entries: Sequence[InteractionEntry] | None = None,
    style: WritingStyle | None = None,
    memory_context: str = "",
    previous_prose: str = "",
    pacing: str = "normal",
) -> str:
    """Render the Writer prompt for one scene."""
    style = style or WritingStyle()
    pov_id, pov_line = _resolve_pov(scene, style)

    if entries is not None:
        log_text = context.format_interaction_log(entries, characters=characters)
    else:
        log_text = "\n".join(scene.interaction_log) or context.NONE_PLACEHOLDER

    location = "an unspecified place"
    if scene.location_id:
        loc = next((l for l in world.locations if l.id == scene.location_id), None)
        location = f"{loc.name} — {loc.description}" if loc else scene.location_id

    return render_prompt(
        "writer",
        memory_context=memory_context or NO_MEMORY,
        previous_prose=(previous_prose[-PREVIOUS_PROSE_CHARS:] if previous_prose else NO_PREVIOUS),
        pacing=describe_pacing(pacing),
        genre=world.genre,
        tone=world.tone,
        location=location,
        objective=scene.objective,
        mood=_scene_mood(scene),
        world_summary=context.format_world_summary(world),
        world_rules=context.format_rules(world.rules),
        character_sheets=_character_sheets(
            characters, scene.participating_character_ids, pov_id
        ),
        interaction_log=log_text,
        perspective=style.describe_perspective(),
        pov_line=pov_line,
        density=style.describe_density(),
        target_word_count=style.target_word_count_per_scene,
        dialogue_percent=round(style.dialogue_ratio * 100),
        style_notes=style.author_style_notes or "(none)",
        language=style.language,
    )


def write_scene(
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    entries: Sequence[InteractionEntry] | None = None,
    style: WritingStyle | None = None,
    llm=None,
    memory_context: str = "",
    previous_prose: str = "",
    pacing: str = "normal",
) -> str:
    """Write one scene as prose.

    Pass `entries` when the structured log is on hand; otherwise the rendered
    strings already on `scene.interaction_log` are used.
    """
    if entries is not None and not entries:
        raise ValueError(f"Scene {scene.scene_number} has an empty interaction log")
    if entries is None and not scene.interaction_log:
        raise ValueError(f"Scene {scene.scene_number} has an empty interaction log")

    prompt = build_prompt(
        scene, world, characters, entries, style, memory_context, previous_prose, pacing
    )
    model = telemetry.meter(llm or get_llm(stage="writer"), "writer")
    result = model.invoke(prompt)
    prose = getattr(result, "content", result)
    return str(prose).strip()


def write_transition(
    previous_scene: Scene,
    next_scene: Scene,
    world: WorldLore,
    previous_prose: str,
    next_prose: str = "",
    style: WritingStyle | None = None,
    llm=None,
) -> str:
    """Write the sentence or two that carries the reader between two scenes.

    A hard cut between scenes reads as a jump even when both are good; this is a
    separate, cheap call rather than something folded into the scene prompt,
    because it needs the end of one scene and the start of the next at once.
    """
    style = style or WritingStyle()
    prompt = render_prompt(
        "transition",
        previous_location=_location_name(previous_scene, world),
        previous_mood=_scene_mood(previous_scene),
        previous_tail=previous_prose[-PREVIOUS_PROSE_CHARS:] or "(nothing)",
        next_location=_location_name(next_scene, world),
        next_mood=_scene_mood(next_scene),
        next_objective=next_scene.objective,
        next_head=next_prose[:PREVIOUS_PROSE_CHARS] or "(not written yet)",
        language=style.language,
    )
    model = telemetry.meter(llm or get_llm(stage="transition"), "transition")
    result = model.invoke(prompt)
    return str(getattr(result, "content", result)).strip()


def _location_name(scene: Scene, world: WorldLore) -> str:
    if not scene.location_id:
        return "unspecified"
    location = next((l for l in world.locations if l.id == scene.location_id), None)
    return location.name if location else scene.location_id
