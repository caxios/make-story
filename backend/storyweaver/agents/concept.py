"""Concept Agent — the only stage whose job is to originate.

Every other agent here transforms something: an outline into scenes, a scene
into prose, a chapter into memory. This one is handed nothing, or a hint, and
proposes whole stories; then it revises the one the author picked, as many
times as they want.

Two things keep unlimited refinement workable.

The model is sent **the current concept and one instruction**, never the
transcript. The concept carries the state, so the fiftieth round costs what the
first one did. The turns are stored for the author to look back at — they are
simply not replayed.

And what changed is worked out **here, by comparing**, rather than asked of the
model. A model asked to report its own edits describes what it meant to do; the
author needs to know what it actually did.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from storyweaver import telemetry
from storyweaver.agents.prompts import render_prompt
from storyweaver.agents.writer import _unwrap_content_blocks
from storyweaver.llm import get_llm
from storyweaver.models.concept import (
    ConceptCharacter,
    ConceptMessage,
    ConceptOutline,
    ConceptProposals,
    StoryConcept,
)

logger = logging.getLogger(__name__)

DEFAULT_COUNT = 3
# How many chapters an outline covers when the author does not say.
DEFAULT_EPISODES = 12
# Long prose is reported as "changed" rather than "A → B": an arc is five
# paragraphs, and a diff line nobody can read is a diff line nobody reads.
SHORT_VALUE = 40

NO_SEED = """The author has not said what they want. Range widely: the {count} concepts
should not share a genre, let alone a premise."""

WITH_SEED = """The author has said this much, and no more:

    {seed}

All {count} concepts must honour it. Differ underneath it — the same starting
point can carry very different books, and that is what this spread is for."""


# ---------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------


def build_propose_prompt(seed: str = "", count: int = DEFAULT_COUNT) -> str:
    seed = seed.strip()
    seed_block = (
        WITH_SEED.format(seed=seed, count=count)
        if seed
        else NO_SEED.format(count=count)
    )
    return render_prompt("concept_propose", count=count, seed_block=seed_block)


def propose(seed: str = "", count: int = DEFAULT_COUNT, llm=None) -> list[StoryConcept]:
    """Propose `count` concepts, from a hint or from nothing.

    One model call: the spread comes back together, because concepts proposed
    in separate calls cannot be made to differ from each other.
    """
    if count < 1:
        raise ValueError("propose needs to return at least one concept")

    prompt = build_propose_prompt(seed, count)
    model = telemetry.meter(llm or get_llm(stage="concept"), "concept")
    output: ConceptProposals = model.with_structured_output(ConceptProposals).invoke(prompt)

    concepts = [_tidy(concept) for concept in output.concepts]
    whole = [concept for concept in concepts if is_whole(concept)]

    for concept in concepts:
        if concept not in whole:
            logger.warning(
                "Dropping %r from the spread: it came back without %s",
                concept.title,
                ", ".join(missing_parts(concept)),
            )

    if not whole:
        raise ValueError("The concept agent returned no usable proposals")
    if len(whole) != count:
        logger.warning("Asked for %d concepts and kept %d", count, len(whole))
    return whole


# What a proposal has to have before it is worth showing to an author. A model
# asked for three complete concepts in one call will ration its output and
# starve the last one — it arrives as a title and a logline and nothing else,
# which is not a third option, it is a gap dressed as one.
REQUIRED = [
    ("title", "제목"),
    ("logline", "로그라인"),
    ("premise", "기획 의도"),
    ("arc", "전체 아크"),
    ("ending", "계획된 결말"),
]


def missing_parts(concept: StoryConcept) -> list[str]:
    missing = [label for field, label in REQUIRED if not str(getattr(concept, field) or "").strip()]
    if not concept.characters:
        missing.append("인물")
    return missing


def is_whole(concept: StoryConcept) -> bool:
    """Whether a proposal is complete enough to be one of the author's options."""
    return not missing_parts(concept)


# ---------------------------------------------------------------------------
# The chapter outline
# ---------------------------------------------------------------------------


def build_outline_prompt(concept: StoryConcept, count: int = DEFAULT_EPISODES) -> str:
    return render_prompt(
        "concept_outline",
        concept=concept.model_dump_json(indent=2),
        count=count,
    )


def outline(
    concept: StoryConcept, count: int = DEFAULT_EPISODES, llm=None
) -> StoryConcept:
    """Draw up the chapter outline for the concept the author kept.

    Separate from `propose` deliberately. Twelve lines per concept across a
    spread of three is thirty-six lines written to throw away twenty-four — and
    asking for all of it in one call is what made the model ration its output
    and return a third concept that was a title and nothing else.
    """
    if count < 1:
        raise ValueError("an outline needs at least one episode")

    prompt = build_outline_prompt(concept, count)
    model = telemetry.meter(llm or get_llm(stage="concept"), "concept")
    result: ConceptOutline = model.with_structured_output(ConceptOutline).invoke(prompt)

    if not result.episodes:
        raise ValueError("The concept agent returned an empty outline")
    return _tidy(concept.model_copy(update={"episodes": result.episodes}))


