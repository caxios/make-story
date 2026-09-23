"""The work's plan, for the stages that plan.

The Director is asked to take a one-line storyline and build it into a full
episode — `prompts/director.md` has a rule for exactly that. Doing it without
knowing where the work is going means the expansion can drift off the arc,
plausibly, one chapter at a time, and nothing about any single chapter looks
wrong.

So the planning stages get a short digest of the story document. **Only the
planning stages.** `context.format_world_summary` reaches five prompts; the arc
and the planned ending must not travel with it, because a character who has
read the ending stops being surprised by it and the Lore Checker would flag
every chapter for not having arrived there yet.

Short on purpose. The Director needs the direction, not the ending in detail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from storyweaver.wiki.fold import current_value
from storyweaver.wiki.sections import STORY_SUBJECT_ID

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore

# Enough to steer by, not enough to crowd out the episode being planned.
LOGLINE_CHARS = 200
ARC_CHARS = 700
ENDING_CHARS = 300

NOTHING = "(아직 정해진 전체 구상이 없습니다)"


def _trim(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def story_brief(store: ChronicleStore | None) -> str:
    """Where this work is going, as the planning stages are told it.

    Empty when the author has not written a plan, which is the ordinary case
    for a story that was not started from a concept session.
    """
    if store is None:
        return ""

    parts: list[str] = []
    for section, label, limit in (
        ("logline", "한 줄 요약", LOGLINE_CHARS),
        ("arc", "전체 아크", ARC_CHARS),
        ("ending", "계획된 결말", ENDING_CHARS),
    ):
        value = _trim(current_value(store, "story", STORY_SUBJECT_ID, section), limit)
        if value:
            parts.append(f"{label}: {value}")

    return "\n\n".join(parts)


__all__ = ["ARC_CHARS", "ENDING_CHARS", "LOGLINE_CHARS", "NOTHING", "story_brief"]
