"""The author approves the plan before a word of the chapter is written.

Drafting a plan costs one Director call; writing the chapter costs dozens. So
the plan exists to be looked at, corrected, and signed off — and what gets
written has to be exactly what was signed off, not a fresh idea from the model.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import director
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.api import deps, generation
from storyweaver.models import StoryBeat
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
    project.add_episode("해리가 비밀의 방 입구를 찾아 기숙사를 몰래 빠져나온다.", "비밀의 방")
    project_store.save(project)
    return project


@pytest.fixture
def three_scenes(monkeypatch, loaded):
    """The Director, stubbed to lay out three scenes with the real cast."""
    cast = [character.id for character in loaded.characters[:2]]

    def plan(episode, world, characters, **kwargs):
        return [
            DraftScene(
                title=title,
                objective=f"{title}을 해낸다",
                participating_character_ids=cast,
                beats=[StoryBeat(description=f"{title}의 비트")],
            )
            for title in ("기숙사의 밤", "복도의 인기척", "2층 화장실")
        ]

    def decompose(episode, world, characters, llm=None, **kwargs):
        return director._to_scenes(
            plan(episode, world, characters), world, director.context.as_character_map(characters)
        )

    monkeypatch.setattr(director, "decompose_episode", decompose)
    from storyweaver.api import episodes as episodes_api

    monkeypatch.setattr(episodes_api.director, "decompose_episode", decompose)
    return cast


# ==========================================================================
# Drafting
# ==========================================================================


def test_planning_writes_scenes_without_writing_prose(
    client, project_store, loaded, three_scenes
):
    response = client.post("/api/episodes/2/plan")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "planned"
    assert [scene["title"] for scene in body["scenes"]] == [
        "기숙사의 밤",
        "복도의 인기척",
        "2층 화장실",
    ]
    # The plan is saved, and not one word of the chapter is.
    saved = project_store.load().get_episode(2)
    assert saved.status == "planned"
    assert len(saved.scenes) == 3
    assert saved.final_text == ""
    assert all(scene.prose == "" for scene in saved.scenes)


def test_the_plan_reports_the_length_it_is_budgeted_for(client, loaded, three_scenes):
    """Whether three scenes can carry a 회차 is the author's call to make."""
    body = client.post("/api/episodes/2/plan").json()

    assert body["unit"] == "characters"  # the project writes in Korean
    assert body["target_per_scene"] == 1400
    assert body["target_total"] == 4200
    assert (body["standard_low"], body["standard_high"]) == (4500, 5500)


def test_an_episode_with_no_storyline_cannot_be_planned(client, project_store, loaded):
    loaded.update_episode(loaded.get_episode(2).model_copy(update={"author_storyline": "  "}))
    project_store.save(loaded)

    response = client.post("/api/episodes/2/plan")

    assert response.status_code == 409
    assert "storyline" in response.json()["detail"]


def test_a_director_that_returns_nothing_is_reported_not_saved(
    client, project_store, loaded, monkeypatch
):
    """Episode 5 was planned as a single scene; silence is worse than that."""
    from storyweaver.api import episodes as episodes_api

    monkeypatch.setattr(episodes_api.director, "decompose_episode", lambda *a, **k: [])

    response = client.post("/api/episodes/2/plan")

    assert response.status_code == 502
    assert project_store.load().get_episode(2).status == "queued"


# ==========================================================================
# Editing
# ==========================================================================


def test_the_author_can_rewrite_the_plan(client, project_store, loaded, three_scenes):
    client.post("/api/episodes/2/plan")
    cast = [loaded.characters[0].id]

    response = client.put(
        "/api/episodes/2/plan",
        json={
            "scenes": [
                {
                    "title": "작가가 고친 장면",
                    "objective": "작가가 정한 목표",
                    "participating_character_ids": cast,
                    "beats": [{"description": "작가가 적은 비트"}],
                },
                {
                    "title": "두 번째 장면",
                    "objective": "두 번째 목표",
                    "participating_character_ids": cast,
                },
            ]
        },
    )

    assert response.status_code == 200
    saved = project_store.load().get_episode(2)
    assert [scene.title for scene in saved.scenes] == ["작가가 고친 장면", "두 번째 장면"]
    # Renumbered from one, whatever the author sent.
    assert [scene.scene_number for scene in saved.scenes] == [1, 2]
    assert saved.scenes[0].beats[0].description == "작가가 적은 비트"


