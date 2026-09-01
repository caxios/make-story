"""The Writer's prompt must carry style, cast and log; its output is bare prose."""

from __future__ import annotations

import pytest

from storyweaver.agents import writer
from storyweaver.models import WritingStyle

PROSE = "The compartment smelled of soot and sugar quills.\n\nRon slid the door shut behind him."


def _prose_llm(scripted_llm, text: str = PROSE):
    return scripted_llm(str=lambda prompt, index: text)


def test_prompt_carries_the_cast_sheets(sample_entries, world, characters, two_character_scene):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)

    assert characters["harry-potter"].appearance in prompt
    assert characters["ron-weasley"].speech_style in prompt
    assert "Hermione" not in prompt          # not in this scene
    assert "Anyone sitting there?" in prompt  # the log itself
    assert world.genre in prompt


def test_prompt_reflects_the_writing_style(
    sample_entries, world, characters, two_character_scene
):
    style = WritingStyle(
        perspective="first_person",
        pov_character_id="harry-potter",
        prose_density="lush",
        dialogue_ratio=0.65,
        target_word_count_per_scene=900,
        language="en",
        author_style_notes="Write like Diana Wynne Jones.",
    )

    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries, style)

    assert "first person" in prompt
    assert "harry-potter" in prompt
    assert "Rich and textured" in prompt      # lush density, spelled out
    assert "65%" in prompt                    # dialogue ratio as a percentage
    assert "900 words" in prompt
    assert "Diana Wynne Jones" in prompt
    assert "in en." in prompt                 # output language


def test_default_style_is_korean_third_person_limited(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)

    assert "third-person limited" in prompt
    assert "in ko." in prompt
    assert "1500 words" in prompt


def test_pov_defaults_to_the_scene_opener_when_unset(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)

    opener = two_character_scene.participating_character_ids[0]
    assert f"point-of-view character for this scene is {opener}" in prompt


def test_pov_character_absent_from_the_scene_falls_back(
    sample_entries, world, characters, two_character_scene
):
    style = WritingStyle(pov_character_id="hermione-granger")  # not in this scene

    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries, style)

    assert "point-of-view character for this scene is harry-potter" in prompt


def test_omniscient_perspective_names_no_pov_character(
    sample_entries, world, characters, two_character_scene
):
    style = WritingStyle(perspective="third_person_omniscient")

    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries, style)

    assert "point-of-view character for this scene" not in prompt
    assert "omniscient" in prompt


def test_scene_mood_is_taken_from_the_beats(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)
    assert "Mood: awkward" in prompt


def test_write_scene_returns_stripped_prose(
    sample_entries, world, characters, two_character_scene, scripted_llm
):
    llm = _prose_llm(scripted_llm, f"\n\n{PROSE}\n\n")

    prose = writer.write_scene(
        two_character_scene, world, characters, sample_entries, llm=llm
    )

    assert prose == PROSE
    assert len(llm.calls) == 1


def test_write_scene_falls_back_to_the_rendered_log_on_the_scene(
    sample_entries, world, characters, two_character_scene, scripted_llm
):
    """A Scene carrying only rendered strings is still writable."""
    played = two_character_scene.model_copy(
        update={"interaction_log": [e.render() for e in sample_entries]}
    )
    llm = _prose_llm(scripted_llm)

    prose = writer.write_scene(played, world, characters, llm=llm)

    assert prose == PROSE
    assert "Anyone sitting there?" in llm.last_prompt


def test_write_scene_rejects_an_empty_log(world, characters, two_character_scene, scripted_llm):
    llm = _prose_llm(scripted_llm)

    with pytest.raises(ValueError, match="empty interaction log"):
        writer.write_scene(two_character_scene, world, characters, llm=llm)

    with pytest.raises(ValueError, match="empty interaction log"):
        writer.write_scene(two_character_scene, world, characters, entries=[], llm=llm)
