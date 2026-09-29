"""Putting a new episode between two others: `POST /insert` and `/draft-insert`.

What matters:

- the new episode takes the number it was put in at, and everything from
  there on moves down one — with the chronicle and any checkpoints following;
- an AI draft for it is written from the episode before and the one after,
  with the gap marked in the queue, and nothing is saved by drafting;
- chapters being written are never renumbered under their run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import next_episode
from storyweaver.agents.checkpoint import CheckpointStore, EpisodeCheckpoint
from storyweaver.api import deps, episodes as episodes_api, generation
from storyweaver.models import Episode
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
    project.episodes = [
        Episode(episode_number=n, title=f"{n}화", author_storyline=f"{n}화 개요")
        for n in range(1, 6)
    ]
    project.episodes[0] = project.episodes[0].model_copy(update={
        "status": "completed", "final_text": "본문.", "summary": "1화에 실제로 일어난 일",
    })
    project_store.save(project)
    return project


def _outlines(project_store) -> list[str]:
    return [e.author_storyline for e in project_store.load().episodes]


def test_an_episode_goes_in_between_two_others(client, loaded, project_store):
    response = client.post("/api/episodes/insert", json={"at": 3, "author_storyline": "새 회차"})

    assert response.status_code == 201
    assert _outlines(project_store) == ["1화 개요", "2화 개요", "새 회차", "3화 개요", "4화 개요", "5화 개요"]
    assert [e.episode_number for e in project_store.load().episodes] == [1, 2, 3, 4, 5, 6]


def test_an_episode_can_go_in_first_or_last(client, loaded, project_store):
    client.post("/api/episodes/insert", json={"at": 1, "author_storyline": "맨 앞"})
    client.post("/api/episodes/insert", json={"at": 7, "author_storyline": "맨 뒤"})

    outlines = _outlines(project_store)
    assert outlines[0] == "맨 앞"
    assert outlines[1] == "1화 개요"
    assert outlines[-1] == "맨 뒤"


def test_a_place_past_the_end_is_refused(client, loaded):
    response = client.post("/api/episodes/insert", json={"at": 8, "author_storyline": "x"})

    assert response.status_code == 422


def test_the_chronicle_follows_the_episodes_that_moved(client, loaded, monkeypatch):
    seen = []
    monkeypatch.setattr(episodes_api, "_follow_renumbering", seen.append)

    client.post("/api/episodes/insert", json={"at": 3, "author_storyline": "새 회차"})

    assert seen == [{3: 4, 4: 5, 5: 6}]


def test_a_checkpoint_moves_with_its_chapter(client, loaded, project_store):
    checkpoints = CheckpointStore(project_store.state_dir)
    checkpoints.save(EpisodeCheckpoint(episode_number=4, author_storyline="4화 개요"))

    client.post("/api/episodes/insert", json={"at": 2, "author_storyline": "새 회차"})

    assert checkpoints.load(4) is None
    moved = checkpoints.load(5)
    assert moved is not None and moved.matches(5, "4화 개요")


def test_a_chapter_being_written_is_not_renumbered(client, loaded, monkeypatch, project_store):
    monkeypatch.setattr(generation, "running_generations", lambda: [4])

    response = client.post("/api/episodes/insert", json={"at": 3, "author_storyline": "새 회차"})

    assert response.status_code == 409
    assert "4화" in response.json()["detail"]
    assert len(project_store.load().episodes) == 5


def test_writing_after_the_one_being_written_is_fine(client, loaded, monkeypatch):
    monkeypatch.setattr(generation, "running_generations", lambda: [2])

    response = client.post("/api/episodes/insert", json={"at": 3, "author_storyline": "새 회차"})

    assert response.status_code == 201


# ==========================================================================
# The draft
# ==========================================================================


class _Planner:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return "2화와 3화 사이의 새 개요"


def test_the_draft_is_written_from_both_neighbours(client, loaded, monkeypatch, project_store):
    planner = _Planner()
    monkeypatch.setattr(next_episode, "get_llm", lambda *a, **k: planner)

    body = client.post(
        "/api/episodes/draft-insert", json={"at": 3, "direction": "숨 고르는 회차로"}
    ).json()

    assert body == {"at": 3, "author_storyline": "2화와 3화 사이의 새 개요"}
    prompt = planner.prompts[0]
    before = prompt.split("## The episode just before it (episode 2)")[1].split("##")[0]
    after = prompt.split("## The episode just after it (becomes episode 4)")[1].split("##")[0]
    assert "2화 개요" in before
    assert "3화 개요" in after
    # The queue is numbered as it will be, with the gap marked.
    assert ">>> Episode 3: THE NEW EPISODE GOES HERE <<<" in prompt
    assert "Episode 4 (planned): 3화 개요" in prompt
    assert "Episode 1 (written — what actually happened): 1화에 실제로 일어난 일" in prompt
    assert "숨 고르는 회차로" in prompt
    # Drafting saves nothing.
    assert len(project_store.load().episodes) == 5


def test_a_draft_for_the_very_first_place_has_nothing_before_it(client, loaded, monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(next_episode, "get_llm", lambda *a, **k: planner)

    client.post("/api/episodes/draft-insert", json={"at": 1})

    assert next_episode.NO_BEFORE in planner.prompts[0]


def test_a_failed_draft_is_reported(client, loaded, monkeypatch):
    class Broken:
        def invoke(self, prompt):
            raise RuntimeError("quota exhausted")

    monkeypatch.setattr(next_episode, "get_llm", lambda *a, **k: Broken())

    response = client.post("/api/episodes/draft-insert", json={"at": 3})

    assert response.status_code == 502
