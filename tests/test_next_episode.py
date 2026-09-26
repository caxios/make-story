"""Drafting the next episode's outline: `POST /api/episodes/draft-next`.

After the concept's opening chapters, adding an episode meant the author writing
its outline from memory. This asks the model instead — and the properties that
matter are what it is shown (the wiki, every episode, the open threads, the
work's direction, the author's wish) and that nothing is saved until the author
has read it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import next_episode
from storyweaver.api import deps
from storyweaver.api import episodes as episodes_api
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Episode
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
        Episode(episode_number=1, title="1화", author_storyline="해리가 호그와트에 도착한다.",
                status="completed", final_text="본문.",
                summary="해리는 호그와트에 도착해 기숙사를 배정받았다."),
        Episode(episode_number=2, title="2화", author_storyline="해리가 비밀의 방 소문을 듣는다."),
    ]
    project_store.save(project)
    return project


class _Blocks:
    """How Gemini actually answers: a list of content blocks, not a string."""

    def __init__(self, text: str):
        self.content = [{"type": "text", "text": text, "extras": {"signature": "EpcU…"}}]


def _answers_with(monkeypatch, outline: str = "3화 개요.", fail: bool = False) -> dict:
    calls: dict = {"prompts": [], "stage": None}

    class Model:
        def invoke(self, prompt):
            calls["prompts"].append(prompt)
            if fail:
                raise RuntimeError("quota exhausted")
            return _Blocks(outline)

    def fake_get_llm(stage="unknown", **kwargs):
        calls["stage"] = stage
        return Model()

    monkeypatch.setattr(next_episode, "get_llm", fake_get_llm)
    return calls


def _draft(client, direction: str = ""):
    return client.post("/api/episodes/draft-next", json={"direction": direction})


# ==========================================================================
# What comes back
# ==========================================================================


def test_the_next_episode_gets_an_outline(client, loaded, monkeypatch):
    _answers_with(monkeypatch, outline="해리가 비밀의 방의 단서를 쫓는다.")

    response = _draft(client)

    assert response.status_code == 200
    assert response.json() == {
        "episode_number": 3,
        "author_storyline": "해리가 비밀의 방의 단서를 쫓는다.",
    }


def test_nothing_is_saved_until_the_author_adds_it(client, loaded, monkeypatch):
    _answers_with(monkeypatch)

    _draft(client)

    assert len(client.get("/api/episodes").json()) == 2


def test_the_outline_reaches_the_author_as_words_not_blocks(client, loaded, monkeypatch):
    _answers_with(monkeypatch, outline="깨끗한 개요.")

    outline = _draft(client).json()["author_storyline"]

    assert outline == "깨끗한 개요."
    assert "signature" not in outline


def test_it_runs_on_the_planner_stage(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    _draft(client)

    assert calls["stage"] == "planner"


# ==========================================================================
# What the model is shown
# ==========================================================================


def test_it_sees_every_episode_and_which_were_written(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    _draft(client)

    prompt = calls["prompts"][0]
    assert "Episode 1 (written): 해리는 호그와트에 도착해 기숙사를 배정받았다." in prompt
    assert "Episode 2 (planned): 해리가 비밀의 방 소문을 듣는다." in prompt
    assert "episode 3" in prompt


def test_it_sees_the_cast(client, loaded, monkeypatch, harry):
    calls = _answers_with(monkeypatch)

    _draft(client)

    assert harry.name in calls["prompts"][0]


def test_it_sees_where_the_work_is_headed(client, loaded, memory, monkeypatch):
    memory.chronicle.record("story", STORY_SUBJECT_ID, "arc", "1부 입학, 2부 비밀의 방, 3부 결전.",
                            source="author")
    memory.chronicle.record("story", STORY_SUBJECT_ID, "ending", "해리가 볼드모트를 이긴다.",
                            source="author")
    calls = _answers_with(monkeypatch)

    _draft(client)

    assert "1부 입학, 2부 비밀의 방, 3부 결전." in calls["prompts"][0]
    assert "해리가 볼드모트를 이긴다." in calls["prompts"][0]


def test_it_sees_the_open_threads_quietest_first(client, loaded, memory, monkeypatch):
    memory.open_plot_thread("이마의 흉터", "왜 흉터가 아픈가", episode=2)
    memory.open_plot_thread("사라진 지팡이", "누가 지팡이를 가져갔나", episode=1)
    calls = _answers_with(monkeypatch)

    _draft(client)

    prompt = calls["prompts"][0]
    assert "이마의 흉터" in prompt and "사라진 지팡이" in prompt
    assert prompt.index("사라진 지팡이") < prompt.index("이마의 흉터")


def test_the_authors_direction_is_passed_on(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    _draft(client, direction="이번 화는 론과 크게 싸우는 이야기로")

    assert "이번 화는 론과 크게 싸우는 이야기로" in calls["prompts"][0]


def test_without_a_direction_the_model_is_told_to_choose(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch)

    _draft(client)

    assert next_episode.NO_DIRECTION in calls["prompts"][0]


def test_old_episodes_are_cut_short_and_recent_ones_are_not(sample_data):
    project = project_from_sample(sample_data)
    project.episodes = []
    long_line = "가" * 400
    for _ in range(next_episode.RECENT_IN_FULL + 3):
        project.add_episode(long_line)

    text = next_episode.format_story_so_far(project)

    assert text.count(long_line) == next_episode.RECENT_IN_FULL
    assert text.startswith("Episode 1 (planned): " + "가" * 10)


# ==========================================================================
# Where the last chapter ended
# ==========================================================================


class _Closings:
    def __init__(self, number, passage):
        self._closing = (number, passage)

    def get_episode_closing(self):
        return self._closing


class _Memory:
    def __init__(self, number, passage):
        self.structured_store = _Closings(number, passage)


def test_the_last_lines_are_shown_when_they_end_the_queue(loaded):
    loaded.episodes = loaded.episodes[:1]

    closing = episodes_api._closing_of_last(loaded, _Memory(1, "해리는 창밖을 보았다."))

    assert "해리는 창밖을 보았다." in closing


def test_the_last_lines_are_not_shown_when_planned_episodes_follow(loaded):
    # Episode 2 is planned after the last written one: that is where the next
    # episode follows on from, not episode 1's last lines.
    assert episodes_api._closing_of_last(loaded, _Memory(1, "해리는 창밖을 보았다.")) == ""


# ==========================================================================
# Refusals
# ==========================================================================


def test_a_story_with_no_cast_is_refused(client, project_store, monkeypatch):
    project_store.save(Project())
    calls = _answers_with(monkeypatch)

    assert _draft(client).status_code == 409
    assert calls["prompts"] == []


def test_a_failed_call_is_reported_and_saves_nothing(client, loaded, monkeypatch):
    _answers_with(monkeypatch, fail=True)

    response = _draft(client)

    assert response.status_code == 502
    assert "quota exhausted" in response.json()["detail"]
    assert len(client.get("/api/episodes").json()) == 2


# ==========================================================================
# The Story Planner's expansion, fixed while here
# ==========================================================================


def test_the_planner_expansion_is_told_where_the_work_is_headed(loaded, monkeypatch):
    prompts = []

    class Model:
        def invoke(self, prompt):
            prompts.append(prompt)
            return _Blocks("펼친 기획서.")

    monkeypatch.setattr(episodes_api, "get_llm", lambda **kwargs: Model())

    text = episodes_api._expand_summary(
        "해리가 결투를 한다", 3, loaded, "", [], brief="전체 아크: 해리가 성장한다."
    )

    assert "전체 아크: 해리가 성장한다." in prompts[0]
    assert text == "펼친 기획서."
