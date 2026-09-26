"""Deleting several episodes at once: `POST /api/episodes/delete-many`.

The property that matters is that the numbers the author ticked are the
chapters that go — deleting one at a time would renumber after each call, so
"3 and 5" would take 3 and then what used to be 6.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps, generation
from storyweaver.memory.manager import MemoryManager
from storyweaver.ui.project import Project, ProjectStore, project_from_sample


class InertVectors:
    def seed_world_lore(self, world):
        return 0


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def memory(project_store) -> MemoryManager:
    return MemoryManager(vector_store=InertVectors(), data_dir=project_store.state_dir)


@pytest.fixture
def client(project_store, memory):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


@pytest.fixture
def loaded(project_store, sample_data) -> Project:
    project = project_from_sample(sample_data)
    project.episodes = []
    for n in range(1, 8):
        project.add_episode(f"원래 {n}화")
    project_store.save(project)
    return project


def _delete(client, *numbers):
    return client.post("/api/episodes/delete-many", json={"episode_numbers": list(numbers)})


def test_the_ticked_episodes_are_the_ones_that_go(client, loaded, project_store):
    assert _delete(client, 3, 5).status_code == 200

    lines = [e.author_storyline for e in project_store.load().episodes]
    assert lines == ["원래 1화", "원래 2화", "원래 4화", "원래 6화", "원래 7화"]


def test_the_queue_is_renumbered_once_with_no_gaps(client, loaded, project_store):
    _delete(client, 1, 4, 7)

    assert [e.episode_number for e in project_store.load().episodes] == [1, 2, 3, 4]


def test_the_wiki_follows_the_renumbering(client, loaded, memory):
    memory.chronicle.record("world", "world", "events", "6화의 일", source="episode", episode_number=6)
    memory.chronicle.record("world", "world", "events", "3화의 일", source="episode", episode_number=3)

    _delete(client, 3, 5)

    entries = memory.chronicle.chain("world", "world", "events", include_all=True)
    # 3화's record went with it; 6화 is now 4화.
    assert [(e.value, e.episode_number) for e in entries] == [("6화의 일", 4)]


def test_an_unknown_number_refuses_the_whole_request(client, loaded, project_store):
    assert _delete(client, 2, 99).status_code == 404
    assert len(project_store.load().episodes) == 7


def test_an_episode_being_written_cannot_be_deleted(client, loaded, project_store, monkeypatch):
    monkeypatch.setattr(generation, "_running", {3})

    assert _delete(client, 3, 4).status_code == 409
    assert len(project_store.load().episodes) == 7


def test_deleting_everything_leaves_an_empty_queue(client, loaded, project_store):
    _delete(client, *range(1, 8))

    assert project_store.load().episodes == []
