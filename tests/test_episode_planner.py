"""The Story Planner: one line per episode in, an outline per episode out.

Two things carry the weight here. The numbers must be the numbers the queue
will actually give these episodes, because the author approves them by number
and would otherwise approve "1화" only to find it saved as 7화. And nothing may
be written: this is a proposal, and a proposal the author has not accepted is
not part of the story.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps, episodes as episodes_api
from storyweaver.models import Episode
from storyweaver.ui.project import Project, ProjectStore, project_from_sample

LINES = ["지민이 유나와 재회한다", "지민이 유나를 미행한다"]


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
    project_store.save(project)
    return project


def _answers_with(monkeypatch, outline: str = "펼쳐진 기획서 본문.", fail: bool = False):
    """Stub the planner's model and record every prompt it is handed."""
    calls: dict = {"prompts": [], "stage": None}

    class Model:
        def invoke(self, prompt):
            calls["prompts"].append(prompt)
            if fail:
                raise RuntimeError("quota exhausted")

            class Response:
                content = outline

            return Response()

    def fake_get_llm(stage="unknown", **kwargs):
        calls["stage"] = stage
        return Model()

    monkeypatch.setattr(episodes_api, "get_llm", fake_get_llm)
    return calls


# ==========================================================================
# The outlines themselves
# ==========================================================================


def test_each_line_comes_back_as_an_outline(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch, outline="4~6문단짜리 기획서.")

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES})

    assert response.status_code == 200
    body = response.json()["episodes"]
    assert len(body) == 2
    assert [e["author_storyline"] for e in body] == ["4~6문단짜리 기획서."] * 2
    # One model call per line, no more.
    assert len(calls["prompts"]) == 2
    assert calls["stage"] == "planner"


def test_the_authors_own_line_is_kept_beside_the_outline(client, loaded, monkeypatch):
    """The author needs to see what they asked for next to what they got."""
    _answers_with(monkeypatch)

    body = client.post("/api/episodes/plan-all", json={"summaries": LINES}).json()

    assert [e["author_one_line"] for e in body["episodes"]] == LINES


def test_the_numbers_are_where_these_episodes_would_actually_land(
    client, project_store, loaded, monkeypatch
):
    """Numbering from 1 would lie to an author whose queue is not empty."""
    _answers_with(monkeypatch)
    first_free = loaded.next_episode_number()
    assert first_free > 1  # the sample has a queue, so this test means something

    body = client.post("/api/episodes/plan-all", json={"summaries": LINES}).json()

    assert [e["episode_number"] for e in body["episodes"]] == [
        first_free,
        first_free + 1,
    ]
    assert [e["title"] for e in body["episodes"]] == [
        f"{first_free}화",
        f"{first_free + 1}화",
    ]


def test_planning_saves_nothing(client, project_store, loaded, monkeypatch):
    _answers_with(monkeypatch)
    before = len(project_store.load().episodes)

    client.post("/api/episodes/plan-all", json={"summaries": LINES})

    assert len(project_store.load().episodes) == before


# ==========================================================================
# What the model is told
# ==========================================================================


