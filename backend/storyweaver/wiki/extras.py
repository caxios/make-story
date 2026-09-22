"""Sections the author invented, rendered for a prompt.

A bound section stands for a typed field, so an agent can use it structurally
and the Lore Checker can name the one that was broken. A section the author
added — 능력, 과거사, 명대사 — has no field to stand for, so it reaches the
model the only way it can: as labelled prose.

It has to reach the model somehow. An author who bothered to write a section
about a character's ability did so because it bears on the story, and the
summarizer records into these sections for the same reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from storyweaver.models.chronicle import SubjectType
from storyweaver.wiki.fold import current_value

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore

HEADING = "## 그 밖의 설정"


def free_sections_text(
    store: ChronicleStore | None,
    subject_type: SubjectType,
    subject_id: str,
) -> str:
    """The author's own sections as a prompt block, or "" if there are none.

    Log sections are rendered oldest-first, because a 작중 행적 is a sequence
    and reading it out of order would tell the model the wrong story.
    """
    if store is None:
        return ""

    saved = store.get_wiki_subject(subject_type, subject_id)
    if not saved.free_sections:
        return ""

    blocks = []
    for spec in sorted(saved.free_sections, key=lambda s: (s.order, s.key)):
        if spec.kind == "log":
            lines = [
                e.value
                for e in store.chain(subject_type, subject_id, spec.key)
                if e.value.strip()
            ]
            body = "\n".join(f"- {line}" for line in lines)
        else:
            body = current_value(store, subject_type, subject_id, spec.key) or ""
        if body.strip():
            blocks.append(f"### {spec.title}\n{body.strip()}")

    if not blocks:
        return ""
    # The spacing belongs to the value, not to the template: a character with
    # no sections of their own must leave no gap where they would have been.
    return "\n\n" + HEADING + "\n" + "\n\n".join(blocks)


__all__ = ["HEADING", "free_sections_text"]
