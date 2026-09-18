"""A chapter in progress survives everything short of its own failure.

Each test here is a way a real generation was lost:

- episode 4 wrote all four scenes, then died generating its *title*;
- episode 5 was left "in progress" forever with nothing behind it, because the
  result was only ever saved by the SSE stream — so when the stream closed,
  nothing saved it;
- a finished chapter's checkpoint was deleted before the chapter was saved,
  leaving a window where the prose existed nowhere on disk.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import episode_runner
from storyweaver.agents.checkpoint import CheckpointStore, EpisodeCheckpoint
from storyweaver.api import deps, generation
from storyweaver.models import Scene
from storyweaver.ui.project import Project, ProjectStore, project_from_sample


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def client(project_store):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled for tests")
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)


@pytest.fixture
def loaded(project_store, sample_data) -> Project:
    project = project_from_sample(sample_data)
    project.add_episode("Harry is fitted for a wand.", "Ollivanders")
    project_store.save(project)
    return project


def _wait_until_idle(timeout: float = 10.0) -> None:
    """Block until no generation is running, or fail."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not generation.running_generations():
            return
        time.sleep(0.02)
    raise AssertionError("the generation never finished")


def _scene(number: int = 1) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        participating_character_ids=["harry-potter"],
        objective="Get there.",
    )


# ==========================================================================
# The job outlives its watcher
#
# `TestClient` cannot simulate a disconnect: leaving a stream early just waits
# for the response to finish. So these drive the pieces directly — the job is
# started by the handler, and the watcher is `_relay`, closed the same way
# Starlette closes it when a browser goes away.
# ==========================================================================


def _held_run(release: threading.Event, *, fail: bool = False):
    """A stand-in pipeline that waits for the test before finishing."""

    def run(episode, world, characters, *, on_event=None, **kwargs):
        on_event("director_plan_scenes", {"scenes": [_scene()]})
        assert release.wait(10), "the test never let the run finish"
        if fail:
            raise RuntimeError("quota exhausted")
        return (
            episode.model_copy(
                update={"status": "completed", "final_text": "Finished while nobody watched."}
            ),
            {},
        )

    return run


def _start(project_store, episode_number: int = 2):
    """What the endpoint does before it starts streaming."""
    with generation._running_lock:
        generation._running.add(episode_number)
    return generation._start_job(project_store.load(), episode_number, 12)


def test_closing_the_stream_does_not_lose_the_chapter(
    client, project_store, loaded, monkeypatch
):
    """The episode-5 failure: nobody watching meant nobody saving."""
    release = threading.Event()
    monkeypatch.setattr(generation.episode_runner, "run_episode", _held_run(release))

    job = _start(project_store)
    relay = generation._relay(job)
    assert next(relay)["event"] == "start"
    relay.close()  # the browser goes away, mid-run

    # The watcher is gone. The job is not.
    assert not job.watching.is_set()
    assert generation.running_generations() == [2]
    assert project_store.load().get_episode(2).status == "in_progress"

    release.set()
    _wait_until_idle()

    saved = project_store.load().get_episode(2)
    assert saved.status == "completed"
    assert saved.final_text == "Finished while nobody watched."


def test_a_job_whose_stream_never_opened_still_saves(
    client, project_store, loaded, monkeypatch
):
    """A client that drops before the first byte still gets its chapter written."""
    release = threading.Event()
    monkeypatch.setattr(generation.episode_runner, "run_episode", _held_run(release))

    generation.stream_generation(2, max_turns=12)  # handler runs; body never read

    release.set()
    _wait_until_idle()

    assert project_store.load().get_episode(2).status == "completed"


def test_a_failure_nobody_watched_still_returns_the_episode_to_the_queue(
    client, project_store, loaded, monkeypatch
):
    release = threading.Event()
    monkeypatch.setattr(
        generation.episode_runner, "run_episode", _held_run(release, fail=True)
    )

    relay = generation._relay(_start(project_store))
    next(relay)
    relay.close()

    release.set()
    _wait_until_idle()

    # Not stuck "in progress": back in the queue, ready to be generated again.
    assert project_store.load().get_episode(2).status == "queued"


def test_the_same_episode_cannot_start_twice_while_an_unwatched_run_continues(
    client, loaded, monkeypatch
):
    """Before, closing the stream freed the slot while the worker kept going."""
    release = threading.Event()
    monkeypatch.setattr(generation.episode_runner, "run_episode", _held_run(release))

    generation.stream_generation(2, max_turns=12)  # started, and nobody watching
    second = client.get("/api/generation/stream/2")

    release.set()
    _wait_until_idle()

    assert second.status_code == 409
    assert "already generating" in second.json()["detail"]


# ==========================================================================
# The title is never worth the chapter
# ==========================================================================


def test_a_failed_title_still_saves_the_chapter_untitled(world, characters, scripted_llm):
    """The episode-4 failure: four finished scenes, lost to a title."""

    def refuse_title(prompt, index):
        raise RuntimeError("safety block on the title")

    state = {
        "episode": episode_runner.Episode(episode_number=4, author_storyline="x"),
        "world_lore": world,
        "scenes": [_scene(1), _scene(2)],
        "writing_style": episode_runner.WritingStyle(),
        "scene_prose_outputs": ["First scene.", "Second scene."],
        "transitions": [],
    }
    models = episode_runner.PipelineModels(titler=scripted_llm(EpisodeTitle=refuse_title))

    result = episode_runner.assemble_final_text(state, models, auto_title=True)

    assert result["episode"].status == "completed"
    assert result["episode"].title == ""
    assert "First scene." in result["final_episode_text"]
    assert "Second scene." in result["final_episode_text"]