def test_the_cast_and_the_world_reach_the_prompt(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    prompt = calls["prompts"][0]
    assert loaded.world.title in prompt
    for character in loaded.characters:
        assert character.id in prompt


def test_a_later_line_knows_about_the_earlier_ones(client, loaded, monkeypatch):
    """Otherwise two episodes in one batch would each open the same door."""
    calls = _answers_with(monkeypatch)

    client.post("/api/episodes/plan-all", json={"summaries": LINES})

    first, second = calls["prompts"]
    assert LINES[0] not in first.split("THE AUTHOR'S ONE LINE")[0]
    assert LINES[0] in second  # the first line is context for the second
    assert LINES[1] not in first  # but not the other way round


def test_the_episodes_already_in_the_queue_are_context_too(
    client, project_store, loaded, monkeypatch
):
    """A new outline that ignores the existing story is not continuity."""
    project = project_store.load()
    project.episodes.append(
        Episode(
            episode_number=project.next_episode_number(),
            title="지난 화",
            author_storyline="지민이 처음으로 유나의 거짓말을 눈치챈다",
        )
    )
    project_store.save(project)
    calls = _answers_with(monkeypatch)

    client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    assert "지민이 처음으로 유나의 거짓말을 눈치챈다" in calls["prompts"][0]


def test_a_written_chapters_summary_is_preferred_to_its_outline(
    client, project_store, loaded, monkeypatch
):
    """The outline is what was asked for; the summary is what was written."""
    project = project_store.load()
    project.episodes.append(
        Episode(
            episode_number=project.next_episode_number(),
            author_storyline="작가가 부탁한 것",
            summary="실제로 쓰인 것",
            status="completed",
        )
    )
    project_store.save(project)
    calls = _answers_with(monkeypatch)

    client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    assert "실제로 쓰인 것" in calls["prompts"][0]
    assert "작가가 부탁한 것" not in calls["prompts"][0]


# ==========================================================================
# What is refused, and refused before it costs anything
# ==========================================================================


def test_an_empty_list_is_refused(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    assert client.post("/api/episodes/plan-all", json={"summaries": []}).status_code == 422
    assert calls["prompts"] == []


def test_a_blank_line_is_refused_rather_than_planned(client, loaded, monkeypatch):
    """A blank line would cost a model call to discover it said nothing."""
    calls = _answers_with(monkeypatch)

    response = client.post("/api/episodes/plan-all", json={"summaries": ["진짜 줄", "   "]})

    assert response.status_code == 422
    assert calls["prompts"] == []


def test_more_lines_than_the_cap_are_refused_before_any_are_planned(
    client, loaded, monkeypatch
):
    """Each line is real money; a pasted wall of them is refused, not charged."""
    calls = _answers_with(monkeypatch)

    response = client.post(
        "/api/episodes/plan-all", json={"summaries": [f"{i}번째 줄" for i in range(21)]}
    )

    assert response.status_code == 422
    assert calls["prompts"] == []


def test_a_story_with_no_cast_cannot_be_planned(client, project_store, monkeypatch):
    calls = _answers_with(monkeypatch)
    project = Project(name="빈 이야기")
    project.world = project.world.model_copy(update={"overview": "세계는 있다."})
    project_store.save(project)

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    assert response.status_code == 409
    assert calls["prompts"] == []


def test_a_story_with_no_world_cannot_be_planned(
    client, project_store, loaded, monkeypatch
):
    calls = _answers_with(monkeypatch)
    project = project_store.load()
    project.world = project.world.model_copy(update={"overview": "   "})
    project_store.save(project)

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    assert response.status_code == 409
    assert calls["prompts"] == []


# ==========================================================================
# When the model will not cooperate
# ==========================================================================


def test_a_dead_model_is_a_bad_gateway_rather_than_a_crash(client, loaded, monkeypatch):
    _answers_with(monkeypatch, fail=True)

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES})

    assert response.status_code == 502
    assert "quota exhausted" in response.json()["detail"]


def test_an_empty_outline_is_reported_rather_than_returned(client, loaded, monkeypatch):
    """An empty storyline would sail through and produce an empty chapter."""
    _answers_with(monkeypatch, outline="   ")

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES[:1]})

    assert response.status_code == 502


def test_a_failure_halfway_through_saves_nothing(
    client, project_store, loaded, monkeypatch
):
    """Half a batch quietly in the queue would be worse than none of it."""
    before = len(project_store.load().episodes)
    calls: dict = {"n": 0}

    class Model:
        def invoke(self, prompt):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("died on the second one")

            class Response:
                content = "첫 번째 기획서."

            return Response()

    monkeypatch.setattr(episodes_api, "get_llm", lambda **kwargs: Model())

    response = client.post("/api/episodes/plan-all", json={"summaries": LINES})

    assert response.status_code == 502
    assert len(project_store.load().episodes) == before


# ==========================================================================
# Wiring
# ==========================================================================


def test_plan_all_is_not_swallowed_by_the_episode_number_routes(client):
    """`/plan-all` must not be read as episode number "plan-all"."""
    schema = client.get("/openapi.json").json()

    assert "/api/episodes/plan-all" in schema["paths"]
    assert schema["paths"]["/api/episodes/plan-all"]["post"]["tags"] == ["episodes"]