def test_a_plan_naming_someone_outside_the_cast_is_refused(client, loaded, three_scenes):
    """Silently dropping them would leave a scene missing a character."""
    response = client.put(
        "/api/episodes/2/plan",
        json={
            "scenes": [
                {
                    "title": "장면",
                    "objective": "목표",
                    "participating_character_ids": ["there-is-no-such-character"],
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "there-is-no-such-character" in response.json()["detail"]


def test_a_plan_needs_at_least_one_scene_with_someone_in_it(client, loaded):
    assert client.put("/api/episodes/2/plan", json={"scenes": []}).status_code == 422


def test_changing_the_storyline_throws_the_plan_away(
    client, project_store, loaded, three_scenes
):
    """A plan drawn for another storyline is not a plan for this one."""
    client.post("/api/episodes/2/plan")

    client.put("/api/episodes/2", json={"author_storyline": "완전히 다른 이야기."})

    saved = project_store.load().get_episode(2)
    assert saved.status == "queued"
    assert saved.scenes == []


def test_editing_the_title_leaves_the_plan_alone(client, project_store, loaded, three_scenes):
    client.post("/api/episodes/2/plan")

    client.put("/api/episodes/2", json={"title": "새 제목"})

    saved = project_store.load().get_episode(2)
    assert saved.status == "planned"
    assert len(saved.scenes) == 3


# ==========================================================================
# Writing what was approved
# ==========================================================================


def test_an_approved_plan_is_written_as_approved(
    client, project_store, loaded, three_scenes, monkeypatch
):
    """The Director must not get a second opinion after the author signed off."""
    client.post("/api/episodes/2/plan")
    client.put(
        "/api/episodes/2/plan",
        json={
            "scenes": [
                {
                    "title": "작가가 승인한 단 하나의 장면",
                    "objective": "이대로 쓰여야 한다",
                    "participating_character_ids": [loaded.characters[0].id],
                }
            ]
        },
    )

    seen: dict = {}

    def run(episode, world, characters, **kwargs):
        seen["plan"] = kwargs.get("plan")
        return episode.model_copy(update={"status": "completed", "final_text": "본문"}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", run)

    client.get("/api/generation/stream/2")
    while generation.running_generations():
        pass

    assert seen["plan"] is not None
    assert [scene.title for scene in seen["plan"]] == ["작가가 승인한 단 하나의 장면"]


def test_an_unplanned_episode_still_gets_the_director(
    client, loaded, monkeypatch
):
    """Nothing forces the plan step on a caller that does not want it."""
    seen: dict = {}

    def run(episode, world, characters, **kwargs):
        seen["plan"] = kwargs.get("plan")
        return episode.model_copy(update={"status": "completed", "final_text": "본문"}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", run)

    client.get("/api/generation/stream/2")
    while generation.running_generations():
        pass

    assert seen["plan"] is None


def test_the_pipeline_starts_at_the_plan_rather_than_the_director(world, characters):
    """The mechanism underneath: a seeded plan routes the graph past planning."""
    from storyweaver.agents import episode_runner
    from storyweaver.models import Episode, Scene

    plan = [
        Scene(
            scene_number=1,
            title="승인된 장면",
            participating_character_ids=[next(iter(characters))],
            objective="쓰인다",
        )
    ]

    state = episode_runner._initial_state(
        Episode(episode_number=2, author_storyline="x"),
        world,
        dict(characters),
        None,
        None,
        plan,
    )

    # `entry_point` is what chooses; "resume" is the branch that skips planning.
    assert episode_runner.entry_point(state) == "resume"
    assert [scene.title for scene in state["scenes"]] == ["승인된 장면"]
    assert state["current_scene_index"] == 0


def test_a_checkpoint_outranks_a_plan(world, characters):
    """A part-written run is past planning; its scenes carry prose."""
    from storyweaver.agents import episode_runner
    from storyweaver.agents.checkpoint import EpisodeCheckpoint
    from storyweaver.models import Episode, Scene

    written = Scene(
        scene_number=1,
        title="이미 쓴 장면",
        participating_character_ids=[next(iter(characters))],
        objective="끝났다",
    )
    checkpoint = EpisodeCheckpoint(
        episode_number=2,
        author_storyline="x",
        scenes=[written],
        scene_prose_outputs=["써 둔 본문"],
        current_scene_index=1,
    )
    stale_plan = [written.model_copy(update={"title": "낡은 기획"})]

    state = episode_runner._initial_state(
        Episode(episode_number=2, author_storyline="x"),
        world,
        dict(characters),
        None,
        checkpoint,
        stale_plan,
    )

    assert [scene.title for scene in state["scenes"]] == ["이미 쓴 장면"]
    assert state["scene_prose_outputs"] == ["써 둔 본문"]
