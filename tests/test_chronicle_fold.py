"""Folding a chronicle back into the models the agents read.

The rule is that the last live entry wins, and the consequence is that the
story is written from who these people have become rather than from the sheet
the author filled in before it started.

The failure this guards against is quiet. If the prose follows the fold and the
Lore Checker reads the original, every scene where a character behaves as they
now are is reported as a setting violation — and the pipeline re-runs correct
writing to "fix" it, burning real quota to make the chapter worse.
"""

from __future__ import annotations

import pytest

from storyweaver.agents import character as character_agent
from storyweaver.agents import context, lore_checker
from storyweaver.agents.writer import _character_sheets
from storyweaver.memory.chronicle_store import ChronicleStore
from storyweaver.models import CharacterProfile, Location, Relationship, Rule, WorldLore
from storyweaver.wiki import (
    fold_cast,
    fold_character,
    fold_world,
    relationship_section_key,
)


@pytest.fixture
def store(tmp_path) -> ChronicleStore:
    return ChronicleStore(tmp_path / "state")


def _hair_was_cut(store: ChronicleStore, character_id: str = "harry-potter") -> None:
    store.record(
        "character", character_id, "appearance", "머리를 짧게 깎았다",
        source="episode", episode_number=1, reason="싸움 중 잘림",
    )


# ==========================================================================
# The rule
# ==========================================================================


def test_a_section_with_no_history_keeps_what_the_author_wrote(store, harry):
    """A project that has recorded nothing folds to exactly what it was."""
    assert fold_character(store, harry) == harry


def test_the_last_entry_wins(store, harry):
    store.record("character", harry.id, "appearance", "첫 번째 변화",
                 source="episode", episode_number=1, reason="a")
    store.record("character", harry.id, "appearance", "두 번째 변화",
                 source="episode", episode_number=3, reason="b")

    assert fold_character(store, harry).appearance == "두 번째 변화"


def test_a_retracted_entry_falls_back_to_the_one_before(store, harry):
    """This is how an author undoes a change the summarizer invented."""
    store.record("character", harry.id, "appearance", "좋은 기록",
                 source="episode", episode_number=1, reason="a")
    wrong = store.record("character", harry.id, "appearance", "지어낸 기록",
                         source="episode", episode_number=2, reason="b")

    store.retract(wrong.entry_id)

    assert fold_character(store, harry).appearance == "좋은 기록"


def test_the_authors_later_edit_wins_over_an_earlier_episode(store, harry):
    """The chronicle is one timeline; who wrote an entry does not rank it."""
    store.record("character", harry.id, "appearance", "1화가 남긴 것",
                 source="episode", episode_number=1, reason="a")
    store.record("character", harry.id, "appearance", "작가가 나중에 고친 것")

    assert fold_character(store, harry).appearance == "작가가 나중에 고친 것"


def test_folding_does_not_touch_what_is_stored(store, harry):
    original = harry.appearance
    _hair_was_cut(store, harry.id)

    fold_character(store, harry)

    assert harry.appearance == original
    assert len(store.chain("character", harry.id, "appearance")) == 1


def test_a_list_field_comes_back_as_a_list(store, harry):
    store.record("character", harry.id, "goals", "볼드모트를 막는다\n친구들을 지킨다",
                 source="episode", episode_number=2, reason="각오를 다짐")

    assert fold_character(store, harry).goals == ["볼드모트를 막는다", "친구들을 지킨다"]


def test_a_log_section_is_not_folded_into_anything(store, harry):
    """작중 행적 is history, not a current value; it has no field to land in."""
    store.record("character", harry.id, "deeds", "무언가 했다.",
                 source="episode", episode_number=1)

    assert fold_character(store, harry) == harry


# ==========================================================================
# Relationships
# ==========================================================================


def test_a_relationship_moves_with_its_chain(store, harry, ron):
    store.record(
        "character", harry.id, relationship_section_key(ron.id),
        "신뢰하는 동료 — 사념세계에서 감싸 주는 것을 봄",
        source="episode", episode_number=3, reason="그 장면",
    )

    folded = fold_character(store, harry)
    relationship = next(r for r in folded.relationships if r.target_character_id == ron.id)

    assert relationship.type == "신뢰하는 동료"
    assert relationship.description == "사념세계에서 감싸 주는 것을 봄"


def test_a_relationship_that_never_moved_is_left_alone(store, harry):
    before = list(harry.relationships)

    store.record("character", harry.id, "appearance", "다른 것이 바뀜",
                 source="episode", episode_number=1, reason="a")

    assert fold_character(store, harry).relationships == before


def test_a_new_relationship_can_appear_from_the_chronicle(store, harry):
    stranger = harry.model_copy(update={"relationships": []})

    store.record("character", stranger.id, relationship_section_key("낯선이"), "처음 만난 사이",
                 source="episode", episode_number=1, reason="만남")

    folded = fold_character(store, stranger)
    assert [r.target_character_id for r in folded.relationships] == ["낯선이"]


# ==========================================================================
# The world
# ==========================================================================


def test_a_place_can_break_and_come_back(store):
    gate = Location(id="gate", name="차원게이트", description="빛나는 문.")
    world = WorldLore(title="w", genre="fantasy", tone="dark", overview="o", locations=[gate])

    store.record("location", "gate", "state", "고장",
                 source="episode", episode_number=4, reason="공격", kind="removed")
    assert fold_world(store, world).locations[0].status == "고장"

    store.record("location", "gate", "state", "수리됨",
                 source="episode", episode_number=6, reason="고침", kind="restored")
    assert fold_world(store, world).locations[0].status == "수리됨"


