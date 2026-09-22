"""The episode queue: outlines in, order, and batch import."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from storyweaver import telemetry
from storyweaver.agents import context as ctx
from storyweaver.agents import director
from storyweaver.llm import get_llm
from storyweaver.models import Episode, Scene, StoryBeat
from storyweaver.models.style import PACING, PROSE_DENSITIES
from storyweaver.api import deps
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/episodes", tags=["episodes"])

STATUSES = ("queued", "planned", "in_progress", "completed")


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
    # How this one chapter is written. `null` is not "unset" here — a PUT that
    # omits these leaves them alone, and `reset_expression` is how an override
    # is taken back off.
    creativity: float | None = Field(default=None, ge=0.0, le=1.0)
    prose_density: str | None = None
    tone_notes: str | None = None
    reset_expression: bool = False


class MoveRequest(BaseModel):
    offset: int = Field(description="-1 to move up the queue, +1 to move down")


class BatchRequest(BaseModel):
    text: str
    separator: str = "---"


# One line in, an outline out. Each summary costs a model call, so the list is
# capped: a paste of fifty lines would otherwise sit there spending quota.
OneLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PlanAllRequest(BaseModel):
    summaries: list[OneLine] = Field(
        min_length=1,
        max_length=20,
        description="One entry per episode, in order. Each is a one-line or short description.",
    )


class ExpandedEpisodeSummary(BaseModel):
    """One episode: the author's one line, and the outline drawn out of it."""

    episode_number: int
    title: str
    author_one_line: str
    author_storyline: str


class PlanAllResponse(BaseModel):
    episodes: list[ExpandedEpisodeSummary]


def _check_pacing(pacing: str | None) -> None:
    if pacing is not None and pacing not in PACING:
        raise HTTPException(
            status_code=422, detail=f"Unknown pacing {pacing!r}; expected one of {list(PACING)}"
        )


def _check_density(density: str | None) -> None:
    if density is not None and density not in PROSE_DENSITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prose density {density!r}; expected one of "
            f"{list(PROSE_DENSITIES)}",
        )


def _check_status(status: str | None) -> None:
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Unknown status {status!r}; expected one of {list(STATUSES)}"
        )


def _story_so_far(project: Project, limit: int = 6) -> str:
    """What the queue already contains, so a new outline follows on from it.

    Summaries are used where a chapter has one and the storyline otherwise —
    the storyline is what the author asked for, the summary is what was
    actually written, and after generation the second is the truer record.
    """
    lines = []
    for episode in project.episodes[-limit:]:
        gist = (episode.summary or episode.author_storyline).strip()
        if gist:
            lines.append(f"Episode {episode.episode_number}: {gist}")
    return "\n".join(lines)


def _expand_summary(
    summary: str,
    episode_number: int,
    project: Project,
    story_so_far: str,
    prior_summaries: list[str],
) -> str:
    """Draw one line out into an outline the Director can decompose.

    One model call. The result is prose-shaped planning text, not prose: it
    becomes the episode's `author_storyline`, which is what every later stage
    reads.
    """
    prior_text = ""
    if story_so_far:
        prior_text += f"\n\n--- EPISODES ALREADY IN THE QUEUE ---\n{story_so_far}"
    if prior_summaries:
        numbered = "\n".join(prior_summaries)
        prior_text += f"\n\n--- EARLIER EPISODES IN THIS SAME BATCH ---\n{numbered}"

    prompt = f"""You are a story planning assistant for the serial novel "{project.world.title}".
The author has given you a one-line summary for episode {episode_number}.

Expand it into a detailed episode outline (4-6 paragraphs) that:
1. Names the characters who appear in this episode
2. Describes the main conflict, event, or revelation
3. Describes the emotional arc - how the characters feel at the start and at the end
4. Suggests 2-3 key scenes with their location and mood
5. States the ending beat clearly - what the reader is left with

Do NOT write prose fiction; this is a planning document, not a chapter. Write
it in the language the author used, in clear and concise sentences.

Do not invent characters or contradict the world and the cast below. Where the
author's line is thin, develop it in the direction the story is already going
rather than introducing something new.

--- CAST ---
{ctx.format_character_summaries(project.characters)}

--- WORLD ---
{ctx.format_world_summary(project.world)}{prior_text}

--- THE AUTHOR'S ONE LINE FOR EPISODE {episode_number} ---
{summary}

Return only the outline text. No headers, no JSON, no markdown fences.
"""

    model = telemetry.meter(get_llm(stage="planner"), "planner")
    try:
        result = model.invoke(prompt)
    except Exception as error:  # noqa: BLE001 - reported to the author
        raise HTTPException(
            status_code=502, detail=f"The planner failed on episode {episode_number}: {error}"
        ) from error

    text = str(getattr(result, "content", result)).strip()
    if not text:
        raise HTTPException(
            status_code=502,
            detail=f"The planner returned nothing for episode {episode_number}.",
        )
    return text


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


