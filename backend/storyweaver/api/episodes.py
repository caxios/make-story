"""The episode queue: outlines in, order, and batch import."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from storyweaver.models import Episode
from storyweaver.models.style import PACING
from storyweaver.api import deps
from storyweaver.ui.project import Project

router = APIRouter(prefix="/api/episodes", tags=["episodes"])

STATUSES = ("queued", "in_progress", "completed")


class NewEpisode(BaseModel):
    author_storyline: str = Field(min_length=1)
    title: str = ""
    pacing: str = "normal"


class EpisodeUpdate(BaseModel):
    """A partial edit. Omitted fields are left alone."""

    title: str | None = None
    author_storyline: str | None = None
    pacing: str | None = None
    status: str | None = None
    final_text: str | None = None
    # Editable: the author knows better than the summarizer what the next
    # episode needs to remember, and this is what gets injected into it.
    summary: str | None = None


class MoveRequest(BaseModel):
    offset: int = Field(description="-1 to move up the queue, +1 to move down")


class BatchRequest(BaseModel):
    text: str
    separator: str = "---"


def _check_pacing(pacing: str | None) -> None:
    if pacing is not None and pacing not in PACING:
        raise HTTPException(
            status_code=422, detail=f"Unknown pacing {pacing!r}; expected one of {list(PACING)}"
        )


def _check_status(status: str | None) -> None:
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Unknown status {status!r}; expected one of {list(STATUSES)}"
        )


@router.get("", response_model=list[Episode])
def list_episodes(project: Project = Depends(deps.get_project)) -> list[Episode]:
    return sorted(project.episodes, key=lambda e: e.episode_number)


@router.post("", response_model=Episode, status_code=201)
def add_episode(new: NewEpisode) -> Episode:
    """Queue an outline. The number follows on from the end of the queue."""
    _check_pacing(new.pacing)
    with deps.write_lock():
        project = deps.get_project()
        episode = project.add_episode(new.author_storyline.strip(), new.title.strip())
        episode = episode.model_copy(update={"pacing": new.pacing})
        project.update_episode(episode)
        deps.save_project(project)
    return episode


@router.post("/batch", response_model=list[Episode], status_code=201)
def add_episodes_batch(request: BatchRequest) -> list[Episode]:
    """Import several outlines at once from one blob, split on a separator line."""
    with deps.write_lock():
        project = deps.get_project()
        added = project.add_episodes_from_text(request.text, request.separator)
        if not added:
            raise HTTPException(status_code=422, detail="No outlines found in the text")
        deps.save_project(project)
    return added


@router.get("/{episode_number}", response_model=Episode)
def read_episode(episode_number: int, project: Project = Depends(deps.get_project)) -> Episode:
    return deps.require_episode(project, episode_number)


@router.put("/{episode_number}", response_model=Episode)
def update_episode(episode_number: int, update: EpisodeUpdate) -> Episode:
    _check_pacing(update.pacing)
    _check_status(update.status)
    with deps.write_lock():
        project = deps.get_project()
        episode = deps.require_episode(project, episode_number)
        changes = update.model_dump(exclude_unset=True, exclude_none=True)
        edited = episode.model_copy(update=changes)
        project.update_episode(edited)
        deps.save_project(project)
    return edited


@router.delete("/{episode_number}", response_model=list[Episode])
def delete_episode(episode_number: int) -> list[Episode]:
    """Delete an episode and close the gap: the queue renumbers itself.

    Any checkpoint for it goes too, or a later generation would resume into
    half-written scenes belonging to a chapter that no longer exists.
    """
    with deps.write_lock():
        project = deps.get_project()
        deps.require_episode(project, episode_number)
        project.remove_episode(episode_number)
        project.renumber_episodes()
        deps.save_project(project)
    deps.get_checkpoints().clear(episode_number)
    return project.episodes


@router.post("/{episode_number}/move", response_model=list[Episode])
def move_episode(episode_number: int, request: MoveRequest) -> list[Episode]:
    """Reorder the queue. Numbers follow position, so this reorders the story."""
    with deps.write_lock():
        project = deps.get_project()
        deps.require_episode(project, episode_number)
        project.move_episode(episode_number, request.offset)
        deps.save_project(project)
    return project.episodes


@router.post("/{episode_number}/summarize", response_model=Episode)
def summarize_episode(episode_number: int) -> Episode:
    """Re-read a finished chapter and rewrite its summary.

    Worth doing after editing the prose by hand: the summary is what the next
    episode is told about this one, so a stale summary quietly steers the whole
    serial. Re-running it also refreshes the memory stores.
    """
    project = deps.get_project()
    episode = deps.require_episode(project, episode_number)
    if not episode.final_text.strip():
        raise HTTPException(
            status_code=409,
            detail=f"Episode {episode_number} has not been written yet, so there is nothing to summarize",
        )

    memory = deps.require_memory()
    try:
        recorded = memory.summarize_and_record(
            episode,
            project.world,
            project.character_map(),
            language=project.style.language,
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise HTTPException(
            status_code=502, detail=f"The summarizer failed: {error}"
        ) from error

    with deps.write_lock():
        # Reloaded rather than reused: summarizing is a model call, and the
        # queue may have moved on while it ran.
        current = deps.get_project()
        latest = deps.require_episode(current, episode_number)
        updated = latest.model_copy(update={"summary": recorded.summary})
        current.update_episode(updated)
        deps.save_project(current)
    return updated