def test_an_abolished_rule_stops_being_enforced(store):
    """The Lore Checker enforces every rule it is handed — including repealed ones."""
    rule = Rule(id="secrecy", category="society", statement="마법은 비밀이다.")
    world = WorldLore(title="w", genre="fantasy", tone="dark", overview="o", rules=[rule])

    store.record("rule", "secrecy", "active", "폐지됨",
                 source="episode", episode_number=5, reason="마법이 공개됨", kind="removed")

    assert fold_world(store, world).rules == []


def test_an_abolished_rule_keeps_its_history(store):
    """"It used to hold" is exactly what the chronicle is for."""
    rule = Rule(id="secrecy", category="society", statement="마법은 비밀이다.")
    world = WorldLore(title="w", genre="fantasy", tone="dark", overview="o", rules=[rule])
    store.record("rule", "secrecy", "active", "폐지됨",
                 source="episode", episode_number=5, reason="공개됨", kind="removed")

    fold_world(store, world)

    assert len(store.chain("rule", "secrecy", "active")) == 1


def test_a_rule_that_was_never_touched_is_still_enforced(store):
    rule = Rule(id="secrecy", category="society", statement="마법은 비밀이다.")
    world = WorldLore(title="w", genre="fantasy", tone="dark", overview="o", rules=[rule])

    assert fold_world(store, world).rules == [rule]


def test_the_worlds_own_sections_fold(store):
    world = WorldLore(title="w", genre="fantasy", tone="밝음", overview="처음 설명")

    store.record("world", "world", "overview", "달라진 설명",
                 source="episode", episode_number=2, reason="드러남")
    store.record("world", "world", "tone", "어두움",
                 source="episode", episode_number=3, reason="전쟁이 남")

    folded = fold_world(store, world)
    assert folded.overview == "달라진 설명"
    assert folded.tone == "어두움"


# ==========================================================================
# What the agents are actually shown
# ==========================================================================


def test_the_writer_describes_the_character_as_they_are_now(store, harry, ron, characters):
    """The acceptance test for this whole phase: the haircut must not grow back."""
    _hair_was_cut(store, harry.id)
    folded = fold_cast(store, dict(characters))

    sheets = _character_sheets(folded, [harry.id, ron.id], harry.id)

    assert "머리를 짧게 깎았다" in sheets
    assert harry.appearance not in sheets


def test_the_character_agent_plays_the_character_as_they_are_now(
    store, harry, two_character_scene, world, characters
):
    store.record("character", harry.id, "speech", "짧고 무뚝뚝하게 말한다",
                 source="episode", episode_number=4, reason="말수가 줄어듦")
    folded = fold_cast(store, dict(characters))

    prompt = character_agent.build_system_prompt(
        folded[harry.id], two_character_scene, world, folded
    )

    assert "짧고 무뚝뚝하게 말한다" in prompt
    assert harry.speech_style not in prompt


def test_the_lore_checker_judges_against_who_they_are_now(
    store, harry, two_character_scene, world, characters
):
    """The quiet failure: a changed character reported as a setting violation.

    If this regresses, correct prose is flagged every scene and the pipeline
    re-runs it — spending real quota to undo the story's own development.
    """
    store.record("character", harry.id, "speech", "짧고 무뚝뚝하게 말한다",
                 source="episode", episode_number=4, reason="말수가 줄어듦")
    folded = fold_cast(store, dict(characters))

    prompt = lore_checker.build_prompt([], world, folded, scene=two_character_scene)

    assert "짧고 무뚝뚝하게 말한다" in prompt
    assert harry.speech_style not in prompt


def test_the_lore_checker_is_not_handed_a_repealed_rule(
    store, two_character_scene, characters
):
    world = WorldLore(
        title="w", genre="fantasy", tone="dark", overview="o",
        rules=[
            Rule(id="secrecy", category="society", statement="마법은 비밀이다."),
            Rule(id="wands", category="magic", statement="지팡이가 있어야 마법을 쓴다."),
        ],
    )
    store.record("rule", "secrecy", "active", "폐지됨",
                 source="episode", episode_number=5, reason="공개됨", kind="removed")

    prompt = lore_checker.build_prompt(
        [], fold_world(store, world), characters, scene=two_character_scene
    )

    assert "마법은 비밀이다" not in prompt
    assert "지팡이가 있어야" in prompt


# ==========================================================================
# Settings that reached no prompt at all
# ==========================================================================


def test_factions_reach_the_world_summary():
    """An author could write a faction and the model would never hear of it."""
    world = WorldLore(
        title="w", genre="fantasy", tone="dark", overview="o",
        factions=["불사조 기사단", "죽음을 먹는 자들"],
    )

    summary = context.format_world_summary(world)

    assert "불사조 기사단" in summary
    assert "죽음을 먹는 자들" in summary


def test_additional_lore_reaches_the_world_summary():
    world = WorldLore(
        title="w", genre="fantasy", tone="dark", overview="o",
        additional_lore={"화폐": "갈레온, 시클, 크넛."},
    )

    summary = context.format_world_summary(world)

    assert "화폐" in summary and "갈레온" in summary


def test_an_empty_lore_entry_is_not_shown():
    world = WorldLore(
        title="w", genre="fantasy", tone="dark", overview="o",
        additional_lore={"빈칸": "   "},
    )

    assert "빈칸" not in context.format_world_summary(world)


def test_a_world_with_neither_reads_as_it_always_did(world):
    summary = context.format_world_summary(world)

    assert summary.startswith(world.title)
    assert world.overview in summary