def test_resuming_after_every_scene_is_written_goes_straight_to_assembly(
    tmp_path, world, characters, scripted_llm
):
    """The episode-4 checkpoint: scene index 4 of 4, only the title left.

    Resume used to send every run to `simulate_scene`, which would index a
    fifth scene that does not exist. Nothing but the titler may be called.
    """
    storyline = "Harry is fitted for a wand."
    store = CheckpointStore(tmp_path / "state")
    store.save(
        EpisodeCheckpoint(
            episode_number=4,
            author_storyline=storyline,
            scenes=[_scene(1), _scene(2)],
            scene_prose_outputs=["The shop was narrow.", "The wand chose him."],
            current_scene_index=2,  # past the last scene: all written
        )
    )
    # Answers titling and nothing else — any other agent call fails the test.
    only_titles = scripted_llm(
        EpisodeTitle=lambda prompt, index: episode_runner.EpisodeTitle(title="Ollivanders")
    )
    models = episode_runner.PipelineModels(
        director=only_titles,
        character=only_titles,
        supervisor=only_titles,
        lore=only_titles,
        writer=only_titles,
        transition=only_titles,
        titler=only_titles,
    )

    done, _ = episode_runner.run_episode(
        episode_runner.Episode(episode_number=4, author_storyline=storyline),
        world,
        characters,
        models=models,
        checkpoints=store,
    )

    assert done.status == "completed"
    assert done.title == "Ollivanders"
    assert "The shop was narrow." in done.final_text
    assert "The wand chose him." in done.final_text
    assert len(only_titles.calls) == 1  # the title, and nothing re-simulated


# ==========================================================================
# The checkpoint outlives the chapter's journey to disk
# ==========================================================================


def test_run_episode_can_leave_the_checkpoint_for_the_caller(tmp_path, monkeypatch):
    """Until the caller has saved the chapter, the checkpoint is its only copy."""
    store = CheckpointStore(tmp_path / "state")
    store.save(EpisodeCheckpoint(episode_number=3, author_storyline="x"))

    episode = episode_runner.Episode(episode_number=3, author_storyline="x")
    done = episode.model_copy(update={"status": "completed", "final_text": "done"})
    monkeypatch.setattr(
        episode_runner,
        "stream_episode",
        lambda *a, **k: iter([("assemble_episode", {"episode": done})]),
    )
    monkeypatch.setattr(episode_runner, "_validate", lambda *a, **k: None)

    episode_runner.run_episode(
        episode, None, {}, checkpoints=store, resume=False, clear_checkpoint=False
    )
    assert store.load(3) is not None, "kept for the caller to clear after saving"

    episode_runner.run_episode(episode, None, {}, checkpoints=store, resume=False)
    assert store.load(3) is None, "the default still clears it, for the CLI"


def test_a_successful_generation_clears_its_checkpoint_only_after_saving(
    client, project_store, loaded, monkeypatch
):
    checkpoints = CheckpointStore(project_store.state_dir)
    checkpoints.save(EpisodeCheckpoint(episode_number=2, author_storyline="x"))

    def run(episode, world, characters, **kwargs):
        # While the pipeline runs, the checkpoint must still be there.
        assert kwargs["clear_checkpoint"] is False
        assert checkpoints.load(2) is not None
        return episode.model_copy(update={"status": "completed", "final_text": "ok"}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", run)

    client.get("/api/generation/stream/2")
    _wait_until_idle()

    assert project_store.load().get_episode(2).status == "completed"
    assert checkpoints.load(2) is None


def test_a_failed_generation_keeps_its_checkpoint(client, project_store, loaded, monkeypatch):
    checkpoints = CheckpointStore(project_store.state_dir)
    checkpoints.save(EpisodeCheckpoint(episode_number=2, author_storyline="x"))

    def explode(*args, **kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(generation.episode_runner, "run_episode", explode)

    client.get("/api/generation/stream/2")
    _wait_until_idle()

    assert checkpoints.load(2) is not None, "the finished scenes are what resume needs"


# ==========================================================================
# A dead process leaves nothing stranded
# ==========================================================================


def test_startup_puts_a_stranded_episode_back_in_the_queue(project_store, loaded):
    """The episode-5 state: "in progress", with no process behind it."""
    stranded = loaded.get_episode(2).model_copy(update={"status": "in_progress"})
    loaded.update_episode(stranded)
    project_store.save(loaded)

    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled for tests")
    try:
        with TestClient(app):  # entering runs the lifespan, i.e. a fresh start
            pass
    finally:
        deps.set_store(None)

    assert project_store.load().get_episode(2).status == "queued"


def test_recovery_leaves_finished_and_queued_episodes_alone(project_store, loaded):
    deps.set_store(project_store)
    try:
        assert generation.recover_interrupted() == []
    finally:
        deps.set_store(None)

    statuses = [e.status for e in project_store.load().episodes]
    assert statuses == [e.status for e in loaded.episodes]
