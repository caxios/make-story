"""The work's plan, for the stages that plan.

The Director is asked to take a one-line storyline and build it into a full
episode — `prompts/director.md` has a rule for exactly that. Doing it without
knowing where the work is going means the expansion can drift off the arc,
plausibly, one chapter at a time, and nothing about any single chapter looks
wrong.

So the planning stages get the story document. **Only the planning stages.**
`context.format_world_summary` reaches five prompts; the arc and the planned
ending must not travel with it, because a character who has read the ending
stops being surprised by it and the Lore Checker would flag every chapter for
not having arrived there yet.

Given whole. It used to be cut to a few hundred characters, and for a serial
planned across hundreds of episodes the arc is long — the cut dropped exactly
the later parts a planning stage needs to steer toward.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from storyweaver.models.structure import describe_position
from storyweaver.wiki.fold import current_value
from storyweaver.wiki.sections import STORY_SUBJECT_ID

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore
    from storyweaver.models.structure import StoryStructure

NOTHING = "(아직 정해진 전체 구상이 없습니다)"


def story_brief(store: ChronicleStore | None) -> str:
    """Where this work is going, as the planning stages are told it.

    Empty when the author has not written a plan, which is the ordinary case
    for a story that was not started from a concept session.
    """
    if store is None:
        return ""

    parts: list[str] = []
    for section, label in (
        ("logline", "한 줄 요약"),
        # The story page's own, as last edited. The world overview was copied
        # from it once, at commit; an edit on the page afterwards reaches the
        # planners only through here.
        ("premise", "기획 의도"),
        ("arc", "전체 아크"),
        ("ending", "계획된 결말"),
    ):
        value = (current_value(store, "story", STORY_SUBJECT_ID, section) or "").strip()
        if value:
            parts.append(f"{label}: {value}")

    return "\n\n".join(parts)


def planning_brief(
    store: ChronicleStore | None,
    structure: StoryStructure | None,
    episode_number: int,
) -> str:
    """The work's direction, plus where one episode sits in the whole.

    Direction alone is what let a twelve-chapter outline reach the ending: it
    said where the story goes but not how far away that was. With a planned
    length, a stage that plans an episode is also told which part it is in,
    how much of the book is left, and which threads and relationship turns are
    due around it.
    """
    position = describe_position(structure, episode_number)
    return "\n\n".join(part for part in (story_brief(store), position) if part)


__all__ = ["NOTHING", "planning_brief", "story_brief"]
