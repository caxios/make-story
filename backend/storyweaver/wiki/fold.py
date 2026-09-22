"""Folding a chronicle down to what is true now.

The author's setting is where a character started, not a cage. A prickly
character may soften across chapters of being worn down by people who care
about him; a gate that worked may break and later be repaired. The chronicle
records every one of those steps, and folding is how the story is told what
the current step is.

The rule is simple and deliberately so: **the last live entry in a chain
wins.** A section with no chronicle keeps the model's own value, so a project
that has never recorded anything folds to exactly what it already was — the
whole feature is inert until it has something to say.

Nothing here writes. Folding produces a copy; the stored profile and the
chronicle are both left exactly as they were.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from storyweaver.models import (
    CharacterProfile,
    Location,
    Relationship,
    Rule,
    Trait,
    WorldLore,
)
from storyweaver.models.chronicle import SubjectType
from storyweaver.wiki.sections import (
    bound_field_for,
    relationship_target,
    sections_for,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for typing
    from storyweaver.memory.chronicle_store import ChronicleStore

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Fields whose stored value is a list of strings. The chronicle holds text, so
# these round-trip through a newline-separated block.
_LIST_FIELDS = {"values", "goals", "secrets", "exceptions", "notable_features"}
# Truthy words for a boolean field. `Rule.active` is the only one today, and it
# is recorded by the summarizer as "폐지됨" or "유효함" rather than as a flag.
_FALSE_WORDS = {"false", "no", "off", "폐지", "폐지됨", "무효", "무효화", "해제", "사라짐"}


def current_value(
    store: ChronicleStore,
    subject_type: SubjectType,
    subject_id: str,
    section_key: str,
) -> str | None:
    """The last thing the chronicle says about one section, or None if silent."""
    chain = store.chain(subject_type, subject_id, section_key)
    return chain[-1].value if chain else None


def _coerce(field_name: str, raw: str, existing: object) -> object:
    """Turn a chronicle's text back into the shape the field expects."""
    if field_name in _LIST_FIELDS:
        return [line.strip("-• ").strip() for line in raw.splitlines() if line.strip()]
    if isinstance(existing, bool):
        return raw.strip().lower() not in _FALSE_WORDS
    if isinstance(existing, int) and not isinstance(existing, bool):
        try:
            return int(raw.strip())
        except ValueError:
            logger.warning("Chronicle value %r is not a number for %s", raw[:40], field_name)
            return existing
    return raw


def _fold_simple(store: ChronicleStore, subject_type: SubjectType, subject_id: str, base: T) -> T:
    """Apply every bound section's current value onto a copy of `base`."""
    updates: dict[str, object] = {}
    for section in sections_for(subject_type):
        field = section.bound_field
        if field is None or section.kind == "log":
            continue
        value = current_value(store, subject_type, subject_id, section.key)
        if value is None:
            continue
        updates[field] = _coerce(field, value, getattr(base, field, None))
    return base.model_copy(update=updates) if updates else base


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


def _fold_traits(store: ChronicleStore, character_id: str, base: list[Trait]) -> list[Trait]:
    """The personality section holds prose, so a change becomes one trait.

    Traits carry an intensity the chronicle has no way to express, so an
    existing set is left alone and the chronicle's line is added alongside it.
    That keeps the author's own sliders while still letting the story say the
    character has changed.
    """
    value = current_value(store, "character", character_id, "personality")
    if value is None:
        return base
    kept = [t for t in base if t.name != value]
    return [*kept, Trait(name=value, intensity=0.8)]


def _fold_relationships(
    store: ChronicleStore, character_id: str, base: list[Relationship]
) -> list[Relationship]:
    """Replay every `relationship:<target>` chain over the stored list.

    One chain per pair is what makes "경계하는 상대 → 신뢰하는 동료" readable as
    a history rather than as a pile of list edits. Sentiment is not in the
    chain — the chronicle stores text — so an existing relationship keeps the
    number it had and only its wording moves.
    """
    by_target = {r.target_character_id: r for r in base}
    for section_key in store.section_keys("character", character_id):
        target = relationship_target(section_key)
        if target is None:
            continue
        value = current_value(store, "character", character_id, section_key)
        if value is None:
            continue
        described, _, note = value.partition(" — ")
        existing = by_target.get(target)
        by_target[target] = Relationship(
            target_character_id=target,
            type=described.strip() or (existing.type if existing else "관계"),
            sentiment=existing.sentiment if existing else 0.0,
            description=note.strip() or (existing.description if existing else None),
        )
    return list(by_target.values())


def fold_character(store: ChronicleStore, base: CharacterProfile) -> CharacterProfile:
    """`base`, brought up to what the story has done to them since."""
    folded = _fold_simple(store, "character", base.id, base)
    return folded.model_copy(
        update={
            "traits": _fold_traits(store, base.id, base.traits),
            "relationships": _fold_relationships(store, base.id, base.relationships),
        }
    )


def fold_cast(
    store: ChronicleStore, cast: dict[str, CharacterProfile]
) -> dict[str, CharacterProfile]:
    return {cid: fold_character(store, character) for cid, character in cast.items()}


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------


def fold_location(store: ChronicleStore, base: Location) -> Location:
    return _fold_simple(store, "location", base.id, base)


def fold_rule(store: ChronicleStore, base: Rule) -> Rule:
    return _fold_simple(store, "rule", base.id, base)


def fold_world(store: ChronicleStore, base: WorldLore) -> WorldLore:
    """The world, its rules and its places, all brought up to date.

    A rule the story abolished is dropped rather than folded in: the Lore
    Checker enforces every rule it is handed, and enforcing a repealed law is
    how a continuity gate starts fighting the story it is meant to protect.
    Its history stays in the chronicle, which is where "it used to hold" lives.
    """
    folded = _fold_simple(store, "world", "world", base)
    rules = [fold_rule(store, rule) for rule in base.rules]
    return folded.model_copy(
        update={
            "rules": [rule for rule in rules if rule.active],
            "locations": [fold_location(store, place) for place in base.locations],
        }
    )


__all__ = [
    "current_value",
    "fold_cast",
    "fold_character",
    "fold_location",
    "fold_rule",
    "fold_world",
]