@router.post("/plan-all", response_model=PlanAllResponse)
def plan_all_episodes(
    body: PlanAllRequest,
    project: Project = Depends(deps.get_project),
) -> PlanAllResponse:
    """Draw a list of one-liners out into outlines, for the author to approve.

    Nothing is saved and no prose is written: the browser shows these, the
    author edits them, and saving is the ordinary `POST /api/episodes` once per
    approved episode.

    The numbers are where these episodes would land if all of them were
    approved, so what the author reviews is numbered the way the queue will be.
    """
    if not project.characters:
        raise HTTPException(status_code=409, detail="This story has no characters yet")
    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="This story has no world yet")

    story_so_far = _story_so_far(project)
    first_number = project.next_episode_number()
    # Outlines are approved by the author and become the storyline every later
    # stage reads, so they are drawn from the cast and world as the story has
    # left them, not as they were first written down.
    project = deps.folded_project(project)

    results: list[ExpandedEpisodeSummary] = []
    prior_summaries: list[str] = []

    for offset, one_line in enumerate(body.summaries):
        episode_number = first_number + offset
        expanded = _expand_summary(
            summary=one_line,
            episode_number=episode_number,
            project=project,
            story_so_far=story_so_far,
            prior_summaries=prior_summaries,
        )
        results.append(
            ExpandedEpisodeSummary(
                episode_number=episode_number,
                # A placeholder the author renames; the Writer titles the
                # chapter itself once it is written.
                title=f"{episode_number}화",
                author_one_line=one_line,
                author_storyline=expanded,
            )
        )
        prior_summaries.append(f"Episode {episode_number}: {one_line}")

    return PlanAllResponse(episodes=results)


@router.get("/{episode_number}", response_model=Episode)
def read_episode(episode_number: int, project: Project = Depends(deps.get_project)) -> Episode:
    return deps.require_episode(project, episode_number)


@router.put("/{episode_number}", response_model=Episode)
def update_episode(episode_number: int, update: EpisodeUpdate) -> Episode:
    _check_pacing(update.pacing)
    _check_status(update.status)
    _check_density(update.prose_density)
    with deps.write_lock():
        project = deps.get_project()
        episode = deps.require_episode(project, episode_number)
        changes = update.model_dump(exclude_unset=True, exclude_none=True)
        if changes.pop("reset_expression", False):
            # Back to following the project's writing style.
            changes.update({"creativity": None, "prose_density": None, "tone_notes": ""})
        storyline = changes.get("author_storyline")
        if (
            storyline is not None
            and storyline.strip() != episode.author_storyline.strip()
            and episode.status == "planned"
        ):
            # The plan was drawn for a different storyline, so it is no longer
            # the author's plan for this one. Back to the start.
            changes.setdefault("status", "queued")
            changes.setdefault("scenes", [])
        edited = episode.model_copy(update=changes)
        project.update_episode(edited)
        deps.save_project(project)
    return edited


def _follow_renumbering(mapping: dict[int, int | None]) -> None:
    """Move the chronicle with the queue.

    Episode numbers are positions, not identities: deleting or moving a chapter
    renumbers every chapter after it. The chronicle stamps entries with that
    number, so without this an entry recorded in "3화" silently comes to name a
    different chapter — and this history is the thing the author audits.

    The entries' own order is untouched; only their labels move.
    """
    memory = deps.get_memory()
    if memory is None:
        return
    moved = memory.chronicle.renumber(mapping)
    if moved:
        logger.info("Renumbered %d chronicle entries to follow the queue", moved)


@router.delete("/{episode_number}", response_model=list[Episode])
def delete_episode(episode_number: int) -> list[Episode]:
    """Delete an episode and close the gap: the queue renumbers itself.

    Any checkpoint for it goes too, or a later generation would resume into
    half-written scenes belonging to a chapter that no longer exists.
    """
    with deps.write_lock():
        project = deps.get_project()
        deps.require_episode(project, episode_number)
        total = len(project.episodes)
        project.remove_episode(episode_number)
        project.renumber_episodes()
        deps.save_project(project)
        # Everything after the gap moves down one; the deleted chapter's own
        # entries go with it.
        mapping: dict[int, int | None] = {episode_number: None}
        mapping.update({n: n - 1 for n in range(episode_number + 1, total + 1)})
        _follow_renumbering(mapping)
    deps.get_checkpoints().clear(episode_number)
    return project.episodes


