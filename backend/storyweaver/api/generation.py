"""Live episode generation, streamed to the browser over Server-Sent Events.

A generation is a *job*, and the stream is only a window onto it.

The pipeline is synchronous and long-running, so each run is a worker thread
that owns its own outcome: it saves the finished chapter, puts a failed one back
in the queue, and records what it spent — all by itself. The SSE stream merely
relays progress while someone is watching.

That separation is the whole point. A browser tab closes, a laptop sleeps, a
proxy drops an idle connection, the author clicks "stop watching" — none of
those may cost a chapter that is minutes into being written. Earlier the
bookkeeping lived in the stream, so the moment the stream closed a finished
chapter was never saved, and its status stayed "in progress" forever.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

from storyweaver import telemetry
from storyweaver.agents import episode_runner
from storyweaver.api import deps, telemetry as telemetry_log
from storyweaver.ui.progress import NODE_STAGES, GenerationProgress
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/generation", tags=["generation"])

# Episodes with a generation in flight. Two runs of the same chapter would
# fight over the checkpoint file and the saved project.
_running: set[int] = set()
_running_lock = threading.Lock()

_SENTINEL = object()

# The pipeline node names, as the stage an author would name: what the stepper
# in the browser highlights.
_STAGES = {node: stage.value for node, stage in NODE_STAGES.items()}


def _scene_detail(
    state: dict[str, Any], names: dict[str, str]
) -> dict[str, Any] | None:
    """What the scene in flight is about, for the live view.

    The pipeline state already carries the Director's plan; without this the
    browser would only ever know a scene by its number.
    """
    scenes = state.get("scenes") or []
    index = int(state.get("current_scene_index", 0))
    if not 0 <= index < len(scenes):
        return None
    scene = scenes[index]
    try:
        return {
            "number": scene.scene_number,
            "title": scene.title,
            "objective": scene.objective,
            # Names, not ids: this is read by a person, not a prompt.
            "characters": [
                names.get(character_id, character_id)
                for character_id in scene.participating_character_ids
            ],
        }
    except AttributeError:
        # Decoration for a live view is never worth aborting a stream over,
        # and aborting the stream is what an exception in here would do.
        logger.exception("Could not describe scene %d", index + 1)
        return None


@router.get("/pending")
def pending_generations() -> list[dict]:
    """Episodes that stopped partway and can be resumed from their checkpoint."""
    return [
        {
            "episode_number": checkpoint.episode_number,
            "current_scene_index": checkpoint.current_scene_index,
            "scenes_completed": checkpoint.scenes_completed,
        }
        for checkpoint in deps.get_checkpoints().pending()
    ]


@router.get("/running")
def running_generations() -> list[int]:
    with _running_lock:
        return sorted(_running)


def _check_startable(project: Project, episode_number: int) -> None:
    """Everything that would stop a generation from starting, as an HTTP error.

    Shared by the stream and by `/check`, so the two can never disagree about
    whether an episode is ready.
    """
    episode = deps.require_episode(project, episode_number)
    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="This story has no world yet")
    if not project.characters:
        raise HTTPException(status_code=409, detail="This story has no characters yet")
    if not episode.author_storyline.strip():
        raise HTTPException(
            status_code=409, detail="This episode has no storyline to work from"
        )


@router.get("/check/{episode_number}")
def check_generation(
    episode_number: int,
    max_turns: int = Query(default=12, ge=2, le=40),
) -> dict:
    """Would `/stream` start this episode? Answers without starting anything.

    The browser's EventSource cannot read the body of a refused request — it
    only learns that the connection failed, and has to guess why. Asking here
    first, with an ordinary request, is how the author gets the real reason:
    the same validation, the same status codes, the same message.
    """
    _check_startable(deps.get_project(), episode_number)
    with _running_lock:
        if episode_number in _running:
            raise HTTPException(
                status_code=409, detail=f"Episode {episode_number} is already generating"
            )
    checkpoint = deps.get_checkpoints().load(episode_number)
    return {
        "episode_number": episode_number,
        "max_turns": max_turns,
        "resumable": checkpoint is not None,
        "scenes_completed": checkpoint.scenes_completed if checkpoint else 0,
    }


@router.get("/stream/{episode_number}")
def stream_generation(
    episode_number: int,
    max_turns: int = Query(default=12, ge=2, le=40),
) -> EventSourceResponse:
    """Start generating one episode, and watch it.

    The job starts here, in the request handler, before any event is streamed —
    so it runs to the end and saves its result whether or not anyone stays to
    watch. Events, in order: "start", then "progress" after every pipeline node,
    then either "complete" with the saved chapter or "error" saying whether a
    checkpoint survived the failure.
    """
    project = deps.get_project()
    _check_startable(project, episode_number)

    with _running_lock:
        if episode_number in _running:
            raise HTTPException(
                status_code=409, detail=f"Episode {episode_number} is already generating"
            )
        _running.add(episode_number)

    try:
        job = _start_job(project, episode_number, max_turns)
    except BaseException:
        with _running_lock:
            _running.discard(episode_number)
        raise

    return EventSourceResponse(iterate_in_threadpool(_relay(job)))


def _event(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


# ==========================================================================
# The job
# ==========================================================================


@dataclass
class _Job:
    episode_number: int
    max_turns: int
    names: dict[str, str]
    start: dict[str, Any]
    memory_available: bool
    events: queue.Queue = field(default_factory=queue.Queue)
    outcome: dict[str, Any] = field(default_factory=dict)
    # Cleared when the watcher goes away, so a job nobody is watching stops
    # queueing progress frames that would only pile up in memory.
    watching: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


def _start_job(project: Project, episode_number: int, max_turns: int) -> _Job:
    episode = deps.require_episode(project, episode_number)
    checkpoints = deps.get_checkpoints()
    memory = deps.get_memory()

    # Regenerating a finished chapter starts over rather than resuming into
    # scenes that belong to the version being replaced.
    if episode.status == "completed":
        checkpoints.clear(episode_number)

    # An approved plan is used as it stands. A checkpoint outranks it: that run
    # is already past planning, and its scenes carry prose.
    approved_plan = (
        list(episode.scenes) if episode.status == "planned" and episode.scenes else None
    )

    resumable = checkpoints.load(episode_number)
    resuming = (
        resumable.current_scene_index + 1
        if resumable and resumable.matches(episode_number, episode.author_storyline)
        else None
    )

    project.update_episode(episode.model_copy(update={"status": "in_progress"}))
    deps.save_project(project)

    # The chapter is written from what the story has made of these people and
    # places, not from the sheet the author filled in before it started. The
    # fold happens once, here, so no agent has to remember to do it.
    folded = deps.folded_project(project)

    job = _Job(
        episode_number=episode_number,
        max_turns=max_turns,
        names={character.id: character.name for character in project.characters},
        start={
            "episode_number": episode_number,
            "title": episode.title,
            "resuming_from_scene": resuming,
            "memory_available": memory is not None,
        },
        memory_available=memory is not None,
    )
    job.watching.set()

    def on_event(node: str, state: dict[str, Any]) -> None:
        if job.watching.is_set():
            job.events.put((node, state))

    def work() -> None:
        try:
            with telemetry.record_usage(f"episode {episode_number}") as usage:
                # Published before the run starts: `total_tokens` is computed
                # live, so a progress frame can quote the spend so far.
                job.outcome["usage"] = usage
                try:
                    done, final = episode_runner.run_episode(
                        episode,
                        folded.world,
                        folded.character_map(),
                        style=folded.style,
                        max_turns_per_scene=max_turns,
                        memory=memory,
                        checkpoints=checkpoints,
                        on_event=on_event,
                        # Kept until the chapter is saved below: until then the
                        # checkpoint is the only copy of the prose on disk.
                        clear_checkpoint=False,
                        # Scenes the author approved are written as approved;
                        # only an unplanned episode gets the Director.
                        plan=approved_plan,
                        review_chronicle=folded.review_chronicle,
                    )
                except Exception as error:  # noqa: BLE001 — reported to the client
                    logger.exception("Episode %d failed", episode_number)
                    job.outcome["error"] = error
                else:
                    job.outcome["episode"] = done
                    job.outcome["final"] = final
            _settle(job, checkpoints)
        except Exception:  # noqa: BLE001 — never let the job die without a word
            logger.exception("Episode %d: could not settle the result", episode_number)
        finally:
            with _running_lock:
                _running.discard(episode_number)
            job.events.put(_SENTINEL)

    job.thread = threading.Thread(target=work, name=f"generate-{episode_number}", daemon=True)
    job.thread.start()
    return job


def _settle(job: _Job, checkpoints) -> None:
    """Persist a finished run. Runs on the worker, watched or not."""
    number = job.episode_number
    usage = job.outcome.get("usage")
    if usage is not None:
        # Recorded whether the run succeeded or failed: a failed run still
        # spent what it spent.
        telemetry_log.record_run(number, usage)

    with deps.write_lock():
        # Reloaded rather than reused: the run took minutes, and the author may
        # have edited the queue in the meantime.
        current = deps.get_project()
        latest = current.get_episode(number)

        if "error" in job.outcome:
            # Back in the queue, so the author can simply generate it again —
            # it resumes from the checkpoint rather than starting over.
            if latest is not None:
                current.update_episode(latest.model_copy(update={"status": "queued"}))
                deps.save_project(current)
            return

        current.update_episode(job.outcome["episode"])
        deps.save_project(current)

    # Only now is the chapter safely on disk, so only now may the checkpoint go.
    checkpoints.clear(number)
    job.outcome["saved"] = True


# ==========================================================================
# The window onto it
# ==========================================================================


def _relay(job: _Job) -> Iterator[dict[str, str]]:
    """Stream a job's progress. Closing this stream does not stop the job."""
    progress = GenerationProgress(episode_number=job.episode_number)
    try:
        yield _event("start", job.start)

        while True:
            item = job.events.get()
            if item is _SENTINEL:
                break
            node, state = item
            progress.update(node, state)
            usage = job.outcome.get("usage")
            yield _event(
                "progress",
                {
                    "node": node,
                    "stage": _STAGES.get(node, ""),
                    "current_scene": progress.current_scene,
                    "total_scenes": progress.scene_count,
                    "label": progress.current_label(),
                    "summary": progress.events[-1].text if progress.events else "",
                    "fraction": progress.fraction(),
                    "checklist": progress.lines(),
                    "scene": _scene_detail(state, job.names),
                    "turns": len(state.get("current_entries", [])),
                    "max_turns": job.max_turns,
                    "retry_count": int(state.get("retry_count", 0)),
                    "tokens": usage.total_tokens if usage else 0,
                    "calls": usage.calls if usage else 0,
                },
            )

        yield _final_event(job, progress)
    finally:
        # The watcher has gone — finished, or walked away. The job carries on
        # regardless; it just stops queueing frames nobody will read.
        job.watching.clear()


