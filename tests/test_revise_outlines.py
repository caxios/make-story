"""Rewriting the outlines of chosen episodes: `POST /api/episodes/revise-outlines`.

The author ticks episodes in the queue and asks for them to be rewritten. What
matters:

- only the chosen episodes come back, and nothing is saved;
- the model sees the whole queue with the chosen ones marked, so a revision
  fits between episodes that are not changing;
- a written chapter's outline is history and cannot be revised.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import next_episode
from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Episode
from storyweaver.models.structure import StoryPart, StoryStructure, tidy_structure
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
    project.episodes = [
        Episode(episode_number=n, title=f"{n}화", author_storyline=f"{n}화 원래 개요")
        for n in range(1, 21)
    ]
    project.episodes[0] = project.episodes[0].model_copy(update={
        "status": "completed", "final_text": "본문.", "summary": "1화에 실제로 일어난 일",
    })
    project.structure = tidy_structure(StoryStructure(
        target_episodes=400,
        parts=[StoryPart(title="귀환", start=1, end=60), StoryPart(title="각성", start=61, end=400)],
    ))
    project_store.save(project)
    return project


def _answers(monkeypatch) -> dict:
    calls: dict = {"prompts": []}

    class Structured:
        def invoke(self, prompt):
            calls["prompts"].append(prompt)
            numbers = [
                int(n.strip().rstrip("화"))
                for n in prompt.split("rewritten: ")[1].split(".")[0].split(",")
            ]
            # The model also answers an episode it was not asked about.
            return next_episode.DraftedBatch(episodes=[
                *(next_episode.DraftedEpisode(number=n, outline=f"{n}화 새 개요") for n in numbers),
                next_episode.DraftedEpisode(number=19, outline="묻지 않은 회차"),
            ])

    class Model:
        def with_structured_output(self, schema):
            return Structured()

    monkeypatch.setattr(next_episode, "get_llm", lambda *a, **k: Model())
    return calls


def test_only_the_chosen_episodes_come_back(client, loaded, monkeypatch):
    _answers(monkeypatch)

    body = client.post(
        "/api/episodes/revise-outlines", json={"episode_numbers": [7, 3]}
    ).json()

    assert [(e["episode_number"], e["before"], e["after"]) for e in body["episodes"]] == [
        (3, "3화 원래 개요", "3화 새 개요"),
        (7, "7화 원래 개요", "7화 새 개요"),
    ]


def test_revising_saves_nothing(client, loaded, monkeypatch, project_store):
    _answers(monkeypatch)

    client.post("/api/episodes/revise-outlines", json={"episode_numbers": [3]})

    assert project_store.load().get_episode(3).author_storyline == "3화 원래 개요"


def test_the_queue_is_shown_with_the_chosen_marked(client, loaded, monkeypatch):
    calls = _answers(monkeypatch)

    client.post(
        "/api/episodes/revise-outlines",
        json={"episode_numbers": [3], "direction": "강소희를 등장시켜줘"},
    )

    prompt = calls["prompts"][0]
    assert "Episode 3 (TO REVISE — current outline): 3화 원래 개요" in prompt
    assert "Episode 4 (planned — stays as it is): 4화 원래 개요" in prompt
    assert "Episode 1 (written — what actually happened): 1화에 실제로 일어난 일" in prompt
    assert "강소희를 등장시켜줘" in prompt
    assert "1부 '귀환'" in prompt  # where the stretch sits in the whole work


def test_a_written_episode_cannot_be_revised(client, loaded, monkeypatch):
    calls = _answers(monkeypatch)

    response = client.post("/api/episodes/revise-outlines", json={"episode_numbers": [1, 2]})

    assert response.status_code == 409
    assert "1화" in response.json()["detail"]
    assert calls["prompts"] == []


def test_an_episode_that_does_not_exist_is_refused(client, loaded, monkeypatch):
    _answers(monkeypatch)

    response = client.post("/api/episodes/revise-outlines", json={"episode_numbers": [99]})

    assert response.status_code == 404


def test_more_than_twenty_is_refused(client, loaded, monkeypatch):
    _answers(monkeypatch)

    response = client.post(
        "/api/episodes/revise-outlines", json={"episode_numbers": list(range(2, 23))}
    )

    assert response.status_code == 422


def test_a_failed_call_is_reported(client, loaded, monkeypatch):
    class Broken:
        def with_structured_output(self, schema):
            raise RuntimeError("quota exhausted")

    monkeypatch.setattr(next_episode, "get_llm", lambda *a, **k: Broken())

    response = client.post("/api/episodes/revise-outlines", json={"episode_numbers": [3]})

    assert response.status_code == 502
