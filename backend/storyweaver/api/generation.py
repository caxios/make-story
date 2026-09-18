"""Live episode generation, streamed to the browser over Server-Sent Events.

The pipeline is synchronous and long-running, so it runs on a worker thread and
reports through a queue. The request thread does nothing but drain that queue,
which keeps the event loop free and lets a browser watch a ten-minute
generation without a single poll.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
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


@router.get("/stream/{episode_number}")
def stream_generation(
    episode_number: int,
    max_turns: int = Query(default=12, ge=2, le=40),
) -> EventSourceResponse:
    """Generate one episode, reporting each pipeline stage as it finishes.

    Events, in order: "start" once the run begins, "progress" after every
    pipeline node, and then either "complete" with the saved chapter or
    "error" saying whether a checkpoint survived the failure.
    """
    project = deps.get_project()
    episode = deps.require_episode(project, episode_number)

    if not project.world.overview.strip():
        raise HTTPException(status_code=409, detail="This story has no world yet")
    if not project.characters:
        raise HTTPException(status_code=409, detail="This story has no characters yet")
    if not episode.author_storyline.strip():
        raise HTTPException(
            status_code=409, detail="This episode has no storyline to work from"
        )

    with _running_lock:
        if episode_number in _running:
            raise HTTPException(
                status_code=409, detail=f"Episode {episode_number} is already generating"
            )
        _running.add(episode_number)

    return EventSourceResponse(
        iterate_in_threadpool(_run(project, episode_number, max_turns))
    )


def _event(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


def _run(project: Project, episode_number: int, max_turns: int) -> Iterator[dict[str, str]]:
    """Drive one generation, yielding SSE frames as the worker reports in."""
    try:
        yield from _drive(project, episode_number, max_turns)
    finally:
        with _running_lock:
            _running.discard(episode_number)


def _drive(project: Project, episode_number: int, max_turns: int) -> Iterator[dict[str, str]]:
    episode = deps.require_episode(project, episode_number)
    checkpoints = deps.get_checkpoints()
    memory = deps.get_memory()
    progress = GenerationProgress(episode_number=episode_number)

    # Regenerating a finished chapter starts over rather than resuming into
    # scenes that belong to the version being replaced.
    if episode.status == "completed":
        checkpoints.clear(episode_number)

    resumable = checkpoints.load(episode_number)
    resuming = (
        resumable.current_scene_index + 1
        if resumable and resumable.matches(episode_number, episode.author_storyline)
        else None
    )

    project.update_episode(episode.model_copy(update={"status": "in_progress"}))
    deps.save_project(project)

    yield _event(
        "start",
        {
            "episode_number": episode_number,
            "title": episode.title,
            "resuming_from_scene": resuming,
            "memory_available": memory is not None,
        },
    )

    names = {character.id: character.name for character in project.characters}
    events: queue.Queue = queue.Queue()
    outcome: dict[str, Any] = {}

    def on_event(node: str, state: dict[str, Any]) -> None:
        events.put((node, state))

    def work() -> None:
        try:
            with telemetry.record_usage(f"episode {episode_number}") as usage:
                # Published before the run starts: `total_tokens` is computed
                # live, so a progress frame can quote the spend so far.
                outcome["usage"] = usage
                try:
                    done, final = episode_runner.run_episode(
                        episode,
                        project.world,
                        project.character_map(),
                        style=project.style,
                        max_turns_per_scene=max_turns,
                        memory=memory,
                        checkpoints=checkpoints,
                        on_event=on_event,
                    )
                except Exception as error:  # noqa: BLE001 — reported to the client
                    logger.exception("Episode %d failed", episode_number)
                    outcome["error"] = error
                else:
                    outcome["episode"] = done
                    outcome["final"] = final
        finally:
            events.put(_SENTINEL)

    worker = threading.Thread(target=work, name=f"generate-{episode_number}", daemon=True)
    worker.start()

    while True:
        item = events.get()
        if item is _SENTINEL:
            break
        node, state = item
        progress.update(node, state)
        usage = outcome.get("usage")
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
                "scene": _scene_detail(state, names),
                "turns": len(state.get("current_entries", [])),
                "max_turns": max_turns,
                "retry_count": int(state.get("retry_count", 0)),
                "tokens": usage.total_tokens if usage else 0,
                "calls": usage.calls if usage else 0,
            },
        )

    worker.join()
    usage = outcome.get("usage")
    if usage is not None:
        # Recorded whether the run succeeded or failed: a failed run still
        # spent what it spent.
        telemetry_log.record_run(episode_number, usage)
    cost = (
        {
            "calls": usage.calls,
            "total_tokens": usage.total_tokens,
            "report": usage.report(),
        }
        if usage is not None and usage.calls
        else None
    )

    if "error" in outcome:
        error = outcome["error"]
        # The project was left mid-flight; put it back in the queue so the
        # author can simply generate it again.
        current = deps.get_project()
        stalled = current.get_episode(episode_number)
        if stalled is not None:
            current.update_episode(stalled.model_copy(update={"status": "queued"}))
            deps.save_project(current)
        checkpoint = checkpoints.load(episode_number)
        yield _event(
            "error",
            {
                "episode_number": episode_number,
                "message": str(error),
                "type": type(error).__name__,
                "resumable": checkpoint is not None,
                "scenes_completed": checkpoint.scenes_completed if checkpoint else 0,
                "usage": cost,
            },
        )
        return

    done = outcome["episode"]
    final = outcome.get("final", {})
    recorded = memory is not None and "episode_memory" in final
    if recorded:
        progress.note_recorded()

    # Reload before saving: the queue may have moved on while this ran.
    current = deps.get_project()
    current.update_episode(done)
    deps.save_project(current)

    yield _event(
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
