"""The episode queue: outlines in, order, and batch import."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from storyweaver import telemetry
from storyweaver.agents import context as ctx
from storyweaver.agents import director
from storyweaver.agents import history
from storyweaver.agents import next_episode
from storyweaver.agents.flow import episode_flow
from storyweaver.agents.concept import reply_text
from storyweaver.agents.settings_extract import (
    ExtractedSettings,
    NewCharacter,
    NewPlace,
    plan_text,
)
from storyweaver.llm import get_llm
from storyweaver.models import Episode, Scene, StoryBeat
from storyweaver.models.style import PACING, PROSE_DENSITIES
from storyweaver.api import deps, registration
from storyweaver.ui.project import Project
from storyweaver.models.structure import describe_position, describe_range
from storyweaver.wiki import STORY_SUBJECT_ID, story_brief
from storyweaver.wiki.brief import planning_brief

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
    brief: str = "",
    record: str = "",
) -> str:
    """Draw one line out into an outline the Director can decompose.

    One model call. The result is prose-shaped planning text, not prose: it
    becomes the episode's `author_storyline`, which is what every later stage
    reads.
    """
    # The work's direction, from the story page. Passed in all along but never
    # put in the prompt, so the "aim this episode at it" instruction below was
    # pointing at nothing.
    direction_text = f"\n\n--- WHERE THE WORK IS HEADED ---\n{brief}" if brief.strip() else ""
    prior_text = ""
    if record.strip():
        prior_text += f"\n\n--- WHAT HAS HAPPENED TO EACH OF THEM ---\n{record}"
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

Do not contradict the world and the cast below. Where the author's line is
thin, develop it in the direction the story is already going; you may bring in
a new character, place or detail when it makes the episode better — name it
and say who or what it is, since it will be registered in the work's
settings. Where the work's overall direction is
given below, aim this episode at it — do not have anyone act on knowledge of
the ending, and do not bring it forward.

--- CAST ---
{ctx.format_cast_for_planning(project.characters)}

--- WORLD ---
{ctx.format_world_for_planning(project.world)}{direction_text}{prior_text}

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

    # Gemini answers in content blocks; `str()` on those put the raw block list,
    # signature and all, into the author's outline.
    text = reply_text(result)
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


class ManyOutline(BaseModel):
    author_storyline: str = Field(min_length=1)
    title: str = ""


class AddManyRequest(BaseModel):
    episodes: list[ManyOutline] = Field(min_length=1, max_length=next_episode.MAX_BATCH * 5)


@router.post("/many", response_model=list[Episode], status_code=201)
def add_many_episodes(body: AddManyRequest) -> list[Episode]:
    """Queue several outlines at once, in order, at the end of the queue.

    What a drafted batch is saved with once the author has read it. The episodes
    are numbered where they land, which is where the batch was drafted for.
    """
    with deps.write_lock():
        project = deps.get_project()
        added = [
            project.add_episode(outline.author_storyline.strip(), outline.title.strip())
            for outline in body.episodes
        ]
        deps.save_project(project)

    memory = deps.get_memory()
    if memory is not None:
        # The work's own page keeps the queue's history, as it does for the
        # outline the concept stage drew.
        for episode in added:
            memory.chronicle.record(
                "story", STORY_SUBJECT_ID, "episodes",
                f"{episode.episode_number}화 — {episode.author_storyline}",
                source="author", section_kind="log",
            )
    return added


class ExtractSettingsRequest(BaseModel):
    episode_numbers: list[int] = Field(min_length=1, max_length=next_episode.MAX_BATCH * 5)


class ExtractSettingsResponse(BaseModel):
    registered: list[str] = Field(default_factory=list)


@router.post("/extract-settings", response_model=ExtractSettingsResponse)
def extract_settings(body: ExtractSettingsRequest) -> ExtractSettingsResponse:
    """Register what these episodes' outlines bring in that the work lacks.

    Called by the studio after outlines are saved — added, edited, imported.
    New characters go to the workshop, places and rules to the world builder,
    factions and world facts to the wiki, a change of direction to the work's
    page and 작품기획. Outlines already read are skipped, so this costs one
    model call at most, and none when nothing changed.
    """
    project = deps.get_project()
    texts = []
    for number in sorted(set(body.episode_numbers)):
        episode = project.get_episode(number)
        if episode is not None and episode.author_storyline.strip():
            texts.append((number, "개요", episode.author_storyline))
    try:
        registered = registration.register_from(texts)
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Reading outlines for settings failed")
        raise HTTPException(
            status_code=502, detail=f"개요에서 새 설정을 읽지 못했습니다: {error}"
        ) from error
    return ExtractSettingsResponse(registered=registered)


class ReviseRequest(BaseModel):
    episode_numbers: list[int] = Field(min_length=1, max_length=next_episode.MAX_REVISE)
    direction: str = Field(default="", max_length=2000)


class RevisedOutline(BaseModel):
    episode_number: int
    before: str
    after: str


class ReviseResponse(BaseModel):
    episodes: list[RevisedOutline]


@router.post("/revise-outlines", response_model=ReviseResponse)
def revise_outlines(
    body: ReviseRequest,
    project: Project = Depends(deps.get_project),
) -> ReviseResponse:
    """Rewrite the outlines of the episodes the author chose, and only those.

    One model call, shown the whole queue with the chosen ones marked, so each
    revision fits between episodes that are not changing. Nothing is saved:
    the author compares, edits and keeps what they want (`PUT /{n}` each).
    A written chapter cannot be re-outlined here — its outline is history.
    """
    chosen = sorted(set(body.episode_numbers))
    missing = [n for n in chosen if project.get_episode(n) is None]
    if missing:
        raise HTTPException(
            status_code=404, detail="없는 회차입니다: " + ", ".join(f"{n}화" for n in missing)
        )
    locked = [
        n for n in chosen
        if project.get_episode(n).status in ("completed", "in_progress")
    ]
    if locked:
        raise HTTPException(
            status_code=409,
            detail="이미 썼거나 쓰는 중인 회차는 개요를 고칠 수 없습니다: "
            + ", ".join(f"{n}화" for n in locked),
        )

    memory = deps.get_memory()
    folded = deps.folded_project(project)
    try:
        revised = next_episode.revise(
            folded,
            chosen,
            brief=story_brief(memory.chronicle) if memory is not None else "",
            threads=memory.get_active_plot_threads() if memory is not None else [],
            direction=body.direction,
            range_text=describe_range(project.structure, chosen[0], chosen[-1]),
            record=_record(project, chosen[0]),
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Revising outlines %s failed", chosen)
        raise HTTPException(
            status_code=502, detail=f"개요를 고치지 못했습니다: {error}"
        ) from error

    return ReviseResponse(
        episodes=[
            RevisedOutline(
                episode_number=number,
                before=project.get_episode(number).author_storyline,
                after=outline,
            )
            for number, outline in revised
        ]
    )


class DraftBatchRequest(BaseModel):
    count: int = Field(default=next_episode.MAX_BATCH, ge=1, le=next_episode.MAX_BATCH)
    direction: str = Field(default="", max_length=2000)


class DraftedOutline(BaseModel):
    episode_number: int
    author_storyline: str


class DraftBatchResponse(BaseModel):
    episodes: list[DraftedOutline]


@router.post("/draft-batch", response_model=DraftBatchResponse)
def draft_episode_batch(
    body: DraftBatchRequest,
    project: Project = Depends(deps.get_project),
) -> DraftBatchResponse:
    """Plan the next `count` episodes (twenty by default) in one go.

    One model call, so the stretch is planned as a run rather than twenty
    separate guesses. It is shown where the stretch sits in the planned length —
    the parts it crosses, the threads and relationship turns that fall inside
    it — along with everything the single-episode draft is shown. Nothing is
    saved; the author reads, edits and keeps what they want (`POST /many`).
    """
    if not project.characters:
        raise HTTPException(status_code=409, detail="등장인물이 아직 없습니다")
    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="세계관이 아직 없습니다")

    memory = deps.get_memory()
    start = project.next_episode_number()
    end = start + body.count - 1
    folded = deps.folded_project(project)

    try:
        drafted = next_episode.draft_batch(
            folded,
            body.count,
            brief=story_brief(memory.chronicle) if memory is not None else "",
            threads=memory.get_active_plot_threads() if memory is not None else [],
            closing=_closing_of_last(project, memory),
            direction=body.direction,
            range_text=describe_range(project.structure, start, end),
            record=_record(project, start),
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Drafting episodes %d-%d failed", start, end)
        raise HTTPException(
            status_code=502, detail=f"{start}~{end}화 개요를 쓰지 못했습니다: {error}"
        ) from error

    return DraftBatchResponse(
        episodes=[
            DraftedOutline(episode_number=number, author_storyline=outline)
            for number, outline in drafted
        ]
    )


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
    memory = deps.get_memory()
    brief = story_brief(memory.chronicle) if memory is not None else ""
    # Outlines are approved by the author and become the storyline every later
    # stage reads, so they are drawn from the cast and world as the story has
    # left them, not as they were first written down.
    record = _record(project, first_number)
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
            record=record,
            brief=planning_brief(
                memory.chronicle if memory is not None else None, project.structure, episode_number
            ),
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


class DraftNextRequest(BaseModel):
    direction: str = Field(
        default="",
        max_length=2000,
        description="What the author wants from this episode, if anything. Optional.",
    )


class DraftNextResponse(BaseModel):
    episode_number: int
    author_storyline: str


@router.post("/draft-next", response_model=DraftNextResponse)
def draft_next_episode(
    body: DraftNextRequest,
    project: Project = Depends(deps.get_project),
) -> DraftNextResponse:
    """Write the outline for the episode after the last one in the queue.

    One model call, and nothing is saved: the author reads it, changes what
    they want, and adds it the ordinary way. It is drawn from the wiki as the
    story has left it, every episode in the queue, the open threads, the work's
    direction and whatever the author asked for — see `agents/next_episode.py`.
    """
    if not project.characters:
        raise HTTPException(status_code=409, detail="등장인물이 아직 없습니다")
    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="세계관이 아직 없습니다")

    memory = deps.get_memory()
    brief = story_brief(memory.chronicle) if memory is not None else ""
    threads = memory.get_active_plot_threads() if memory is not None else []
    closing = _closing_of_last(project, memory)
    folded = deps.folded_project(project)

    try:
        outline = next_episode.draft(
            folded, brief=brief, threads=threads, closing=closing, direction=body.direction,
            position=describe_position(project.structure, project.next_episode_number()),
            record=_record(project, project.next_episode_number()),
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Drafting the next episode failed")
        raise HTTPException(
            status_code=502, detail=f"다음 회차 개요를 쓰지 못했습니다: {error}"
        ) from error

    return DraftNextResponse(
        episode_number=project.next_episode_number(), author_storyline=outline
    )


class DraftInsertRequest(BaseModel):
    at: int = Field(ge=1, description="The number the new episode will have.")
    direction: str = Field(default="", max_length=2000)


class DraftInsertResponse(BaseModel):
    at: int
    author_storyline: str


def _check_insert_point(project: Project, at: int) -> None:
    last = len(project.episodes) + 1
    if not 1 <= at <= last:
        raise HTTPException(
            status_code=422, detail=f"회차는 1화부터 {last}화 자리까지 넣을 수 있습니다"
        )


@router.post("/draft-insert", response_model=DraftInsertResponse)
def draft_insert(
    body: DraftInsertRequest,
    project: Project = Depends(deps.get_project),
) -> DraftInsertResponse:
    """Write the outline for a new episode that goes in as episode `at`.

    It sits between the episodes now numbered `at - 1` and `at`, and is drawn
    from both — it starts where the one before leaves off and ends where the
    one after can begin — along with the whole queue, the wiki, the record,
    the threads and where it sits in the work. One model call; nothing is
    saved (`POST /insert` does that).
    """
    _check_insert_point(project, body.at)
    if not project.characters:
        raise HTTPException(status_code=409, detail="등장인물이 아직 없습니다")
    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="세계관이 아직 없습니다")

    memory = deps.get_memory()
    folded = deps.folded_project(project)
    try:
        outline = next_episode.draft_between(
            folded,
            body.at,
            brief=story_brief(memory.chronicle) if memory is not None else "",
            threads=memory.get_active_plot_threads() if memory is not None else [],
            direction=body.direction,
            position=describe_position(project.structure, body.at),
            record=_record(project, body.at),
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        logger.exception("Drafting an episode to insert at %d failed", body.at)
        raise HTTPException(
            status_code=502, detail=f"{body.at}화에 넣을 개요를 쓰지 못했습니다: {error}"
        ) from error
    return DraftInsertResponse(at=body.at, author_storyline=outline)


class InsertRequest(NewEpisode):
    at: int = Field(ge=1, description="The number the new episode will have.")


@router.post("/insert", response_model=list[Episode], status_code=201)
def insert_episode(body: InsertRequest) -> list[Episode]:
    """Put a new episode in as episode `at`; everything from `at` on moves down one.

    The chronicle and any half-written checkpoints move with their chapters,
    as they do when episodes are moved or deleted. Refused while a chapter that
    would be renumbered is being written.
    """
    from storyweaver.api.generation import running_generations

    _check_pacing(body.pacing)
    busy = [n for n in running_generations() if n >= body.at]
    if busy:
        raise HTTPException(
            status_code=409,
            detail="집필 중인 회차의 번호가 바뀌게 되어 지금은 넣을 수 없습니다: "
            + ", ".join(f"{n}화" for n in busy),
        )

    with deps.write_lock():
        project = deps.get_project()
        _check_insert_point(project, body.at)
        total = len(project.episodes)
        project.episodes.sort(key=lambda e: e.episode_number)
        project.episodes.insert(
            body.at - 1,
            Episode(
                episode_number=body.at,
                title=body.title.strip(),
                author_storyline=body.author_storyline.strip(),
                pacing=body.pacing,
            ),
        )
        project.renumber_episodes()
        deps.save_project(project)
        _follow_renumbering({n: n + 1 for n in range(body.at, total + 1)})
        _shift_checkpoints(body.at, total)
    return project.episodes


def _shift_checkpoints(start: int, last: int) -> None:
    """Move half-written chapters' checkpoints down one, from `start` on.

    A checkpoint only resumes the episode whose number it carries, so left
    where it was it would be offered to whichever chapter took that number.
    """
    checkpoints = deps.get_checkpoints()
    for number in range(last, start - 1, -1):  # from the end, so none is overwritten
        checkpoint = checkpoints.load(number)
        if checkpoint is None:
            continue
        checkpoints.save(checkpoint.model_copy(update={"episode_number": number + 1}))
        checkpoints.clear(number)


def _record(project: Project, before: int) -> str:
    """What the story has done to each element before episode `before`.

    Drawn from the stored project rather than the folded one: the fold is the
    current setting, and this is the history that led to it.
    """
    memory = deps.get_memory()
    return history.story_record(memory.chronicle if memory is not None else None, project, before)


def _closing_of_last(project: Project, memory) -> str:
    """The last written passage — but only if it is the end of the queue.

    When chapters are planned past the last written one, that passage is not
    where the next episode starts from, and showing it would pull the draft
    back to the wrong moment.
    """
    if memory is None or not project.episodes:
        return ""
    closing = memory.structured_store.get_episode_closing()
    if closing is None:
        return ""
    number, passage = closing
    if number != project.episodes[-1].episode_number:
        return ""
    return f"## Where episode {number} ended — its last lines\n\n{passage}"


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


class DeleteManyRequest(BaseModel):
    episode_numbers: list[int] = Field(min_length=1)


@router.post("/delete-many", response_model=list[Episode])
def delete_episodes(body: DeleteManyRequest) -> list[Episode]:
    """Delete several episodes at once, and renumber the queue once.

    Deleting them one call at a time would renumber after each, so the numbers
    the author ticked would point at different chapters by the second call.
    Here every survivor's old number maps straight to its new one, and the
    chronicle follows that single mapping.

    Refused if any of them is being written right now.
    """
    from storyweaver.api.generation import running_generations

    doomed = set(body.episode_numbers)
    busy = doomed & set(running_generations())
    if busy:
        raise HTTPException(
            status_code=409,
            detail=f"지금 집필 중인 회차는 지울 수 없습니다: {', '.join(map(str, sorted(busy)))}화",
        )

    with deps.write_lock():
        project = deps.get_project()
        existing = {e.episode_number for e in project.episodes}
        missing = sorted(doomed - existing)
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"없는 회차입니다: {', '.join(map(str, missing))}화",
            )

        survivors = [e.episode_number for e in project.episodes if e.episode_number not in doomed]
        mapping: dict[int, int | None] = {n: None for n in doomed}
        mapping.update(
            {old: new for new, old in enumerate(survivors, start=1) if old != new}
        )
        project.episodes = [e for e in project.episodes if e.episode_number not in doomed]
        project.renumber_episodes()
        deps.save_project(project)
        _follow_renumbering(mapping)

    checkpoints = deps.get_checkpoints()
    for number in doomed:
        checkpoints.clear(number)
    logger.info("Deleted episodes %s", sorted(doomed))
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
    # Where the whole work is going, and where this episode sits in it. Rule 2
    # has the Director build a sparse storyline into a full episode, and doing
    # that blind to the arc drifts off it one chapter at a time.
    brief = planning_brief(
        memory.chronicle if memory is not None else None,
        project.structure,
        episode.episode_number,
    )
    # And what the story has done to each of the people and places in it, so
    # the plan builds on their history rather than only on their sheet.
    record = history.with_heading(_record(project, episode.episode_number))
    brief = "\n\n".join(part for part in (brief, record) if part)

    try:
        drawn = director.plan_episode(
            episode,
            folded.world,
            folded.character_map(),
            memory_context=memory_context,
            story_brief=brief,
            # The episodes before and after, so this one does not stage what
            # the next is planned for.
            story_flow=episode_flow(project.episodes, episode.episode_number),
        )
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise HTTPException(
            status_code=502, detail=f"The Director failed: {error}"
        ) from error

    if not drawn.scenes:
        raise HTTPException(
            status_code=502,
            detail="The Director produced no usable scenes. Try again, or name the "
            "characters in the outline the way they are spelled in the cast.",
        )

    # Anyone and anywhere new the Director brought in joins the work before
    # the plan that uses them is saved.
    registered: list[str] = []
    scenes = drawn.scenes
    if drawn.new_characters or drawn.new_locations:
        done = registration.register_found(
            ExtractedSettings(
                new_characters=[
                    NewCharacter(**n.model_dump(exclude={"id"})) for n in drawn.new_characters
                ],
                new_locations=[
                    NewPlace(**p.model_dump(exclude={"id"})) for p in drawn.new_locations
                ],
            ),
            f"{episode_number}화 기획서",
            preset_character_ids={n.name.strip(): n.id for n in drawn.new_characters},
            preset_location_ids={p.name.strip(): p.id for p in drawn.new_locations},
        )
        registered += done.lines
        scenes = _renamed(
            scenes,
            {n.id: done.character_ids.get(n.name.strip(), n.id) for n in drawn.new_characters},
            {p.id: done.location_ids.get(p.name.strip(), p.id) for p in drawn.new_locations},
        )

    with deps.write_lock():
        current = deps.get_project()
        latest = deps.require_episode(current, episode_number)
        planned = latest.model_copy(update={"scenes": scenes, "status": "planned"})
        current.update_episode(planned)
        deps.save_project(current)
    return {**_plan_response(current, planned), **_register_plan(planned, registered)}


def _renamed(scenes: list[Scene], people: dict[str, str], places: dict[str, str]) -> list[Scene]:
    """A plan with provisional ids swapped for the ones the newcomers got."""
    if all(k == v for k, v in people.items()) and all(k == v for k, v in places.items()):
        return scenes
    renamed = []
    for scene in scenes:
        beats = [
            beat.model_copy(update={
                "involved_character_ids": [people.get(c, c) for c in beat.involved_character_ids],
                "location_id": places.get(beat.location_id, beat.location_id),
            })
            for beat in scene.beats
        ]
        renamed.append(scene.model_copy(update={
            "participating_character_ids": [
                people.get(c, c) for c in scene.participating_character_ids
            ],
            "location_id": places.get(scene.location_id, scene.location_id),
            "beats": beats,
        }))
    return renamed


def _register_plan(episode: Episode, already: list[str] | None = None) -> dict:
    """Read a saved plan for new settings. A failure here never loses the plan."""
    registered = list(already or [])
    try:
        registered += registration.register_from(
            [(episode.episode_number, "기획서", plan_text(episode))]
        )
    except Exception as error:  # noqa: BLE001 — the plan is saved either way
        logger.exception("Reading episode %d's plan for settings failed", episode.episode_number)
        return {"registered": registered, "registration_error": str(error)}
    return {"registered": registered}


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
    return {**_plan_response(current, edited), **_register_plan(edited)}
