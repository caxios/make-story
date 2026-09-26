"""Planning twenty episodes at once: `POST /api/episodes/draft-batch` and `/many`.

Adding an episode used to mean one outline at a time. Now 회차 추가 plans the
next stretch — 1~20, then 21~40 — as one run, paced by the work's structure.
What matters:

- the numbers are the next ones in the queue, and exactly as many as asked;
- the model is shown where the stretch sits: parts, threads and relationship
  turns inside it;
- nothing is queued until the author keeps it, and then in order.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import next_episode
from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Episode
from storyweaver.models.structure import (
    PlannedRelationship,
    PlannedThread,
    RelationshipTurn,
    StoryPart,
    StoryStructure,
    tidy_structure,
)
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import STORY_SUBJECT_ID


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
        Episode(episode_number=n, title=f"{n}화", author_storyline=f"{n}화 줄거리")
        for n in range(1, 21)
    ]
    project.structure = tidy_structure(
        StoryStructure(
            target_episodes=400,
            parts=[StoryPart(title="귀환", start=1, end=60, purpose="적응한다."),
                   StoryPart(title="각성", start=61, end=400)],
            threads=[PlannedThread(name="편지", description="동생이 보냈다", plant=25, payoff=150)],
            relationships=[PlannedRelationship(
                characters=["해리", "론"], arc="절친이 된다",
                turns=[RelationshipTurn(episode=33, change="처음 크게 다툰다")],
            )],
        )
    )
    project_store.save(project)
    return project


def _answers(monkeypatch, *, skip: set[int] = frozenset(), fail: bool = False) -> dict:
    calls: dict = {"prompts": [], "max_tokens": None}

    class Structured:
        def invoke(self, prompt):
            calls["prompts"].append(prompt)
            if fail:
                raise RuntimeError("quota exhausted")
            start = int(prompt.split("decide what happens in episodes ")[1].split(" ")[0])
            count = int(prompt.split(" — ")[1].split(" episodes")[0])
            return next_episode.DraftedBatch(episodes=[
                next_episode.DraftedEpisode(number=n, outline=f"{n}화 새 개요")
                for n in range(start, start + count) if n not in skip
            ])

    class Model:
        def with_structured_output(self, schema):
            return Structured()

    def fake_get_llm(stage="unknown", max_output_tokens=None, **kwargs):
        calls["max_tokens"] = max_output_tokens
        return Model()

    monkeypatch.setattr(next_episode, "get_llm", fake_get_llm)
    return calls


def test_the_next_twenty_are_drafted(client, loaded, monkeypatch):
    _answers(monkeypatch)

    drafted = client.post("/api/episodes/draft-batch", json={}).json()["episodes"]

    assert [e["episode_number"] for e in drafted] == list(range(21, 41))
    assert drafted[0]["author_storyline"] == "21화 새 개요"


def test_fewer_can_be_asked_for(client, loaded, monkeypatch):
    _answers(monkeypatch)

    drafted = client.post("/api/episodes/draft-batch", json={"count": 5}).json()["episodes"]

    assert [e["episode_number"] for e in drafted] == [21, 22, 23, 24, 25]


def test_more_than_twenty_is_refused(client, loaded, monkeypatch):
    _answers(monkeypatch)

    assert client.post("/api/episodes/draft-batch", json={"count": 21}).status_code == 422


def test_drafting_saves_nothing(client, loaded, monkeypatch, project_store):
    _answers(monkeypatch)

    client.post("/api/episodes/draft-batch", json={})

    assert len(project_store.load().episodes) == 20


def test_the_stretch_is_told_where_it_sits(client, loaded, monkeypatch):
    calls = _answers(monkeypatch)

    client.post("/api/episodes/draft-batch", json={"direction": "론과의 우정을 키워줘"})

    prompt = calls["prompts"][0]
    assert "이번에 쓸 회차는 21~40화" in prompt
    assert "25화 즈음 '편지'" in prompt                       # a thread planted inside
    assert "33화 즈음 해리·론 — 처음 크게 다툰다" in prompt     # a relationship turn inside
    assert "론과의 우정을 키워줘" in prompt
    assert "Rules this world will not break" in prompt         # the rules reach planning


def test_a_batch_is_not_held_to_the_shared_cap(client, loaded, monkeypatch):
    from storyweaver.llm import MODEL_MAX_OUTPUT_TOKENS

    calls = _answers(monkeypatch)

    client.post("/api/episodes/draft-batch", json={})

    assert calls["max_tokens"] == MODEL_MAX_OUTPUT_TOKENS


def test_an_episode_the_model_skipped_is_left_out_not_invented(client, loaded, monkeypatch):
    _answers(monkeypatch, skip={23})

    drafted = client.post("/api/episodes/draft-batch", json={"count": 4}).json()["episodes"]

    assert [e["episode_number"] for e in drafted] == [21, 22, 24]


def test_a_failed_call_is_reported(client, loaded, monkeypatch):
    _answers(monkeypatch, fail=True)

    response = client.post("/api/episodes/draft-batch", json={})

    assert response.status_code == 502
    assert "21~40화" in response.json()["detail"]


def test_the_kept_outlines_are_queued_in_order(client, loaded, project_store, memory):
    added = client.post("/api/episodes/many", json={"episodes": [
        {"author_storyline": "21화 새 개요"}, {"author_storyline": "22화 새 개요"},
    ]}).json()

    assert [e["episode_number"] for e in added] == [21, 22]
    assert project_store.load().episodes[-1].author_storyline == "22화 새 개요"
    log = memory.chronicle.chain("story", STORY_SUBJECT_ID, "episodes")
    assert log[-1].value == "22화 — 22화 새 개요"


def test_the_first_batch_of_an_empty_queue_starts_at_one(client, project_store, sample_data, monkeypatch):
    project = project_from_sample(sample_data)
    project.episodes = []
    project_store.save(project)
    _answers(monkeypatch)

    drafted = client.post("/api/episodes/draft-batch", json={}).json()["episodes"]

    assert drafted[0]["episode_number"] == 1 and drafted[-1]["episode_number"] == 20