# ---------------------------------------------------------------------------
# Working it out by talking
# ---------------------------------------------------------------------------

# How many messages of the conversation the model is shown. This is the one
# place in the concept stage that replays a transcript, so it is the one place
# whose cost grows with use — a conversation that forgets what was said two
# lines ago is not a conversation, so there is no way around replaying it,
# only a limit on how far back.
#
# The oldest messages are dropped rather than summarised: a summary of the
# early conversation would be the model's account of what the author decided,
# and that account would then be treated as the decision itself.
TRANSCRIPT_WINDOW = 40

AUTHOR_LABEL = "작가"
AI_LABEL = "AI"

OPENING = "(아직 아무 말도 오가지 않았습니다. 작가에게 먼저 말을 거세요.)"


def format_transcript(messages: Sequence[ConceptMessage], window: int = TRANSCRIPT_WINDOW) -> str:
    """The conversation as the model reads it, oldest kept message first."""
    kept = list(messages)[-window:] if window > 0 else list(messages)
    if not kept:
        return OPENING

    lines = []
    if len(messages) > len(kept):
        lines.append(f"(앞의 {len(messages) - len(kept)}개 대화는 생략되었습니다)\n")
    for message in kept:
        label = AUTHOR_LABEL if message.role == "author" else AI_LABEL
        lines.append(f"{label}: {message.text.strip()}")
    return "\n\n".join(lines)


def build_talk_prompt(messages: Sequence[ConceptMessage]) -> str:
    return render_prompt("concept_talk", transcript=format_transcript(messages))


def reply_text(result: object) -> str:
    """The words out of a message, whatever shape the reply arrived in.

    Gemini answers with a list of content blocks rather than a string, and
    `str()` on that list puts `[{'type': 'text', 'text': '…'}]` — signature
    blobs and all — straight in front of the author. The Writer has met this
    already; `_unwrap_content_blocks` is the same repair, reused rather than
    written twice.
    """
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "\n\n".join(part for part in parts if part.strip()).strip()
    return _unwrap_content_blocks(str(content)).strip()


def talk(messages: Sequence[ConceptMessage], llm=None) -> str:
    """One reply in the conversation. Plain prose, not a structure.

    Deliberately unstructured. Asked for a schema the model fills every field,
    and filling every field is exactly what this stage must not do — the point
    is the half-formed thought the author can push back on.
    """
    prompt = build_talk_prompt(messages)
    model = telemetry.meter(llm or get_llm(stage="concept"), "concept")
    reply = reply_text(model.invoke(prompt))

    if not reply:
        raise ValueError("The concept agent returned an empty reply")
    return reply


def build_distill_prompt(messages: Sequence[ConceptMessage]) -> str:
    return render_prompt("concept_distill", transcript=format_transcript(messages, window=0))


def distill(messages: Sequence[ConceptMessage], llm=None) -> StoryConcept:
    """Write the conversation down as the concept it arrived at.

    The whole transcript is sent, not the window: this call happens once, and
    dropping the opening of a conversation here would drop the premise.
    """
    if not any(message.role == "author" for message in messages):
        raise ValueError("There is no conversation to build a concept from")

    prompt = build_distill_prompt(messages)
    model = telemetry.meter(llm or get_llm(stage="concept"), "concept")
    concept: StoryConcept = model.with_structured_output(StoryConcept).invoke(prompt)
    return _tidy(concept)


# ---------------------------------------------------------------------------
# Refining
# ---------------------------------------------------------------------------


def build_refine_prompt(concept: StoryConcept, instruction: str) -> str:
    return render_prompt(
        "concept_refine",
        concept=concept.model_dump_json(indent=2),
        instruction=instruction.strip(),
    )


def refine(
    concept: StoryConcept, instruction: str, llm=None
) -> tuple[StoryConcept, list[str]]:
    """Revise a concept once. Returns the new one and what actually moved."""
    if not instruction.strip():
        raise ValueError("refine needs an instruction")

    prompt = build_refine_prompt(concept, instruction)
    model = telemetry.meter(llm or get_llm(stage="concept"), "concept")
    revised: StoryConcept = model.with_structured_output(StoryConcept).invoke(prompt)

    revised = _tidy(revised)
    return revised, describe_changes(concept, revised)


# ---------------------------------------------------------------------------
# Tidying
# ---------------------------------------------------------------------------


