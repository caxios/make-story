"""The identity fields have to actually reach the prompts.

`age`, `gender`, `role` and `backstory` sit on every `CharacterProfile` and,
until now, were read by nothing: a seventeen-year-old could address a
forty-seven-year-old in 반말 because no prompt had ever mentioned either age.
Korean prose shows a relationship mostly through speech level, so this is not
a detail the model can be left to guess.

The Writer needs them as much as the Character Agent does — it is the one
setting the final words down.
"""

from __future__ import annotations

import pytest

from storyweaver.agents import character as character_agent
from storyweaver.agents import context
from storyweaver.agents.writer import _character_sheets


@pytest.fixture
def scene(two_character_scene):
    return two_character_scene


def _prompt(character, scene, world, characters) -> str:
    return character_agent.build_system_prompt(character, scene, world, characters)


# ==========================================================================
# The character's own prompt
# ==========================================================================


def test_age_reaches_the_prompt(harry, scene, world, characters):
    assert harry.age is not None  # the fixture would make this test vacuous
    assert f"{harry.age}세" in _prompt(harry, scene, world, characters)


def test_gender_reaches_the_prompt(harry, scene, world, characters):
    assert harry.gender in _prompt(harry, scene, world, characters)


def test_backstory_reaches_the_prompt(harry, scene, world, characters):
    assert harry.backstory
    assert harry.backstory in _prompt(harry, scene, world, characters)


def test_the_role_reaches_the_prompt(harry, scene, world, characters):
    harry = harry.model_copy(update={"role": "주인공"})

    assert "주인공" in _prompt(harry, scene, world, {**characters, harry.id: harry})


def test_an_english_role_is_shown_in_the_authors_own_vocabulary(
    harry, scene, world, characters
):
    """A project holds both; one prompt should not carry two vocabularies."""
    harry = harry.model_copy(update={"role": "protagonist"})

    prompt = _prompt(harry, scene, world, {**characters, harry.id: harry})

    assert "주인공" in prompt
    assert "protagonist" not in prompt


def test_a_role_nobody_has_heard_of_is_passed_through_unchanged(
    harry, scene, world, characters
):
    """The role is free text, so an invented one is not an error."""
    harry = harry.model_copy(update={"role": "몰락한 예언자"})

    assert "몰락한 예언자" in _prompt(harry, scene, world, {**characters, harry.id: harry})


def test_the_prompt_says_how_to_choose_between_존댓말_and_반말(
    harry, scene, world, characters
):
    prompt = _prompt(harry, scene, world, characters)

    assert "존댓말" in prompt
    assert "반말" in prompt


def test_closeness_outranks_age_in_the_formality_rule(harry, scene, world, characters):
    """Age alone would put two unacquainted peers on 반말, which is wrong."""
    prompt = _prompt(harry, scene, world, characters)

    assert "closeness" in prompt
    assert "peers you do not know well" in prompt


def test_a_character_with_none_of_these_fields_still_renders(
    harry, scene, world, characters
):
    """An empty identity line must not leave a hole where the character was."""
    bare = harry.model_copy(update={"age": None, "gender": None, "role": "", "backstory": ""})

    prompt = _prompt(bare, scene, world, {**characters, bare.id: bare})

    assert prompt.startswith(f"You are {bare.name}.")
    # No stray "None", and no run of blank lines where the fields would be.
    assert "None" not in prompt.split("## Your Identity")[0]
    assert "\n\n\n" not in prompt


def test_the_identity_line_reads_as_one_line(harry, scene, world, characters):
    harry = harry.model_copy(update={"role": "주인공"})

    prompt = _prompt(harry, scene, world, {**characters, harry.id: harry})
    identity = prompt.splitlines()[1]

    assert identity == f"주인공 · {harry.age}세 · {harry.gender}"


# ==========================================================================
# The Writer's character sheets
# ==========================================================================


def test_the_writer_is_told_everyones_age(harry, ron, characters):
    sheets = _character_sheets(characters, [harry.id, ron.id], harry.id)

    assert f"Age: {harry.age}" in sheets
    assert f"Age: {ron.age}" in sheets


def test_the_writer_is_told_the_relationships_in_the_scene(harry, ron, characters):
    """Two people's history with each other is what the prose is made of."""
    sheets = _character_sheets(characters, [harry.id, ron.id], harry.id)

    assert "Relationships with others in this scene" in sheets
    assert ron.name in sheets


def test_the_writer_is_not_told_about_people_who_are_not_there(
    harry, hermione, ron, characters
):
    """Harry's relationship with Hermione is none of this scene's business."""
    sheets = _character_sheets(characters, [harry.id, ron.id], harry.id)

    assert hermione.name not in sheets


def test_a_sheet_with_no_relationships_says_nothing_rather_than_none(
    harry, ron, characters
):
    stranger = harry.model_copy(update={"relationships": []})
    cast = {**characters, stranger.id: stranger}

    sheets = _character_sheets(cast, [stranger.id], stranger.id)

    assert "Relationships with others in this scene" not in sheets
    assert context.NONE_PLACEHOLDER not in sheets


def test_missing_fields_are_left_out_rather_than_printed_empty(harry, characters):
    """"Age: None" would be worse than no line at all."""
    bare = harry.model_copy(update={"age": None, "gender": None, "role": ""})

    sheets = _character_sheets({**characters, bare.id: bare}, [bare.id], bare.id)

    assert "Age:" not in sheets
    assert "Gender:" not in sheets
    assert "Story role:" not in sheets
    assert bare.appearance in sheets  # the rest of the sheet is intact


def test_a_field_the_author_left_blank_is_left_out_of_the_sheet(harry, characters):
    """"Appearance:" with nothing after it says the field exists and is empty."""
    faceless = harry.model_copy(update={"appearance": "   "})

    sheets = _character_sheets({**characters, faceless.id: faceless}, [faceless.id], None)

    assert "Appearance:" not in sheets
    assert faceless.personality_summary in sheets  # the rest still lands


def test_an_english_role_is_translated_for_the_writer_too(harry, characters):
    harry = harry.model_copy(update={"role": "supporting"})

    sheets = _character_sheets({**characters, harry.id: harry}, [harry.id], harry.id)

    assert "Story role: 조연" in sheets
    assert "supporting" not in sheets


# ==========================================================================
# The vocabulary itself
# ==========================================================================


def test_every_role_the_workshop_offers_survives_a_round_trip():
    """A Korean role the author picked must not be mangled on the way in."""
    for korean in context.ROLE_LABELS.values():
        assert context.describe_role(korean) == korean


def test_the_role_lookup_ignores_case_and_stray_spaces():
    assert context.describe_role("  Protagonist  ") == "주인공"
