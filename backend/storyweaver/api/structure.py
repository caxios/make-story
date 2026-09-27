"""The work's planned length and layout, after the concept is committed.

The concept stage draws a structure — parts and planned threads across a target
length — and commit puts it on the project. This is where the author reads it,
edits it, and redraws it: when they decide the story should run four hundred
episodes instead of two hundred, or when the story has moved and the plan
should follow.

Redrawing is two steps, like everything else that spends a model call on the
author's plan: `/draft` proposes a new layout and new outlines for the episodes
that are not written yet, and nothing changes until `/apply` is called with
whatever the author kept. Written chapters are never touched.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from storyweaver.agents import context as ctx
from storyweaver.agents import history
from storyweaver.agents import structure as layout
from storyweaver.api import deps
from storyweaver.models.structure import (
    MAX_TARGET,
    StoryStructure,
    describe_position,
    tidy_structure,
)
from storyweaver.ui.project import Project
from storyweaver.wiki import STORY_SUBJECT_ID, current_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/structure", tags=["structure"])

# Episodes the redraw may rewrite: in the queue, with nothing written yet. A
# chapter that is written, or half-written, is what happened — the plan
# follows it, not the other way round.
REWRITABLE = ("queued", "planned")


class StructureView(BaseModel):
    structure: StoryStructure | None = None
    # The episode the next outline would be for, and where it sits.
    next_episode: int
    written_through: int
    position: str = ""


class DraftRequest(BaseModel):
    target_episodes: int = Field(ge=1, le=MAX_TARGET)
    instruction: str = Field(default="", max_length=2000)
    # Also rewrite the outlines of episodes that are queued but not written.
    rewrite_upcoming: bool = True


class EpisodeRewrite(BaseModel):
    episode_number: int
    before: str
    after: str


class DraftResponse(BaseModel):
    structure: StoryStructure
    episodes: list[EpisodeRewrite] = Field(default_factory=list)


class EpisodeOutline(BaseModel):
    episode_number: int
    author_storyline: str = Field(min_length=1)


class ApplyRequest(BaseModel):
    structure: StoryStructure
    episodes: list[EpisodeOutline] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reading the story as it stands
# ---------------------------------------------------------------------------


def written_through(project: Project) -> int:
    """The last episode of the unbroken run of written chapters from 1."""
    last = 0
    for episode in sorted(project.episodes, key=lambda e: e.episode_number):
        if episode.status != "completed":
            break
        last = episode.episode_number
    return last


def _rewritable(project: Project) -> list:
    return [
        e for e in project.episodes
        if e.status in REWRITABLE and not e.final_text.strip()
    ]


def _describe_work(project: Project) -> str:
    """The work as the layout needs it, from the wiki as it stands now."""
    lines = [f"제목: {project.world.title}", f"장르/톤: {project.world.genre} / {project.world.tone}"]
    memory = deps.get_memory()
    if memory is not None:
        for section, label in (
            ("logline", "한 줄 요약"),
            ("premise", "기획 의도"),
            ("arc", "전체 아크"),
            ("ending", "계획된 결말"),
        ):
            value = current_value(memory.chronicle, "story", STORY_SUBJECT_ID, section)
            if value and str(value).strip():
                lines.append(f"{label}:\n{str(value).strip()}")
    if project.world.overview.strip():
        lines.append(f"세계관:\n{ctx.format_world_for_planning(project.world)}")
    if project.characters:
        lines.append(f"인물:\n{ctx.format_cast_for_planning(project.characters)}")
    return "\n\n".join(lines)


def _story_so_far(project: Project) -> str:
    lines = []
    for episode in project.episodes:
        if episode.status == "completed" and episode.summary.strip():
            lines.append(f"{episode.episode_number}화: {episode.summary.strip()}")
    memory = deps.get_memory()
    if memory is not None:
        threads = memory.get_active_plot_threads()
        if threads:
            lines.append("\n지금 열려 있는 떡밥:")
            lines.extend(f"- {t.summary_line()}" for t in threads)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=StructureView)
def read_structure() -> StructureView:
    project = deps.get_project()
    upcoming = project.next_episode_number()
    return StructureView(
        structure=project.structure,
        next_episode=upcoming,
        written_through=written_through(project),
        position=describe_position(project.structure, upcoming),
    )


@router.put("", response_model=StructureView)
def save_structure(structure: StoryStructure) -> StructureView:
    """The author's own edit: a part renamed, a range moved, a thread added."""
    with deps.write_lock():
        project = deps.get_project()
        project.structure = tidy_structure(structure)
        deps.save_project(project)
    return read_structure()


