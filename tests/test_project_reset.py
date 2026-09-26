"""Starting a new work: `POST /api/project/reset`.

The usual reason to reset is that a new concept is waiting to be committed and
the old story is in the way. So the property that matters most is that the
concept session survives the reset — and after it, committing works.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.api import generation
from storyweaver.concept_store import ConceptStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models.concept import ConceptSession
from storyweaver.ui.project import Project, ProjectStore, project_from_sample

from tests.test_concept_api import _concept


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def memory(project_store, vector_store) -> MemoryManager:
    # The same state directory the project store resets, as in the real app.
    return MemoryManager(vector_store=vector_store, data_dir=project_store.state_dir)


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
    project.add_episode("1화 줄거리")
    project.style.author_style_notes = "짧은 문단."
    project_store.save(project)
    return project


def test_reset_empties_the_work(client, loaded):
    project = client.post("/api/project/reset").json()

    assert project["characters"] == []
    assert project["episodes"] == []
    assert not project["world"]["overview"].strip()


def test_how_the_author_writes_survives(client, loaded):
    project = client.post("/api/project/reset").json()

    assert project["style"]["author_style_notes"] == "짧은 문단."


def test_the_wiki_and_memory_are_emptied(client, loaded, memory, harry):
    memory.chronicle.record("character", harry.id, "appearance", "짧은 머리",
                            source="episode", episode_number=1)
    memory.vector_store.seed_world_lore(loaded.world)
    assert memory.vector_store.count("world_lore") > 0

    client.post("/api/project/reset")

    assert memory.chronicle.is_empty()
    assert memory.vector_store.count("world_lore") == 0
    rows = client.get("/api/wiki/subjects").json()
    assert {r["subject_type"] for r in rows} == {"story", "world"}


def test_the_concept_waiting_to_be_committed_survives(client, loaded, project_store):
    concepts = ConceptStore(project_store.state_dir)
    concepts.save(ConceptSession(chosen=_concept(), status="refining"))

    # The reason to reset: this is refused on a project with a story in it.
    assert client.post("/api/concept/commit").status_code == 409

    client.post("/api/project/reset")

    assert concepts.load().chosen.title == "사념세계의 문"
    assert client.post("/api/concept/commit").status_code == 200
    assert {c["name"] for c in client.get("/api/project").json()["characters"]} == {
        "박동혁", "시월",
    }


def test_a_committed_concept_can_be_committed_again(client, loaded, project_store):
    concepts = ConceptStore(project_store.state_dir)
    concepts.save(ConceptSession(chosen=_concept(), status="committed"))

    client.post("/api/project/reset")

    assert concepts.load().status == "refining"


def test_reset_is_refused_while_a_chapter_is_being_written(client, loaded, monkeypatch):
    monkeypatch.setattr(generation, "_running", {1})

    assert client.post("/api/project/reset").status_code == 409
    assert client.get("/api/project").json()["characters"]
