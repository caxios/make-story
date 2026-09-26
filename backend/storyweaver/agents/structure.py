"""Laying the work out across its planned length.

One model call turns "this is a 400-episode story" into parts and planned
threads. The same call serves the concept stage (before anything is written)
and a redraw afterwards (when the author changes the length, or the story has
moved and the plan should follow): after the first chapters are written, what
they established is shown too, and the parts already behind the story are kept
as they happened.

Deliberately separate from outlining episodes. Asked to lay out four hundred
episodes *and* write the first twelve in one answer, a model rations its output
across both — the same thing that once made a third concept arrive as a title
and nothing else.
"""

from __future__ import annotations

import logging

from storyweaver import telemetry
from storyweaver.agents.prompts import render_prompt
from storyweaver.llm import MODEL_MAX_OUTPUT_TOKENS, get_llm
from storyweaver.models.concept import ConceptOutline
from storyweaver.models.structure import (
    StoryStructure,
    StructureDraft,
    describe_structure,
    tidy_structure,
)

logger = logging.getLogger(__name__)


def describe_concept(concept) -> str:
    """A concept as the layout needs it: the story, not the form fields."""
    lines = [
        f"제목: {concept.title}",
        f"한 줄 요약: {concept.logline}",
        f"장르/톤: {concept.genre} / {concept.tone}",
    ]
    if concept.premise.strip():
        lines.append(f"기획 의도:\n{concept.premise.strip()}")
    if concept.arc.strip():
        lines.append(f"전체 아크:\n{concept.arc.strip()}")
    if concept.ending.strip():
        lines.append(f"계획된 결말:\n{concept.ending.strip()}")
    if concept.characters:
        lines.append("인물:")
        for character in concept.characters:
            parts = [f"- {character.name} ({character.role})"]
            if character.goal.strip():
                parts.append(f"목표: {character.goal.strip()}")
            if character.secret.strip():
                parts.append(f"비밀: {character.secret.strip()}")
            lines.append(" / ".join(parts))
    if concept.rules:
        lines.append("세계의 규칙: " + "; ".join(concept.rules))
    if concept.factions:
        lines.append("세력: " + ", ".join(concept.factions))
    return "\n".join(lines)


def build_prompt(
    target: int,
    work: str,
    *,
    story_so_far: str = "",
    written_through: int = 0,
    instruction: str = "",
) -> str:
    so_far = ""
    fixed = ""
    if story_so_far.strip():
        so_far = (
            "## What has been written so far\n\n"
            f"{story_so_far.strip()}"
        )
    if written_through > 0:
        fixed = (
            f"Episodes 1 to {written_through} are already written: the parts covering "
            "them must describe what actually happened there, and the plan picks up "
            f"from episode {written_through + 1}. Threads the written chapters have "
            "already planted keep their place; plan their payoff."
        )
    return render_prompt(
        "structure_layout",
        target=target,
        work=work.strip(),
        so_far=so_far,
        fixed=fixed,
        instruction=(
            f"## What the author asked for\n\n{instruction.strip()}" if instruction.strip() else ""
        ),
    )


def lay_out(
    target: int,
    work: str,
    *,
    story_so_far: str = "",
    written_through: int = 0,
    instruction: str = "",
    llm=None,
    stage: str = "concept",
) -> StoryStructure:
    """Parts and planned threads for a work of `target` episodes."""
    if target < 1:
        raise ValueError("a work needs at least one episode")

    prompt = build_prompt(
        target, work,
        story_so_far=story_so_far, written_through=written_through, instruction=instruction,
    )
    # A layout for hundreds of episodes and a large cast is long; cut short, it
    # loses its last parts and relationships without saying so.
    model = telemetry.meter(
        llm or get_llm(stage=stage, max_output_tokens=MODEL_MAX_OUTPUT_TOKENS), stage
    )
    draft: StructureDraft = model.with_structured_output(StructureDraft).invoke(prompt)
    if not draft.parts:
        raise ValueError("The model returned no parts for the structure")

    structure = tidy_structure(
        StoryStructure(
            target_episodes=target,
            parts=draft.parts,
            threads=draft.threads,
            relationships=draft.relationships,
        )
    )
    logger.info(
        "Laid out %d episodes in %d parts with %d threads and %d relationships",
        target, len(structure.parts), len(structure.threads), len(structure.relationships),
    )
    return structure


def build_rewrite_prompt(
    structure: StoryStructure,
    *,
    title: str,
    work: str,
    story_so_far: str,
    current: dict[int, str],
) -> str:
    numbers = sorted(current)
    return render_prompt(
        "structure_episodes",
        title=title,
        work=work.strip(),
        layout=describe_structure(structure),
        so_far=story_so_far.strip() or "(아직 쓴 회차가 없습니다. 1화부터 시작합니다.)",
        current="\n".join(f"{n}화: {current[n]}" for n in numbers),
        numbers=", ".join(str(n) for n in numbers),
    )


def rewrite_upcoming(
    structure: StoryStructure,
    current: dict[int, str],
    *,
    title: str,
    work: str,
    story_so_far: str = "",
    llm=None,
) -> dict[int, str]:
    """New outlines for unwritten episodes, paced to the layout.

    `current` maps episode number to the outline it has now. Returns the same
    numbers with their new outlines; a number the model skipped keeps its old
    outline rather than being emptied.
    """
    if not current:
        return {}
    prompt = build_rewrite_prompt(
        structure, title=title, work=work, story_so_far=story_so_far, current=current
    )
    model = telemetry.meter(
        llm or get_llm(stage="planner", max_output_tokens=MODEL_MAX_OUTPUT_TOKENS), "planner"
    )
    result: ConceptOutline = model.with_structured_output(ConceptOutline).invoke(prompt)

    drawn = {e.number: e.line.strip() for e in result.episodes if e.line.strip()}
    if not drawn:
        raise ValueError("The model returned no outlines")
    missing = [n for n in current if n not in drawn]
    if missing:
        logger.warning("Re-outlining skipped episodes %s; they keep their outlines", missing)
    return {n: drawn.get(n, current[n]) for n in current}
