"""Keeping a direct edit from being swallowed by the chronicle.

The fold takes a section's value from the last entry in its chain, so once a
chapter has recorded a change to a field, writing that field on the model no
longer decides anything. An author editing 외모 in the Character Workshop would
see it saved, reload the page and see it there — and the next chapter would
still be written from the chronicle.

So an edit that touches a field with a history becomes the next entry in that
history, exactly as an edit made in the wiki would. Every surface writes to the
same place, which is what "the wiki and the database are one store" has to mean
in practice.

Fields with no chronicle are left alone: they are still the author's own, and
inventing a chain for them would fill the history with lines nobody asked for.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from storyweaver.models import CharacterProfile, Location, Rule, WorldLore
from storyweaver.models.chronicle import SubjectType
from storyweaver.wiki.fold import current_value
from storyweaver.wiki.sections import relationship_section_key, sections_for

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore

logger = logging.getLogger(__name__)

AUTHOR_REASON = "작가가 직접 수정"


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return "유효함" if value else "폐지됨"
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    return "" if value is None else str(value)


def _record_changed_fields(
    store: ChronicleStore,
    subject_type: SubjectType,
    subject_id: str,
    updated: object,
) -> int:
    """Append an author entry for every chronicled field that just moved."""
    written = 0
    for section in sections_for(subject_type):
        field = section.bound_field
        if field is None or section.kind == "log":
            continue
        existing = current_value(store, subject_type, subject_id, section.key)
        if existing is None:
            continue  # no history here; the model's own value still rules
        fresh = _as_text(getattr(updated, field, None))
        if fresh.strip() == existing.strip():
            continue
        store.record(
            subject_type, subject_id, section.key, fresh,
            source="author", reason=AUTHOR_REASON,
        )
        written += 1
    return written


def record_character_edit(store: ChronicleStore, character: CharacterProfile) -> int:
    """Fold an author's direct edit of a character back into the chronicle."""
    written = _record_changed_fields(store, "character", character.id, character)

    # Relationships are a chain per pair, so they are compared per pair.
    for relationship in character.relationships:
        key = relationship_section_key(relationship.target_character_id)
        existing = current_value(store, "character", character.id, key)
        if existing is None:
            continue
        described = relationship.type
        if relationship.description:
            described = f"{relationship.type} — {relationship.description}"
        if described.strip() == existing.strip():
            continue
        store.record(
            "character", character.id, key, described,
            source="author", reason=AUTHOR_REASON,
        )
        written += 1

    if written:
        logger.info("Recorded %d author edit(s) to %s in the chronicle", written, character.id)
    return written


def record_world_edit(store: ChronicleStore, world: WorldLore) -> int:
    """The same, for the world header. Rules and places have their own calls."""
    return _record_changed_fields(store, "world", "world", world)


def record_location_edit(store: ChronicleStore, location: Location) -> int:
    return _record_changed_fields(store, "location", location.id, location)


def record_rule_edit(store: ChronicleStore, rule: Rule) -> int:
    return _record_changed_fields(store, "rule", rule.id, rule)


def forget_subject(
    store: ChronicleStore,
    subject_type: SubjectType,
    subject_id: str,
    note: str = "",
    title: str = "",
) -> bool:
    """A subject is gone from the project. Decide what the wiki keeps of them.

    The author asked for concept-stage people to be changeable and deletable
    later, and a concept session mints a whole cast at once — several of whom
    will be cut before episode one. Those were never in the story, so keeping a
    page for each would bury the wiki in people the reader never met.

    But a character the story actually used is a different case. That they were
    written out is itself something that happened, and their episode records are
    the only account of what they did while they were here. Their page stays,
    marked, so an author auditing episode 14 can still find out who that was.

    Returns True when the page was kept (retired), False when it was dropped.
    """
    if store.episode_entries(subject_type, subject_id) == 0:
        store.drop_subject(subject_type, subject_id)
        return False

    subject = store.get_wiki_subject(subject_type, subject_id)
    # The page's title is normally looked up from the project, which no longer
    # has them — so it is pinned here, or the page would be headed by its id.
    store.save_wiki_subject(
        subject.model_copy(
            update={
                "retired": True,
                "retired_note": note.strip(),
                "title": subject.title or title.strip() or subject_id,
            }
        )
    )
    return True


__all__ = [
    "AUTHOR_REASON",
    "forget_subject",
    "record_character_edit",
    "record_location_edit",
    "record_rule_edit",
    "record_world_edit",
]