@router.post("/{episode_number}/move", response_model=list[Episode])
def move_episode(episode_number: int, request: MoveRequest) -> list[Episode]:
    """Reorder the queue. Numbers follow position, so this reorders the story."""
    with deps.write_lock():
        project = deps.get_project()
        deps.require_episode(project, episode_number)
        before = [e.episode_number for e in project.episodes]
        project.move_episode(episode_number, request.offset)
        deps.save_project(project)
        target = episode_number + request.offset
        # `move_episode` does nothing when the target is off either end, so the
        # chronicle must not move either.
        if target in before:
            _follow_renumbering({episode_number: target, target: episode_number})
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
    folded = deps.folded_project(project)
    try:
        recorded = memory.summarize_and_record(
            episode,
            folded.world,
            folded.character_map(),
            language=project.style.language,
            review=project.review_chronicle,
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


# ==========================================================================
# The plan
#
# Between an outline and a chapter sits a decision the author should make, not
# the model: how this episode is actually laid out. Drafting that costs one
# Director call — next to nothing — while writing it costs fifty. So the plan
# is made first, shown, and only written once it is approved.
# ==========================================================================


class PlannedScene(BaseModel):
    """One scene of a plan, as the author edits it."""

    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    participating_character_ids: list[str] = Field(min_length=1)
    location_id: str | None = None
    beats: list[StoryBeat] = Field(default_factory=list)


class PlanUpdate(BaseModel):
    scenes: list[PlannedScene] = Field(min_length=1)


def _plan_response(project: Project, episode: Episode) -> dict:
    """The plan, with the length budget that says whether it can hit its target."""
    style = project.style
    per_scene = style.target_word_count_per_scene
    count = len(episode.scenes)
    return {
        "episode_number": episode.episode_number,
        "status": episode.status,
        "scenes": [scene.model_dump() for scene in episode.scenes],
        "unit": "characters" if style.counts_characters() else "words",
        "target_per_scene": per_scene,
        "target_total": per_scene * count,
        # What a Korean web-novel 회차 is expected to run to, for comparison.
        "standard_low": 4500,
        "standard_high": 5500,
    }


@router.post("/{episode_number}/plan")
def draft_plan(episode_number: int) -> dict:
    """Have the Director lay the episode out, for the author to approve.

    One model call. Nothing is written, and nothing else in the project moves
    until the author says so.
    """
    project = deps.get_project()
    episode = deps.require_episode(project, episode_number)
    if not episode.author_storyline.strip():
        raise HTTPException(
            status_code=409, detail="This episode has no storyline to plan from"
        )
    if not project.characters:
        raise HTTPException(status_code=409, detail="This story has no characters yet")
    if episode.status == "in_progress":
        raise HTTPException(
            status_code=409, detail=f"Episode {episode_number} is being written right now"
        )

    memory = deps.get_memory()
    # The author approves this layout, so it has to be built on who these
    # people are now. A plan cast from the original sheet would put a
    # character back in a form the story has already moved them out of, and
    # the approval gate would become a source of drift instead of a guard.
    folded = deps.folded_project(project)

    memory_context = ""
    if memory is not None:
        memory_context = memory.build_director_context(folded.character_map(), episode)

    try:
        scenes = director.decompose_episode(
            episode,
            folded.world,
            folded.character_map(),
            memory_context=memory_context,
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise HTTPException(
            status_code=502, detail=f"The Director failed: {error}"
        ) from error

    if not scenes:
        raise HTTPException(
            status_code=502,
            detail="The Director produced no usable scenes. Try again, or name the "
            "characters in the outline the way they are spelled in the cast.",
        )

    with deps.write_lock():
        current = deps.get_project()
        latest = deps.require_episode(current, episode_number)
        planned = latest.model_copy(update={"scenes": scenes, "status": "planned"})
        current.update_episode(planned)
        deps.save_project(current)
    return _plan_response(current, planned)


@router.get("/{episode_number}/plan")
def read_plan(episode_number: int, project: Project = Depends(deps.get_project)) -> dict:
    return _plan_response(project, deps.require_episode(project, episode_number))


@router.put("/{episode_number}/plan")
def update_plan(episode_number: int, update: PlanUpdate) -> dict:
    """Replace the plan with the author's edit of it.

    Ids are checked here rather than at writing time: an unknown character id
    would be silently dropped deep inside a simulation, and the author would
    only find out from a scene that is missing someone.
    """
    project = deps.get_project()
    episode = deps.require_episode(project, episode_number)

    known_characters = set(project.character_map())
    known_locations = {location.id for location in project.world.locations}
    scenes = []
    for number, planned in enumerate(update.scenes, start=1):
        unknown = [
            cid for cid in planned.participating_character_ids if cid not in known_characters
        ]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Scene {number} names characters who are not in the cast: "
                + ", ".join(unknown),
            )
        if planned.location_id is not None and planned.location_id not in known_locations:
            raise HTTPException(
                status_code=422,
                detail=f"Scene {number} names a location that is not in the world: "
                f"{planned.location_id}",
            )
        scenes.append(
            Scene(
                scene_number=number,
                title=planned.title,
                objective=planned.objective,
                participating_character_ids=planned.participating_character_ids,
                location_id=planned.location_id,
                beats=planned.beats,
            )
        )

    with deps.write_lock():
        current = deps.get_project()
        latest = deps.require_episode(current, episode_number)
        edited = latest.model_copy(update={"scenes": scenes, "status": "planned"})
        current.update_episode(edited)
        deps.save_project(current)
    return _plan_response(current, edited)