def _final_event(job: _Job, progress: GenerationProgress) -> dict[str, str]:
    usage = job.outcome.get("usage")
    cost = (
        {
            "calls": usage.calls,
            "total_tokens": usage.total_tokens,
            "report": usage.report(),
        }
        if usage is not None and usage.calls
        else None
    )

    if "error" in job.outcome or not job.outcome.get("saved"):
        error = job.outcome.get("error") or RuntimeError(
            "The chapter was written but could not be saved"
        )
        checkpoint = deps.get_checkpoints().load(job.episode_number)
        return _event(
            "error",
            {
                "episode_number": job.episode_number,
                "message": str(error),
                "type": type(error).__name__,
                "resumable": checkpoint is not None,
                "scenes_completed": checkpoint.scenes_completed if checkpoint else 0,
                "usage": cost,
            },
        )

    done = job.outcome["episode"]
    final = job.outcome.get("final", {})
    recorded = job.memory_available and "episode_memory" in final
    if recorded:
        progress.note_recorded()

    return _event(
        "complete",
        {
            "episode": done.model_dump(),
            "words": len(done.final_text.split()),
            "scenes": len(done.scenes),
            "checklist": progress.lines(),
            "recorded_to_memory": recorded,
            "usage": cost,
        },
    )


# ==========================================================================
# Recovery
# ==========================================================================


def recover_interrupted() -> list[int]:
    """Put back in the queue any episode a dead process left "in progress".

    Called at startup, when by definition nothing is running. A server that
    was stopped mid-generation — Ctrl+C, a crash, a reload triggered by a file
    save — leaves its episode marked "in progress" with nothing behind it, and
    nothing else would ever clear that. Its checkpoint, if any, is kept, so
    generating it again resumes from the last finished scene.
    """
    with deps.write_lock():
        project = deps.get_project()
        stranded = [e for e in project.episodes if e.status == "in_progress"]
        for episode in stranded:
            project.update_episode(episode.model_copy(update={"status": "queued"}))
        if stranded:
            deps.save_project(project)
    return [e.episode_number for e in stranded]
