"""Rewriting a finished chapter from the plan it was written to.

A written chapter can be redone two ways: the prose only, to the same plan
(`keep_plan`), or from the plan up, with the Director laying it out again. What
matters:

- `keep_plan` hands the pipeline the old scenes, emptied of the old turns and
  prose, so the Director is skipped;
- without it a finished chapter is planned afresh, as before;
- a kept plan that casts someone no longer in the work is refused up front.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

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


def _written_scene(number: int, cast: str = "harry-potter") -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        participating_character_ids=[cast],
        objective=f"Objective {number}",
        interaction_log=[f"[1] {cast} (dialogue): old turn"],
        prose=f"Old prose {number}.",
    )


@pytest.fixture
def written(project_store, sample_data) -> Project:
    project = project_from_sample(sample_data)
    project.add_episode("Harry is fitted for a wand.", "Ollivanders")
    episode = project.get_episode(2).model_copy(update={
        "status": "completed",
        "final_text": "Old prose 1.\n\nOld prose 2.",
        "scenes": [_written_scene(1), _written_scene(2)],
    })
    project.update_episode(episode)
    project_store.save(project)
    return project


def _wait_until_idle(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not generation.running_generations():
            return
        time.sleep(0.02)
    raise AssertionError("the generation never finished")


def _capture(monkeypatch) -> dict:
    seen: dict = {}

    def run(episode, world, characters, **kwargs):
        seen["plan"] = kwargs.get("plan")
        return episode.model_copy(update={"status": "completed", "final_text": "New prose."}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", run)
    return seen


def test_keeping_the_plan_rewrites_the_prose_to_it(client, written, monkeypatch, project_store):
    seen = _capture(monkeypatch)

    client.get("/api/generation/stream/2?keep_plan=true")
    _wait_until_idle()

    plan = seen["plan"]
    assert [(s.title, s.objective) for s in plan] == [
        ("Scene 1", "Objective 1"),
        ("Scene 2", "Objective 2"),
    ]
    # The old run's turns and prose do not go back in.
    assert all(s.prose == "" and s.interaction_log == [] for s in plan)
    assert project_store.load().get_episode(2).final_text == "New prose."


def test_without_it_a_finished_chapter_is_planned_again(client, written, monkeypatch):
    seen = _capture(monkeypatch)

    client.get("/api/generation/stream/2")
    _wait_until_idle()

    assert seen["plan"] is None  # the Director lays it out afresh


def test_a_chapter_sent_back_with_its_plan_is_written_to_it_bare(
    client, written, monkeypatch, project_store
):
    """The reading room sends a chapter back as 'planned', old prose and all."""
    client.put("/api/episodes/2", json={"status": "planned"})
    seen = _capture(monkeypatch)

    client.get("/api/generation/stream/2")
    _wait_until_idle()

    assert [s.title for s in seen["plan"]] == ["Scene 1", "Scene 2"]
    assert all(s.prose == "" and s.interaction_log == [] for s in seen["plan"])


def test_a_kept_plan_casting_someone_gone_is_refused(client, written, project_store):
    project = project_store.load()
    episode = project.get_episode(2)
    project.update_episode(episode.model_copy(update={
        "scenes": [_written_scene(1, cast="deleted-person")],
    }))
    project_store.save(project)

    response = client.get("/api/generation/check/2?keep_plan=true")

    assert response.status_code == 409
    assert "deleted-person" in response.json()["detail"]
    # Planning afresh is still open.
    assert client.get("/api/generation/check/2").status_code == 200


def test_there_is_no_plan_to_keep_without_scenes(client, written, project_store):
    project = project_store.load()
    project.update_episode(project.get_episode(2).model_copy(update={"scenes": []}))
    project_store.save(project)

    response = client.get("/api/generation/check/2?keep_plan=true")

    assert response.status_code == 409
    assert "기획서" in response.json()["detail"]
