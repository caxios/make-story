"""Where the work is going: who gets told, and who must not be.

The Director is asked to build a one-line storyline into a whole episode. Doing
that without knowing where the work is headed lets each episode drift off the
arc — plausibly, one chapter at a time, and no single chapter looks wrong. So
the planning stages are told the plan.

Nobody else is. A character who has read the ending stops being surprised by
it; the Lore Checker would flag every chapter for not having arrived there yet;
the Summarizer would record the plan as though the chapter had established it.
`test_story_document.py` guards the same boundary from the wiki's side — this
file guards it from the brief's.
"""

from __future__ import annotations

import pytest

from storyweaver.agents import character as character_agent
from storyweaver.agents import director, lore_checker
from storyweaver.agents.writer import _character_sheets
from storyweaver.memory import summarizer
from storyweaver.memory.chronicle_store import ChronicleStore
from storyweaver.wiki import STORY_SUBJECT_ID, story_brief
from storyweaver.wiki.brief import ARC_CHARS, LOGLINE_CHARS

ARC = "1부 만남과 은폐, 2부 사념세계 진입, 3부 두 세계의 경계가 무너짐"
ENDING = "동혁이 사념세계에 남고 시월이 현세계로 건너온다"
LOGLINE = "평범한 학생이 구미호와 얽힌다"


@pytest.fixture
def chronicle(tmp_path) -> ChronicleStore:
    return ChronicleStore(tmp_path / "state")


@pytest.fixture
def planned(chronicle) -> ChronicleStore:
    for key, value in (("logline", LOGLINE), ("arc", ARC), ("ending", ENDING)):
        chronicle.record("story", STORY_SUBJECT_ID, key, value, source="author")
    return chronicle


# ==========================================================================
# The digest itself
# ==========================================================================


def test_a_story_with_no_plan_has_no_brief(chronicle):
    """The ordinary case for a project that was not started from a concept."""
    assert story_brief(chronicle) == ""


def test_a_project_with_no_chronicle_at_all_is_not_an_error(chronicle):
    assert story_brief(None) == ""


def test_the_brief_carries_the_arc_and_the_ending(planned):
    brief = story_brief(planned)

    assert ARC in brief
    assert ENDING in brief
    assert LOGLINE in brief


def test_the_brief_leaves_out_sections_the_author_has_not_written(chronicle):
    """A half-written plan is normal mid-session; it must not render as blanks."""
    chronicle.record("story", STORY_SUBJECT_ID, "arc", ARC, source="author")

    brief = story_brief(chronicle)

    assert brief == f"전체 아크: {ARC}"


def test_the_brief_does_not_carry_the_premise_or_the_episode_outline(planned):
    """Only direction. The premise is why the author is writing it, and the
    outline is the very thing the planner is being asked to produce."""
    planned.record("story", STORY_SUBJECT_ID, "premise", "성장물을 쓰고 싶었다", source="author")
    planned.record("story", STORY_SUBJECT_ID, "episodes", "1화 — 시월이 찾아온다", source="author")

    brief = story_brief(planned)

    assert "성장물을 쓰고 싶었다" not in brief
    assert "시월이 찾아온다" not in brief


def test_a_long_arc_is_trimmed_rather_than_crowding_out_the_episode(chronicle):
    """A fifty-episode arc would otherwise dwarf the chapter being planned."""
    chronicle.record("story", STORY_SUBJECT_ID, "arc", "가" * 5000, source="author")

    brief = story_brief(chronicle)

    assert len(brief) < ARC_CHARS + LOGLINE_CHARS
    assert brief.endswith("…")


def test_a_retracted_plan_is_not_in_the_brief(chronicle):
    """The fold decides the current value; the brief must use it, not the chain."""
    chronicle.record("story", STORY_SUBJECT_ID, "ending", ENDING, source="author")
    chronicle.record(
        "story", STORY_SUBJECT_ID, "ending", "결말을 다시 짬", source="author"
    )

    assert ENDING not in story_brief(chronicle)


# ==========================================================================
# Who is told
# ==========================================================================


def test_the_director_is_told_where_the_work_is_going(episode, world, characters, planned):
    prompt = director.build_prompt(
        episode, world, characters, story_brief=story_brief(planned)
    )

    assert ARC in prompt
    assert ENDING in prompt


def test_the_director_is_told_plainly_when_there_is_no_plan(episode, world, characters):
    """A raw `{story_brief}` left empty reads as a section the model must fill."""
    prompt = director.build_prompt(episode, world, characters)

    assert director.NO_STORY_BRIEF in prompt


def test_the_director_is_told_the_plan_is_direction_not_material(
    episode, world, characters, planned
):
    """Knowing the ending is exactly how an episode starts foreshadowing it."""
    prompt = director.build_prompt(
        episode, world, characters, story_brief=story_brief(planned)
    )

    assert "The characters have not read this." in prompt


# ==========================================================================
# Who is not
# ==========================================================================


def test_a_character_is_not_told_how_the_story_ends(
    harry, two_character_scene, world, characters, planned
):
    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters
    )

    assert ENDING not in prompt
    assert ARC not in prompt


def test_the_writer_is_not_told_how_the_story_ends(harry, ron, characters, planned):
    sheets = _character_sheets(characters, [harry.id, ron.id], harry.id)

    assert ENDING not in sheets
    assert ARC not in sheets


def test_the_lore_checker_does_not_judge_a_scene_against_the_plan(
    two_character_scene, world, characters, planned
):
    """It would flag every chapter for not having reached the ending yet."""
    prompt = lore_checker.build_prompt([], world, characters, scene=two_character_scene)

    assert ENDING not in prompt
    assert ARC not in prompt


def test_the_summarizer_does_not_record_the_plan_as_something_that_happened(
    episode, world, characters, planned
):
    """Its output folds into the chronicle, so a plan reaching it would come
    back as established fact about a chapter that never showed it."""
    prompt = summarizer.build_prompt(episode, world, characters)

    assert ENDING not in prompt
    assert ARC not in prompt
