"""Deciding what happens next: the outline for the episode after the queue.

The concept stage outlines the opening chapters. After that, adding an episode
used to mean the author writing its outline by hand — the one place in the
pipeline where the model, which has read the whole wiki and every chapter
summary, sat idle while the author did the remembering.

This drafts it. The author still sees and edits it before anything is queued;
nothing here writes to the project.

What the model is shown, and why:

- **the work's direction** (arc and ending, from the story page) — so the
  episode is a step toward somewhere rather than a step sideways;
- **the cast and world as the story has left them** — the folded project, so a
  character who lost an arm in episode 9 does not have it back in 13;
- **every episode in the queue**, written or planned — a planned episode will
  happen before this one, so it has to be built on too;
- **the closing passage** of the last chapter, when the last chapter is written
  — the most exact answer to "where are we";
- **what the story has done to each character, faction, place and rule** —
  each one's last forty appearances in full, older ones as a digest
  (`agents/history.py`), so a thread can be built on someone's history;
- **the open plot threads**, quietest first — the ones a reader will think were
  forgotten;
- **where the episode sits in the whole work** — its part, how much of the
  planned length is left, and which planned threads are due to be planted or
  paid off around here — so episode 13 of 400 is written as episode 13 of 400;
- **the author's direction**, if they gave one, which outranks all the rest.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, Field

from storyweaver import telemetry
from storyweaver.agents import context as ctx
from storyweaver.agents.concept import reply_text
from storyweaver.agents.prompts import render_prompt
from storyweaver.llm import MODEL_MAX_OUTPUT_TOKENS, get_llm
from storyweaver.memory.plot_tracker import PlotThread
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

# The most recent episodes are given in full; older ones are cut to a line, so
# a hundred-chapter serial does not cost a hundred summaries per draft.
RECENT_IN_FULL = 5
OLDER_LIMIT = 160

NO_BRIEF = "(작품의 전체 방향이 따로 적혀 있지 않습니다. 지금까지의 흐름에서 판단하세요.)"
NO_EPISODES = "(아직 아무 회차도 없습니다. 이것이 첫 회입니다.)"
NO_THREADS = "(기록된 떡밥이 없습니다.)"
NO_DIRECTION = "(따로 없습니다. 이야기에 가장 좋은 다음 회차를 정하세요.)"
NO_RECORD = "(아직 작품 속에서 기록된 일이 없습니다.)"
NO_POSITION = (
    "(전체 분량이 정해져 있지 않습니다. 연재 웹소설의 한 회차답게 한 걸음만 나아가고, "
    "결말을 앞당기지 마세요.)"
)


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def format_story_so_far(project: Project) -> str:
    """Every episode in the queue, oldest first, marked written or planned."""
    if not project.episodes:
        return NO_EPISODES
    lines = []
    cutoff = len(project.episodes) - RECENT_IN_FULL
    for index, episode in enumerate(project.episodes):
        written = episode.status == "completed" and episode.summary.strip()
        gist = (episode.summary if written else episode.author_storyline).strip()
        if not gist:
            continue
        if index < cutoff:
            gist = _cut(gist, OLDER_LIMIT)
        mark = "written" if written else "planned"
        lines.append(f"Episode {episode.episode_number} ({mark}): {gist}")
    return "\n\n".join(lines) or NO_EPISODES


def format_threads(threads: Sequence[PlotThread], upcoming: int) -> str:
    """Open threads, the ones that have waited longest first."""
    if not threads:
        return NO_THREADS
    ordered = sorted(threads, key=lambda t: t.last_referenced_episode)
    return "\n".join(
        f"- {thread.summary_line()} (untouched for "
        f"{thread.episodes_since_reference(upcoming)} episodes)"
        for thread in ordered
    )


def build_prompt(
    project: Project,
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    closing: str = "",
    direction: str = "",
    position: str = "",
    record: str = "",
) -> str:
    number = project.next_episode_number()
    return render_prompt(
        "next_episode",
        title=project.world.title or project.name,
        number=number,
        previous=number - 1,
        brief=brief.strip() or NO_BRIEF,
        cast=ctx.format_cast_for_planning(project.characters),
        world=ctx.format_world_for_planning(project.world),
        story_so_far=format_story_so_far(project),
        closing=closing.strip(),
        threads=format_threads(threads, number),
        direction=direction.strip() or NO_DIRECTION,
        position=position.strip() or NO_POSITION,
        record=record.strip() or NO_RECORD,
    )


def draft(
    project: Project,
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    closing: str = "",
    direction: str = "",
    position: str = "",
    record: str = "",
    llm=None,
) -> str:
    """The outline for the next episode. One model call; nothing is saved."""
    prompt = build_prompt(
        project, brief=brief, threads=threads, closing=closing, direction=direction,
        position=position, record=record,
    )
    model = telemetry.meter(llm or get_llm(stage="planner"), "planner")
    outline = reply_text(model.invoke(prompt))
    if not outline:
        raise ValueError("The planner returned an empty outline")
    return outline


# ---------------------------------------------------------------------------
# A stretch at once
# ---------------------------------------------------------------------------

# How many episodes one batch may plan. Twenty is a stretch the model can hold
# in its head as one run; beyond that the later outlines thin out.
MAX_BATCH = 20
NO_RANGE = (
    "(전체 분량이 정해져 있지 않습니다. 연재 웹소설의 호흡으로 조금씩 나아가고, "
    "결말을 앞당기지 마세요.)"
)


class DraftedEpisode(BaseModel):
    number: int = Field(description="회차 번호. 요청받은 번호 그대로")
    outline: str = Field(description="한 문단, 3-5문장: 누가 나오고, 무슨 일이, 무엇이 바뀌고, 어디서 끝나는지")


class DraftedBatch(BaseModel):
    episodes: list[DraftedEpisode]


def build_batch_prompt(
    project: Project,
    count: int,
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    closing: str = "",
    direction: str = "",
    range_text: str = "",
    record: str = "",
) -> str:
    start = project.next_episode_number()
    end = start + count - 1
    return render_prompt(
        "next_episodes",
        title=project.world.title or project.name,
        start=start,
        end=end,
        count=count,
        previous=start - 1,
        brief=brief.strip() or NO_BRIEF,
        range=range_text.strip() or NO_RANGE,
        cast=ctx.format_cast_for_planning(project.characters),
        world=ctx.format_world_for_planning(project.world),
        story_so_far=format_story_so_far(project),
        closing=closing.strip(),
        threads=format_threads(threads, start),
        direction=direction.strip() or NO_DIRECTION,
        record=record.strip() or NO_RECORD,
    )


def draft_batch(
    project: Project,
    count: int,
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    closing: str = "",
    direction: str = "",
    range_text: str = "",
    record: str = "",
    llm=None,
) -> list[tuple[int, str]]:
    """Outlines for the next `count` episodes, planned as one run.

    One call, so the stretch is planned together — episode 7 of the batch knows
    what episode 6 did. Returns `(episode_number, outline)` in order, for
    exactly the numbers asked for; nothing is saved.
    """
    if not 1 <= count <= MAX_BATCH:
        raise ValueError(f"a batch is 1 to {MAX_BATCH} episodes")

    prompt = build_batch_prompt(
        project, count, brief=brief, threads=threads, closing=closing,
        direction=direction, range_text=range_text, record=record,
    )
    # Twenty paragraphs is long, and a cut-off answer loses the last episodes
    # silently; planning is not held to the shared cap.
    model = telemetry.meter(
        llm or get_llm(stage="planner", max_output_tokens=MODEL_MAX_OUTPUT_TOKENS), "planner"
    )
    result: DraftedBatch = model.with_structured_output(DraftedBatch).invoke(prompt)

    start = project.next_episode_number()
    wanted = range(start, start + count)
    drawn = {e.number: e.outline.strip() for e in result.episodes if e.outline.strip()}
    outlines = [(n, drawn[n]) for n in wanted if n in drawn]
    if not outlines:
        raise ValueError("The planner returned no outlines")
    missing = [n for n in wanted if n not in drawn]
    if missing:
        logger.warning("The batch came back without episodes %s", missing)
    return outlines


# ---------------------------------------------------------------------------
# Revising chosen outlines
# ---------------------------------------------------------------------------

# Episodes one revision may touch: the same stretch the model can hold as one
# run when drafting.
MAX_REVISE = MAX_BATCH
# Episodes this close to one being revised are shown in full, so the revision
# follows on from them and hands over to them cleanly.
NEIGHBOURHOOD = 3
NO_REVISION_DIRECTION = (
    "(따로 없습니다. 앞뒤 회차와 작품 구조에 더 잘 맞고, 더 재미있게 다듬으세요.)"
)


def format_queue_for_revision(project: Project, targets: set[int]) -> str:
    """The whole queue, with the episodes to revise marked and shown whole."""
    if not project.episodes:
        return NO_EPISODES
    lines = []
    for episode in project.episodes:
        number = episode.episode_number
        written = episode.status == "completed" and episode.summary.strip()
        if number in targets:
            mark, gist = "TO REVISE — current outline", episode.author_storyline.strip()
        elif written:
            mark, gist = "written — what actually happened", episode.summary.strip()
        else:
            mark, gist = "planned — stays as it is", episode.author_storyline.strip()
        if not gist and number not in targets:
            continue
        if not any(abs(number - t) <= NEIGHBOURHOOD for t in targets):
            gist = _cut(gist, OLDER_LIMIT)
        lines.append(f"Episode {number} ({mark}): {gist or '(비어 있음)'}")
    return "\n\n".join(lines)


def build_revise_prompt(
    project: Project,
    targets: Sequence[int],
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    direction: str = "",
    range_text: str = "",
    record: str = "",
) -> str:
    chosen = sorted(set(targets))
    return render_prompt(
        "revise_outlines",
        title=project.world.title or project.name,
        numbers=", ".join(f"{n}화" for n in chosen),
        brief=brief.strip() or NO_BRIEF,
        range=range_text.strip() or NO_RANGE,
        cast=ctx.format_cast_for_planning(project.characters),
        world=ctx.format_world_for_planning(project.world),
        record=record.strip() or NO_RECORD,
        queue=format_queue_for_revision(project, set(chosen)),
        threads=format_threads(threads, chosen[0]),
        direction=direction.strip() or NO_REVISION_DIRECTION,
    )


def revise(
    project: Project,
    targets: Sequence[int],
    *,
    brief: str = "",
    threads: Sequence[PlotThread] = (),
    direction: str = "",
    range_text: str = "",
    record: str = "",
    llm=None,
) -> list[tuple[int, str]]:
    """New outlines for the chosen episodes only. One call; nothing is saved.

    Returns `(episode_number, outline)` for the chosen numbers the model
    answered, in order.
    """
    chosen = sorted(set(targets))
    if not 1 <= len(chosen) <= MAX_REVISE:
        raise ValueError(f"a revision is 1 to {MAX_REVISE} episodes")
    prompt = build_revise_prompt(
        project, chosen, brief=brief, threads=threads, direction=direction,
        range_text=range_text, record=record,
    )
    model = telemetry.meter(
        llm or get_llm(stage="planner", max_output_tokens=MODEL_MAX_OUTPUT_TOKENS), "planner"
    )
    result: DraftedBatch = model.with_structured_output(DraftedBatch).invoke(prompt)
    drawn = {e.number: e.outline.strip() for e in result.episodes if e.outline.strip()}
    revised = [(n, drawn[n]) for n in chosen if n in drawn]
    if not revised:
        raise ValueError("The planner returned no revised outlines")
    missing = [n for n in chosen if n not in drawn]
    if missing:
        logger.warning("The revision came back without episodes %s", missing)
    return revised