def _tidy(concept: StoryConcept) -> StoryConcept:
    """Fix what a model routinely gets slightly wrong, without inventing.

    Episodes are renumbered from 1 and kept in order, and a relationship that
    names somebody who is not in this concept is dropped — it would otherwise
    become a dangling id at commit, pointing at a character who was never
    created.
    """
    episodes = [
        episode.model_copy(update={"number": index})
        for index, episode in enumerate(concept.episodes, start=1)
        if episode.line.strip()
    ]

    names = {character.name for character in concept.characters}
    characters = []
    for character in concept.characters:
        kept = []
        for relationship in character.relationships:
            target = relationship.split("—")[0].strip()
            if target and target in names and target != character.name:
                kept.append(relationship.strip())
            elif relationship.strip():
                logger.warning(
                    "Dropping %s's relationship to %r, who is not in this concept",
                    character.name,
                    target,
                )
        characters.append(character.model_copy(update={"relationships": kept}))

    return concept.model_copy(update={"episodes": episodes, "characters": characters})


# ---------------------------------------------------------------------------
# What moved
# ---------------------------------------------------------------------------

SCALARS = [
    ("title", "제목"),
    ("logline", "로그라인"),
    ("genre", "장르"),
    ("tone", "분위기"),
    ("era", "시대"),
    ("premise", "기획 의도"),
    ("arc", "전체 아크"),
    ("ending", "계획된 결말"),
]

LISTS = [("rules", "규칙"), ("locations", "장소"), ("factions", "세력")]

CHARACTER_FIELDS = [
    ("role", "역할"),
    ("age", "나이"),
    ("gender", "성별"),
    ("appearance", "외모"),
    ("personality", "성격"),
    ("speech", "말투"),
    ("goal", "목표"),
    ("secret", "비밀"),
]


def _scalar_line(label: str, before: object, after: object) -> str:
    """`A → B` when both are short enough to read, otherwise just the name."""
    old, new = str(before or "").strip(), str(after or "").strip()
    if len(old) <= SHORT_VALUE and len(new) <= SHORT_VALUE:
        return f"{label}: {old or '(없음)'} → {new or '(없음)'}"
    return f"{label}이(가) 바뀌었습니다"


def _character_lines(before: StoryConcept, after: StoryConcept) -> list[str]:
    lines: list[str] = []
    old_names = [c.name for c in before.characters]
    new_names = [c.name for c in after.characters]

    for name in new_names:
        if name not in old_names:
            lines.append(f"인물 추가: {name}")
    for name in old_names:
        if name not in new_names:
            lines.append(f"인물 삭제: {name}")

    for character in after.characters:
        previous = before.character(character.name)
        if previous is None:
            continue
        for field, label in CHARACTER_FIELDS:
            old, new = getattr(previous, field), getattr(character, field)
            if old != new:
                lines.append(f"{character.name} · {_scalar_line(label, old, new)}")
        if previous.relationships != character.relationships:
            lines.append(f"{character.name} · 인간관계가 바뀌었습니다")
    return lines


def describe_changes(before: StoryConcept, after: StoryConcept) -> list[str]:
    """What actually moved between two concepts, in the author's language.

    Computed by comparing rather than asked of the model: a model asked what it
    changed reports its intention, and the intention is not what the author has
    to live with.
    """
    lines: list[str] = []

    for field, label in SCALARS:
        old, new = getattr(before, field), getattr(after, field)
        if old != new:
            lines.append(_scalar_line(label, old, new))

    for field, label in LISTS:
        old, new = getattr(before, field), getattr(after, field)
        if old == new:
            continue
        added = [item for item in new if item not in old]
        removed = [item for item in old if item not in new]
        if added:
            lines.append(f"{label} 추가: {', '.join(added)}")
        if removed:
            lines.append(f"{label} 삭제: {', '.join(removed)}")
        if not added and not removed:
            lines.append(f"{label}의 순서나 표현이 바뀌었습니다")

    lines.extend(_character_lines(before, after))

    if len(before.episodes) != len(after.episodes):
        lines.append(f"회차 수: {len(before.episodes)}개 → {len(after.episodes)}개")
    else:
        moved = sum(
            1
            for old, new in zip(before.episodes, after.episodes)
            if old.line.strip() != new.line.strip()
        )
        if moved:
            lines.append(f"회차 구상 {moved}개가 바뀌었습니다")

    return lines or ["바뀐 것이 없습니다"]


__all__ = [
    "DEFAULT_COUNT",
    "DEFAULT_EPISODES",
    "TRANSCRIPT_WINDOW",
    "build_distill_prompt",
    "build_outline_prompt",
    "build_propose_prompt",
    "build_refine_prompt",
    "build_talk_prompt",
    "describe_changes",
    "distill",
    "format_transcript",
    "is_whole",
    "missing_parts",
    "outline",
    "propose",
    "refine",
    "reply_text",
    "talk",
]