@router.delete("", response_model=StructureView)
def clear_structure() -> StructureView:
    """Go back to no planned length. Outlines are no longer paced by one."""
    with deps.write_lock():
        project = deps.get_project()
        project.structure = None
        deps.save_project(project)
    return read_structure()


@router.post("/draft", response_model=DraftResponse)
def draft_structure(body: DraftRequest) -> DraftResponse:
    """Propose a layout for `target_episodes`, and new outlines to fit it.

    Two model calls when there are unwritten episodes to re-outline, one when
    there are not. Nothing is saved.
    """
    project = deps.get_project()
    if not project.characters or not project.world.overview.strip():
        raise HTTPException(
            status_code=409, detail="세계관과 등장인물이 있어야 구조를 짤 수 있습니다"
        )
    through = written_through(project)
    if body.target_episodes <= through:
        raise HTTPException(
            status_code=422,
            detail=f"이미 {through}화까지 썼습니다. 전체 분량은 그보다 커야 합니다",
        )

    folded = deps.folded_project(project)
    work = _describe_work(folded)
    # What the story has done to each element so far: a layout that plants and
    # pays off threads across the rest of the book has to know what is already
    # set up, character by character.
    memory = deps.get_memory()
    record = history.with_heading(
        history.story_record(
            memory.chronicle if memory is not None else None,
            project,
            project.next_episode_number(),
        )
    )
    if record:
        work = f"{work}\n\n{record}"
    so_far = _story_so_far(project)

    try:
        structure = layout.lay_out(
            body.target_episodes, work,
            story_so_far=so_far, written_through=through,
            instruction=body.instruction, stage="planner",
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Laying out the structure failed")
        raise HTTPException(status_code=502, detail=f"구조를 짜지 못했습니다: {error}") from error

    rewrites: list[EpisodeRewrite] = []
    upcoming = _rewritable(project) if body.rewrite_upcoming else []
    if upcoming:
        current = {e.episode_number: e.author_storyline for e in upcoming}
        try:
            drawn = layout.rewrite_upcoming(
                structure, current,
                title=folded.world.title or folded.name, work=work, story_so_far=so_far,
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("Re-outlining the queue failed")
            raise HTTPException(
                status_code=502, detail=f"회차 개요를 다시 쓰지 못했습니다: {error}"
            ) from error
        rewrites = [
            EpisodeRewrite(episode_number=n, before=current[n], after=drawn[n])
            for n in sorted(current)
        ]

    return DraftResponse(structure=structure, episodes=rewrites)


@router.post("/apply", response_model=StructureView)
def apply_structure(body: ApplyRequest) -> StructureView:
    """Save a layout and the outlines the author kept. No model calls.

    Only unwritten episodes can be re-outlined here. An episode whose scene plan
    was drawn for its old outline goes back to the queue, the same as when the
    author edits an outline by hand — the plan was for a different chapter.
    """
    with deps.write_lock():
        project = deps.get_project()
        rewritable = {e.episode_number for e in _rewritable(project)}
        refused = [o.episode_number for o in body.episodes if o.episode_number not in rewritable]
        if refused:
            raise HTTPException(
                status_code=409,
                detail=f"이미 쓴 회차는 바꿀 수 없습니다: {', '.join(map(str, refused))}화",
            )

        project.structure = tidy_structure(body.structure)
        changed = []
        for outline in body.episodes:
            episode = project.get_episode(outline.episode_number)
            text = outline.author_storyline.strip()
            if episode is None or text == episode.author_storyline.strip():
                continue
            updates: dict = {"author_storyline": text}
            if episode.status == "planned":
                updates.update({"status": "queued", "scenes": []})
            project.update_episode(episode.model_copy(update=updates))
            changed.append((episode.episode_number, text))
        deps.save_project(project)

        memory = deps.get_memory()
        if memory is not None:
            for number, text in changed:
                memory.chronicle.record(
                    "story", STORY_SUBJECT_ID, "episodes",
                    f"{number}화 — {text} (전체 {project.structure.target_episodes}화 기준으로 다시 짬)",
                    source="author", section_kind="log",
                )

    logger.info(
        "Applied a %d-episode structure; re-outlined %d episodes",
        project.structure.target_episodes, len(changed),
    )
    return read_structure()
