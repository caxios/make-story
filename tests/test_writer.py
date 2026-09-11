"""The Writer's prompt must carry style, cast and log; its output is bare prose."""

from __future__ import annotations

import pytest

from storyweaver.agents import writer
from storyweaver.models import WritingStyle

PROSE = "The compartment smelled of soot and sugar quills.\n\nRon slid the door shut behind him."

# A whole chapter that arrived wrapped in its own response envelope — a real
# shape seen in saved output, kept here verbatim as a raw string so the
# escaping is the escaping the model actually emitted.
LEAKED = (
    r"""[{'type': 'text', 'text': 'The corridor was cold.\n\n"""
    r"""\"Who\'s there?\" she said.\n\nNo one answered.', """
    r"""'signature': 'aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNpZ25hdHVyZSBibG9iIGxvbmc='}]"""
)


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
    assert "800–1,000 words" in prompt   # a band, in the unit English is measured in
    assert "Diana Wynne Jones" in prompt
    assert "in en." in prompt                 # output language


def test_default_style_is_korean_third_person_limited(
    sample_entries, world, characters, two_character_scene
):
    prompt = writer.build_prompt(two_character_scene, world, characters, sample_entries)

    assert "third-person limited" in prompt
    assert "in ko." in prompt
    # Korean is counted in characters, not words: a model told "1,400 words"
    # of Korean reads that as 어절 and overshoots three- to four-fold.
    assert "1,250–1,550 characters" in prompt
    assert "공백 포함" in prompt


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


# ==========================================================================
# Leaked response envelopes
#
# A structured-output response occasionally reaches us stringified instead of
# unwrapped, taking the whole chapter with it. None of it may survive to a
# reader, and no ordinary prose may be mistaken for it.
# ==========================================================================


def test_a_stringified_content_block_list_is_unwrapped():
    cleaned = writer._clean_prose(LEAKED)

    assert cleaned.startswith("The corridor was cold.")
    assert cleaned.endswith("No one answered.")
    assert "'type'" not in cleaned
    assert "signature" not in cleaned
    assert "\\n" not in cleaned  # the escapes became real paragraph breaks
    assert "\n\n" in cleaned  # and real paragraph breaks are what is left
    assert "Who's there?" in cleaned  # and the escaped apostrophe came back


def test_a_header_line_above_the_leaked_list_does_not_stop_the_unwrap():
    """The model sometimes prints a header before the envelope it leaked."""
    raw = "[Episode 1: 1]\n\n[{'type': 'text', 'text': 'It began at dusk.'}]"

    assert writer._clean_prose(raw) == "It began at dusk."


def test_several_content_blocks_are_joined_as_paragraphs():
    raw = "[{'type': 'text', 'text': 'First.'}, {'type': 'text', 'text': 'Second.'}]"

    assert writer._clean_prose(raw) == "First.\n\nSecond."


def test_ordinary_prose_that_mentions_text_is_left_alone():
    """The unwrapper must not fire on a chapter that merely uses the words."""
    raw = "She read the text again. 'type' was the wrong word for it."

    assert writer._clean_prose(raw) == raw


def test_a_written_scene_is_cleaned_before_it_is_returned(
    scripted_llm, world, characters, two_character_scene, sample_entries
):
    """The unwrapping has to happen on the real path, not just in the helper."""
    llm = scripted_llm(str=lambda prompt, index: LEAKED)

    prose = writer.write_scene(
        two_character_scene, world, characters, entries=sample_entries, llm=llm
    )

    assert prose.startswith("The corridor was cold.")
    assert "signature" not in prose
