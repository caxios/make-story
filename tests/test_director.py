"""Phase 2, Test 1: the Director decomposes an episode storyline into scenes."""

from __future__ import annotations

import pytest

from storyweaver.agents import director
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.models import Episode, StoryBeat


def _output(*drafts: DraftScene) -> DirectorOutput:
    return DirectorOutput(scenes=list(drafts))


def _four_scenes() -> DirectorOutput:
    return _output(
        DraftScene(
            title="The Letter",
            objective="Harry learns he is a wizard.",
            participating_character_ids=["harry-potter"],
            beats=[StoryBeat(description="The letter arrives.")],
            mood="wondrous",
        ),
        DraftScene(
            title="Diagon Alley",
            objective="Harry buys his wand.",
            participating_character_ids=["harry-potter"],
        ),
        DraftScene(
            title="The Express",
            objective="Harry and Hermione meet.",
            participating_character_ids=["harry-potter", "hermione-granger"],
            beats=[StoryBeat(description="Hermione barges in.", mood="brisk")],
        ),
        DraftScene(
            title="The Sorting",
            objective="Harry is sorted, and the hall notices the delay.",
            participating_character_ids=["harry-potter", "hermione-granger"],
            location_id="great-hall",
        ),
    )


def test_prompt_carries_the_storyline_world_and_cast(episode, world, harry, hermione):
    prompt = director.build_prompt(episode, world, [harry, hermione])

    assert episode.author_storyline in prompt
    assert world.overview in prompt
    assert "great-hall" in prompt            # locations offered by id
    assert "harry-potter" in prompt          # characters offered by id
    assert "hermione-granger" in prompt
    assert "wands are required" in prompt.lower() or "wand" in prompt
    assert "3–5 scenes" in prompt            # min/max substituted


def test_decompose_returns_numbered_scenes(episode, world, characters, scripted_llm):
    llm = scripted_llm(DirectorOutput=lambda prompt, index: _four_scenes())

    scenes = director.decompose_episode(episode, world, characters, llm=llm)

    assert 3 <= len(scenes) <= 5
    assert [s.scene_number for s in scenes] == [1, 2, 3, 4]
    assert scenes[0].title == "The Letter"


def test_decomposed_scenes_only_reference_known_ids(episode, world, characters, scripted_llm):
    llm = scripted_llm(DirectorOutput=lambda prompt, index: _four_scenes())

    scenes = director.decompose_episode(episode, world, characters, llm=llm)

    known_characters = set(characters)
    known_locations = {loc.id for loc in world.locations}
    for scene in scenes:
        assert scene.participating_character_ids
        assert set(scene.participating_character_ids) <= known_characters
        assert scene.location_id is None or scene.location_id in known_locations
        assert scene.objective


def test_hallucinated_ids_are_dropped(episode, world, characters, scripted_llm):
    llm = scripted_llm(
        DirectorOutput=lambda prompt, index: _output(
            DraftScene(
                title="Invented",
                objective="Something happens.",
                participating_character_ids=["harry-potter", "dumbledore"],
                location_id="the-moon",
                beats=[
                    StoryBeat(
                        description="A beat.",
                        involved_character_ids=["snape"],
                        location_id="the-moon",
                    )
                ],
            )
        )
    )

    scenes = director.decompose_episode(episode, world, characters, llm=llm)

    assert scenes[0].participating_character_ids == ["harry-potter"]
    assert scenes[0].location_id is None
    assert scenes[0].beats[0].involved_character_ids == []
    assert scenes[0].beats[0].location_id is None


def test_scene_with_no_known_characters_is_skipped(episode, world, characters, scripted_llm):
    llm = scripted_llm(
        DirectorOutput=lambda prompt, index: _output(
            DraftScene(
                title="Ghost scene",
                objective="Nobody we know is here.",
                participating_character_ids=["voldemort"],
            ),
            DraftScene(
                title="Real scene",
                objective="Harry is alone.",
                participating_character_ids=["harry-potter"],
            ),
        )
    )

    scenes = director.decompose_episode(episode, world, characters, llm=llm)

    assert [s.title for s in scenes] == ["Real scene"]
    assert scenes[0].scene_number == 1  # numbering closes the gap


def test_scene_mood_falls_back_to_the_scene_level_mood(episode, world, characters, scripted_llm):
    llm = scripted_llm(
        DirectorOutput=lambda prompt, index: _output(
            DraftScene(
                title="Tense",
                objective="Tension.",
                participating_character_ids=["harry-potter"],
                beats=[
                    StoryBeat(description="Unmoodied beat."),
                    StoryBeat(description="Moodied beat.", mood="comedic"),
                ],
                mood="tense",
            )
        )
    )

    beats = director.decompose_episode(episode, world, characters, llm=llm)[0].beats

    assert beats[0].mood == "tense"
    assert beats[1].mood == "comedic"


def test_direct_episode_attaches_scenes_and_advances_status(
    episode, world, characters, scripted_llm
):
    llm = scripted_llm(DirectorOutput=lambda prompt, index: _four_scenes())

    directed = director.direct_episode(episode, world, characters, llm=llm)

    assert len(directed.scenes) == 4
    assert directed.status == "in_progress"
    assert episode.scenes == []  # the original is untouched


def test_decompose_requires_characters(episode, world, scripted_llm):
    llm = scripted_llm(DirectorOutput=lambda prompt, index: _four_scenes())

    with pytest.raises(ValueError):
        director.decompose_episode(episode, world, {}, llm=llm)


def test_scene_count_bounds_are_configurable(world, characters, scripted_llm):
    llm = scripted_llm(DirectorOutput=lambda prompt, index: _four_scenes())
    episode = Episode(episode_number=2, author_storyline="A quiet interlude.")

    director.decompose_episode(episode, world, characters, llm=llm, min_scenes=2, max_scenes=8)

    assert "2–8 scenes" in llm.last_prompt
