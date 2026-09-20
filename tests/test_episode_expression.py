"""How freely each chapter is written, set per chapter.

A quiet interlude and a climax should not be written at the same pitch, and the
story-wide style cannot say that. These are the per-episode overrides: how much
latitude the prose has, how dense it is, and what this chapter's mood is.

The dial has to move two things at once. The instruction tells the model how far
it may go; the temperature decides how far it actually does. Either alone gives
a model told to be daring that samples timidly, or told to be plain that reaches
for a metaphor anyway — so both are asserted together here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import episode_runner, writer
from storyweaver.api import deps
from storyweaver.models import Episode, WritingStyle
from storyweaver.models.style import (
    DEFAULT_CREATIVITY,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    describe_creativity,
    temperature_for,
)
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
    project.add_episode("조용한 막간.", "막간")
    project_store.save(project)
    return project


# ==========================================================================
# The dial
# ==========================================================================


def test_the_default_is_exactly_what_the_writer_did_before():
    """Adding a dial must not quietly change how existing chapters are written."""
    assert temperature_for(None) == 0.8
    assert temperature_for(DEFAULT_CREATIVITY) == 0.8


def test_the_dial_moves_the_temperature_with_the_instruction():
    restrained, daring = temperature_for(0.0), temperature_for(1.0)

    assert restrained == MIN_TEMPERATURE
    assert daring == MAX_TEMPERATURE
    assert restrained < temperature_for(0.5) < daring
    # And the words move with it.
    assert describe_creativity(0.0) != describe_creativity(1.0)
    assert "Restrained" in describe_creativity(0.0)
    assert "Unrestrained" in describe_creativity(1.0)


def test_the_dial_cannot_be_pushed_off_its_ends():
    """A stored value from anywhere must not produce a wild temperature."""
    assert temperature_for(-3.0) == MIN_TEMPERATURE
    assert temperature_for(9.0) == MAX_TEMPERATURE


# ==========================================================================
# What the Writer is told, and asked at
# ==========================================================================


def test_the_prompt_carries_the_latitude_and_the_mood(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(
        two_character_scene,
        world,
        characters,
        sample_entries,
        creativity=1.0,
        tone_notes="쓸쓸하고 건조하게. 농담은 넣지 말 것.",
    )

    assert "Unrestrained" in prompt
    assert "쓸쓸하고 건조하게" in prompt


def test_a_chapter_with_no_mood_set_says_so_rather_than_leaving_a_hole(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)

    assert writer.NO_TONE in prompt
    assert "{tone_notes}" not in prompt  # the placeholder really was filled


def test_the_writer_is_sampled_at_the_temperature_it_was_told_about(
    sample_entries, world, characters, two_character_scene, monkeypatch
):
    """The half that is easy to forget: the instruction without the sampling."""
    asked: dict = {}

    def fake_get_llm(stage="unknown", temperature=None, **kwargs):
        asked[stage] = temperature

        class Model:
            def invoke(self, prompt, **_):
                return "prose"

        return Model()

    monkeypatch.setattr(writer, "get_llm", fake_get_llm)

    writer.write_scene(
        two_character_scene, world, characters, sample_entries, creativity=0.0
    )
    assert asked["writer"] == MIN_TEMPERATURE

    writer.write_scene(
        two_character_scene, world, characters, sample_entries, creativity=1.0
    )
    assert asked["writer"] == MAX_TEMPERATURE


def test_an_injected_model_is_left_alone(
    sample_entries, world, characters, two_character_scene, scripted_llm
):
    """A caller that brought its own model chose its own temperature too."""
    llm = scripted_llm(str=lambda prompt, index: "prose")

    assert writer.write_scene(
        two_character_scene, world, characters, sample_entries, llm=llm, creativity=1.0
    )


# ==========================================================================
# The pipeline resolves the overrides
# ==========================================================================


def test_an_episode_density_overrides_the_story_one(world, characters):
    story = WritingStyle(prose_density="sparse")
    episode = Episode(episode_number=1, author_storyline="x", prose_density="lush")

    state = episode_runner._initial_state(episode, world, dict(characters), story)

    assert state["writing_style"].prose_density == "lush"
    # And the story's own setting is untouched for every other chapter.
    assert story.prose_density == "sparse"


def test_an_episode_without_an_override_follows_the_story(world, characters):
    story = WritingStyle(prose_density="sparse")
    episode = Episode(episode_number=1, author_storyline="x")

    state = episode_runner._initial_state(episode, world, dict(characters), story)

    assert state["writing_style"].prose_density == "sparse"


# ==========================================================================
# Setting it
# ==========================================================================


def test_the_author_can_set_how_this_chapter_is_written(client, project_store, loaded):
    response = client.put(
        "/api/episodes/2",
        json={
            "creativity": 0.9,
            "prose_density": "lush",
            "tone_notes": "쓸쓸하게, 농담 없이.",
        },
    )

    assert response.status_code == 200
    saved = project_store.load().get_episode(2)
    assert saved.creativity == 0.9
    assert saved.prose_density == "lush"
    assert saved.tone_notes == "쓸쓸하게, 농담 없이."


def test_an_unknown_density_is_refused(client, loaded):
    response = client.put("/api/episodes/2", json={"prose_density": "purple"})

    assert response.status_code == 422
    assert "purple" in response.json()["detail"]


def test_a_creativity_outside_the_dial_is_refused(client, loaded):
    assert client.put("/api/episodes/2", json={"creativity": 4}).status_code == 422
    assert client.put("/api/episodes/2", json={"creativity": -1}).status_code == 422


def test_the_overrides_can_be_taken_back_off(client, project_store, loaded):
    """`null` cannot mean "unset" in a partial update, so this is how."""
    client.put(
        "/api/episodes/2",
        json={"creativity": 0.9, "prose_density": "lush", "tone_notes": "무겁게"},
    )

    client.put("/api/episodes/2", json={"reset_expression": True})

    saved = project_store.load().get_episode(2)
    assert saved.creativity is None
    assert saved.prose_density is None
    assert saved.tone_notes == ""


def test_setting_the_mood_does_not_disturb_the_rest_of_the_episode(
    client, project_store, loaded
):
    before = project_store.load().get_episode(2)

    client.put("/api/episodes/2", json={"tone_notes": "밝게"})

    after = project_store.load().get_episode(2)
    assert after.author_storyline == before.author_storyline
    assert after.status == before.status
    assert after.pacing == before.pacing


def test_the_writing_node_hands_the_episodes_settings_to_the_writer(
    world, characters, two_character_scene, sample_entries
):
    """The wiring between the episode and the Writer, which is easy to drop."""
    passed: dict = {}

    class Recorder:
        def invoke(self, prompt, **_):
            passed["prompt"] = prompt
            return "prose"

    episode = Episode(
        episode_number=1,
        author_storyline="x",
        creativity=1.0,
        tone_notes="쓸쓸하게, 농담 없이.",
    )
    state = {
        "current_scene_index": 0,
        "scenes": [two_character_scene],
        "characters": characters,
        "world_lore": world,
        "writing_style": WritingStyle(),
        "episode": episode,
        "current_entries": [entry.model_dump() for entry in sample_entries],
        "scene_prose_outputs": [],
    }

    episode_runner.write_current_scene(
        state, episode_runner.PipelineModels(writer=Recorder())
    )

    assert "Unrestrained" in passed["prompt"]
    assert "쓸쓸하게, 농담 없이." in passed["prompt"]
