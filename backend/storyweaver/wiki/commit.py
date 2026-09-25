"""Turning an agreed concept into a project.

This is the only place in the concept feature that writes, and it writes four
things at once: the world, the cast, the work's own wiki page, and the episode
queue. Partial success is the failure to avoid — half a cast and no world is
worse than nothing, because the author cannot tell by looking what happened.
So the caller holds one lock around the whole thing.

Every value lands as the **first entry** in its chronicle chain rather than as
a decision. That is the point of committing here rather than straight into the
models: a character invented at the concept stage can be rewritten or deleted
twenty episodes later, and the arc can be redrawn, and all of it stays visible
as history.

No model calls. Everything was settled while refining.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from storyweaver.ids import unique_id
from storyweaver.models import CharacterProfile, Location, Rule
from storyweaver.models.concept import StoryConcept
from storyweaver.wiki.sections import STORY_SUBJECT_ID

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore
    from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

# Where a rule goes when the concept did not say what kind it is. The concept
# stage deals in sentences, not taxonomies.
DEFAULT_RULE_CATEGORY = "society"


class CommitReport:
    """What a commit created, for the author to be told."""

    def __init__(self) -> None:
        self.characters: list[str] = []
        self.rules: list[str] = []
        self.locations: list[str] = []
        self.episodes: int = 0
        self.entries: int = 0
        self.dropped: list[str] = []

    def as_dict(self) -> dict:
        return {
            "characters": self.characters,
            "rules": self.rules,
            "locations": self.locations,
            "episodes": self.episodes,
            "chronicle_entries": self.entries,
            "dropped": self.dropped,
        }


# How many words of a rule's statement become its id. The Lore Checker cites
# rules by id and the author sees them in the World Builder, so the id has to
# be readable — and a character slice of a Korean sentence ends mid-word.
RULE_ID_WORDS = 4


def _rule_id_source(statement: str) -> str:
    """The opening words of a rule, cut where words actually end."""
    return " ".join(statement.split()[:RULE_ID_WORDS])


def _role(proposed: str) -> str:
    """Keep the role if the workshop offers it, otherwise fall back.

    An invented role is not an error — `CharacterProfile.role` is free text and
    a serial invents its own — but one that matches the dropdown drops straight
    into the UI the author will edit it in.
    """
    value = (proposed or "").strip()
    return value if value else "조연"


def _relationship_note(raw: str) -> tuple[str, str]:
    """`"시월 — 경계하는 상대"` → `("시월", "경계하는 상대")`."""
    name, _, described = raw.partition("—")
    return name.strip(), described.strip()


def commit_concept(
    project: Project,
    chronicle: ChronicleStore | None,
    concept: StoryConcept,
    turns: list | None = None,
    messages: list | None = None,
) -> CommitReport:
    """Write an agreed concept into `project` and the chronicle.

    `project` is mutated and must be saved by the caller, inside the same lock
    this was called under.
    """
    report = CommitReport()

    # --- the world ---------------------------------------------------------
    project.world = project.world.model_copy(
        update={
            "title": concept.title.strip() or project.world.title,
            "genre": concept.genre.strip() or project.world.genre,
            "tone": concept.tone.strip(),
            "era": (concept.era or "").strip() or None,
            "overview": concept.premise.strip(),
            "factions": [f.strip() for f in concept.factions if f.strip()],
        }
    )

    taken_rules: set[str] = {rule.id for rule in project.world.rules}
    for index, statement in enumerate(concept.rules, start=1):
        statement = statement.strip()
        if not statement:
            continue
        rule_id = unique_id(_rule_id_source(statement), f"rule-{index}", taken_rules)
        taken_rules.add(rule_id)
        project.upsert_rule(
            Rule(id=rule_id, category=DEFAULT_RULE_CATEGORY, statement=statement)
        )
        report.rules.append(rule_id)

    taken_places: set[str] = {place.id for place in project.world.locations}
    for index, name in enumerate(concept.locations, start=1):
        name = name.strip()
        if not name:
            continue
        place_id = unique_id(name, f"location-{index}", taken_places)
        taken_places.add(place_id)
        project.upsert_location(Location(id=place_id, name=name, description=""))
        report.locations.append(place_id)

    # --- the cast ----------------------------------------------------------
    #
    # Ids first, for everybody, because a relationship can name someone who is
    # created later in the list and would otherwise resolve to nothing.
    taken_people: set[str] = {character.id for character in project.characters}
    ids: dict[str, str] = {}
    for index, proposed in enumerate(concept.characters, start=1):
        name = proposed.name.strip()
        if not name:
            continue
        character_id = unique_id(name, f"character-{index}", taken_people)
        taken_people.add(character_id)
        ids[name] = character_id

    for proposed in concept.characters:
        name = proposed.name.strip()
        if name not in ids:
            continue
        relationships = []
        for raw in proposed.relationships:
            target_name, described = _relationship_note(raw)
            target_id = ids.get(target_name)
            if target_id is None or target_id == ids[name]:
                report.dropped.append(f"{name}의 관계 '{raw}'")
                logger.warning(
                    "Dropping %s's relationship %r: %r is not in this cast", name, raw, target_name
                )
                continue
            relationships.append(
                {
                    "target_character_id": target_id,
                    "type": described or "관계",
                    "sentiment": 0.0,
                    "description": None,
                }
            )

        project.upsert_character(
            CharacterProfile(
                id=ids[name],
                name=name,
                role=_role(proposed.role),
                age=proposed.age,
                gender=(proposed.gender or "").strip() or None,
                appearance=proposed.appearance.strip(),
                personality_summary=proposed.personality.strip(),
                speech_style=proposed.speech.strip(),
                goals=[proposed.goal.strip()] if proposed.goal.strip() else [],
                secrets=[proposed.secret.strip()] if proposed.secret.strip() else [],
                relationships=relationships,  # type: ignore[arg-type]
            )
        )
        report.characters.append(ids[name])

    # --- the queue ---------------------------------------------------------
    for episode in concept.episodes:
        line = episode.line.strip()
        if line:
            project.add_episode(line)
            report.episodes += 1

    # --- the work's own page ------------------------------------------------
    if chronicle is not None:
        for section, value in (
            ("logline", concept.logline),
            ("premise", concept.premise),
            ("arc", concept.arc),
            ("ending", concept.ending),
        ):
            if value.strip():
                chronicle.record(
                    "story", STORY_SUBJECT_ID, section, value.strip(), source="author"
                )
                report.entries += 1

        for episode in concept.episodes:
            if episode.line.strip():
                chronicle.record(
                    "story", STORY_SUBJECT_ID, "episodes",
                    f"{episode.number}화 — {episode.line.strip()}",
                    source="author", section_kind="log",
                )
                report.entries += 1

        # How the concept came to be. Without this the arc arrives looking like
        # it was always obvious, and the author loses the reasoning they spent
        # an afternoon on.
        #
        # The conversation first, where there was one, because it came first:
        # for a concept worked out by talking, the reasoning *is* the
        # conversation, and the refinement turns that follow are footnotes to
        # it. Kept line by line rather than summarised — each line is then its
        # own chronicle entry the author can edit or retract, and a summary
        # would be the model's account of what they decided.
        for message in messages or []:
            text = getattr(message, "text", "").strip()
            if not text:
                continue
            speaker = "작가" if getattr(message, "role", "") == "author" else "AI"
            chronicle.record(
                "story", STORY_SUBJECT_ID, "decisions",
                f"[대화] {speaker}: {text}",
                source="author", section_kind="log",
            )
            report.entries += 1

        for turn in turns or []:
            if getattr(turn, "instruction", "").strip():
                chronicle.record(
                    "story", STORY_SUBJECT_ID, "decisions",
                    f"{turn.instruction.strip()} → " + ", ".join(turn.changed or ["(변화 없음)"]),
                    source="author", section_kind="log",
                )
                report.entries += 1

    logger.info(
        "Committed a concept: %d characters, %d rules, %d locations, %d episodes, "
        "%d chronicle entries",
        len(report.characters), len(report.rules), len(report.locations),
        report.episodes, report.entries,
    )
    return report


__all__ = ["CommitReport", "commit_concept"]
