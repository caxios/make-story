"""Lore Checker — the quality gate between character simulation and the Writer.

Validates an interaction log against the world's rules and the characters' own
definitions, and returns fixes concrete enough to feed straight back into a
re-run of the scene.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, InteractionEntry, Scene, WorldLore

logger = logging.getLogger(__name__)

ViolationCategory = Literal[
    "world_rule",
    "character_inconsistency",
    "relationship_contradiction",
    "continuity",
]


class Violation(BaseModel):
    """One thing the log gets wrong, and what to do about it."""

    turn: int = Field(description="Turn number of the offending log entry")
    category: ViolationCategory
    violated: str = Field(description="The rule or character setting that was broken")
    suggested_fix: str = Field(description="A rewrite instruction addressed to the character")
    offending_content: str = ""


class ValidationResult(BaseModel):
    """The Lore Checker's verdict on a scene's interaction log."""

    passed: bool
    violations: list[Violation] = Field(default_factory=list)

    @property
    def first_bad_turn(self) -> int | None:
        """The earliest turn that needs redoing, or None if the log is clean."""
        return min((v.turn for v in self.violations), default=None)

    def constraints(self) -> list[str]:
        """The fixes, phrased as instructions to inject into character prompts."""
        return [
            f"{v.suggested_fix} (this corrects a {v.category.replace('_', ' ')} "
            f"on turn {v.turn}: {v.violated})"
            for v in self.violations
        ]


def _character_constraints(
    characters: Mapping[str, CharacterProfile], present_ids: Sequence[str]
) -> str:
    """Per-character crib sheet: what each one is, wants, feels and hides."""
    blocks = []
    for cid in present_ids:
        character = characters.get(cid)
        if character is None:
            continue
        blocks.append(
            "\n".join(
                [
                    f"### {character.name} ({character.id})",
                    character.personality_summary,
                    f"Speech: {character.speech_style}",
                    "Traits:",
                    context.format_traits(character),
                    "Relationships with others present:",
                    context.format_relationships(character, present_ids, characters),
                    "Secrets they must not casually reveal:",
                    context.format_bullets(character.secrets),
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else context.NONE_PLACEHOLDER


def build_prompt(
    entries: Sequence[InteractionEntry],
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    scene: Scene | None = None,
) -> str:
    """Render the Lore Checker prompt for a scene's log."""
    present_ids = (
        scene.participating_character_ids
        if scene is not None
        else sorted({e.character_id for e in entries})
    )
    location = "unspecified"
    if scene is not None and scene.location_id:
        loc = next((l for l in world.locations if l.id == scene.location_id), None)
        location = f"{loc.name} — {loc.description}" if loc else scene.location_id

    return render_prompt(
        "lore_checker",
        world_summary=context.format_world_summary(world),
        world_rules=context.format_rules(world.rules),
        character_constraints=_character_constraints(characters, present_ids),
        scene_title=scene.title if scene is not None else "unspecified",
        location=location,
        objective=scene.objective if scene is not None else "unspecified",
        interaction_log=context.format_interaction_log(
            entries, characters=characters, show_turns=True
        ),
    )


def _normalise(result: ValidationResult, valid_turns: set[int]) -> ValidationResult:
    """Reconcile the verdict with the violations, and drop ones we can't act on.

    Models routinely return `passed: true` alongside a list of violations (or
    the reverse), and occasionally cite a turn that isn't in the log. The list
    is the substance; `passed` is derived from it.
    """
    kept, dropped = [], []
    for violation in result.violations:
        (kept if violation.turn in valid_turns else dropped).append(violation)
    if dropped:
        logger.warning(
            "Lore Checker cited turns not present in the log: %s",
            sorted(v.turn for v in dropped),
        )
    return ValidationResult(passed=not kept, violations=kept)


def check(
    entries: Sequence[InteractionEntry],
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    scene: Scene | None = None,
    llm=None,
) -> ValidationResult:
    """Validate an interaction log. An empty log trivially passes."""
    if not entries:
        return ValidationResult(passed=True)

    prompt = build_prompt(entries, world, characters, scene)
    model = telemetry.meter(llm or get_llm(stage="lore"), "lore")
    result: ValidationResult = model.with_structured_output(ValidationResult).invoke(prompt)

    return _normalise(result, {e.turn for e in entries})
