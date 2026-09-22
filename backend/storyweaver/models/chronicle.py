"""The chronicle: how every setting in the story got to be the way it is.

A serial's settings are not constants. A character who begins prickly softens
over twenty episodes of being worn down by people who care about him; a gate
that worked is attacked, breaks, and is later repaired. Storing only the
current value throws away the part an author needs most when auditing a
finished arc — what changed, when, and why.

So nothing here is ever overwritten. Each `(subject, section)` pair owns an
append-only chain of entries, and the current value is simply the last one. The
author's own writing is the first entry rather than a separate "base" record,
which is what lets an author edit, an episode record, and a correction all live
on one timeline without anything having to be reconciled.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Everything the wiki can hold a page for.
SubjectType = Literal["character", "world", "location", "rule", "faction"]

# Who wrote the entry. Author entries carry no episode number: they happen at
# the point in the story the author is standing at, not inside a chapter.
EntrySource = Literal["author", "episode"]

EntryKind = Literal[
    "initial",    # the first thing the author said about this
    "changed",    # it became something else
    "added",      # it did not exist before and now does
    "revealed",   # it was always so; the story has only now told the reader
    "removed",    # it is gone — a ruin destroyed, a rule abolished
    "restored",   # it is back — the broken gate, repaired
]

# `revealed` versus `changed` matters more than it looks. "시월은 사실
# 300살이었다" is a reveal to the reader; "머리카락이 잘렸다" is a change in the
# world. A chronicle that conflates the two cannot produce an honest timeline.

SectionKind = Literal[
    "stateful",  # has a current value, reached through a history
    "log",       # has no current value; the entries are the content (작중 행적)
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChronicleEntry(BaseModel):
    """One step in the history of one section of one subject."""

    entry_id: str
    subject_type: SubjectType
    subject_id: str
    section_key: str

    source: EntrySource
    # Set when `source == "episode"`. Kept for display and grouping only —
    # never for ordering, because the queue renumbers itself (see `sequence`).
    episode_number: int | None = None
    # The real ordering key: a store-wide counter assigned when the entry is
    # appended. Episode numbers cannot order a chain, because deleting or
    # moving an episode renumbers the whole queue. Timestamps cannot either,
    # because an author may correct episode 3's record after episode 7 exists,
    # and that correction belongs where the author put it.
    sequence: int = 0

    kind: EntryKind
    value: str = ""
    # The value before this entry, copied at write time. Denormalised on
    # purpose: the wiki renders "c → b" without walking the chain, and the
    # chain is the one thing that must never be rewritten to make a view work.
    previous: str = ""
    # Why it changed. Required of episode entries and enforced at the API
    # boundary: a change the summarizer cannot ground in something that
    # happened in the chapter is a guess, and a guess that folds into the next
    # chapter's prompt deforms the character for good.
    reason: str = ""

    created_at: datetime = Field(default_factory=_now)
    # Retracted rather than deleted, so that a mistaken retraction is
    # recoverable and the audit trail the author asked for stays whole.
    superseded: bool = False
    # Recorded but not yet accepted by the author. A pending entry is visible
    # on its page and excluded from everything else — above all from the fold,
    # because the chronicle overrides the author's own setting and an invented
    # change that reached a prompt unreviewed would deform the character for
    # every chapter after it.
    pending: bool = False

    def is_live(self) -> bool:
        """Whether this entry counts: accepted, and not taken back."""
        return not self.superseded and not self.pending

    def describe(self) -> str:
        """One line, the way the wiki shows it."""
        where = f"{self.episode_number}화" if self.episode_number is not None else "작가"
        arrow = f"{self.previous} → {self.value}" if self.previous else self.value
        return f"[{where}] {arrow}" + (f"  ({self.reason})" if self.reason else "")


class SectionSpec(BaseModel):
    """What a section is.

    Bound sections mirror a field on a typed model, so an agent can use them
    structurally and the Lore Checker can name the one that was broken. Free
    sections are the author's own — 능력, 과거사, 명대사 — and reach the model
    as labelled prose instead.
    """

    key: str
    title: str                      # Korean; this is what the wiki shows
    kind: SectionKind = "stateful"
    # Attribute name on the typed model, or None for a free section.
    bound_field: str | None = None
    order: int = 0
    # Free sections are author-made; bound ones come from the registry.
    author_made: bool = False

    @property
    def is_bound(self) -> bool:
        return self.bound_field is not None


class WikiSubject(BaseModel):
    """A page: the parts of it that are not derived from a typed model."""

    subject_type: SubjectType
    subject_id: str
    title: str = ""
    summary: str = ""               # the 개요 paragraph at the top of the page
    free_sections: list[SectionSpec] = Field(default_factory=list)

    def section(self, key: str) -> SectionSpec | None:
        return next((s for s in self.free_sections if s.key == key), None)


__all__ = [
    "ChronicleEntry",
    "EntryKind",
    "EntrySource",
    "SectionKind",
    "SectionSpec",
    "SubjectType",
    "WikiSubject",
]
