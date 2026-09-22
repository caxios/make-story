"""Turning a finished episode into history.

The summarizer already ran once per episode; this is about what it is now asked
for and what becomes of the answer. Two things decide whether the chronicle is
trustworthy: an unfounded change must never reach it, because the chronicle
overrides the author's own setting for every episode after it; and rewriting a
chapter must replace that chapter's history rather than adding a second copy.
"""

from __future__ import annotations

import pytest

from storyweaver.memory.manager import MemoryManager
from storyweaver.memory.summarizer import (
    CharacterStateUpdate,
    Deed,
    EpisodeMemory,
    FieldChange,
    _sanitise,
)
from storyweaver.models import Episode, Relationship
from storyweaver.wiki import relationship_section_key


@pytest.fixture
def manager(tmp_path, monkeypatch) -> MemoryManager:
    """A manager whose vector store is inert — this is about the chronicle."""

    class Inert:
        def add_episode_summary(self, *a, **k):
            return None

        def add_interaction_records(self, records):
            return len(list(records))

        def add_lore(self, *a, **k):
            return None

        def seed_world_lore(self, world):
            return 0

    return MemoryManager(vector_store=Inert(), data_dir=tmp_path / "state")


def _record(manager: MemoryManager, episode: Episode, memory: EpisodeMemory):
    """Record with the review gate off — these tests are about the recording.

    The gate itself has its own file; here it would only mean asserting on
    `pending()` instead of on the chain in every single test.
    """
    return manager.record_episode_completion(episode, memory, review=False)


def _episode(number: int = 1, text: str = "마지막 문단입니다.") -> Episode:
    return Episode(
        episode_number=number,
        title=f"{number}화",
        author_storyline="줄거리",
        final_text=text,
        status="completed",
    )


def _memory(**overrides) -> EpisodeMemory:
    base = {"summary": "이 화의 요약."}
    return EpisodeMemory.model_validate({**base, **overrides})


# ==========================================================================
# What becomes history
# ==========================================================================


def test_a_change_becomes_an_entry_on_its_own_chain(manager):
    _record(
        manager,
        _episode(1),
        _memory(changes=[
            FieldChange(
                subject_id="박동혁", section_key="appearance",
                value="한쪽 눈을 덮은 앞머리",
                reason="시월과의 실랑이 중 머리카락이 잘림",
            )
        ]),
    )

    chain = manager.chronicle.chain("character", "박동혁", "appearance")

    assert len(chain) == 1
    assert chain[0].value == "한쪽 눈을 덮은 앞머리"
    assert chain[0].episode_number == 1
    assert chain[0].source == "episode"
    assert chain[0].reason == "시월과의 실랑이 중 머리카락이 잘림"


def test_a_second_change_carries_the_first_as_its_previous(manager):
    """The chain is what the fold builds on, so it has to join up."""
    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="앞머리가 잘림", reason="싸움 중")]),
    )
    _record(
        manager,
        _episode(2),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="짧게 친 머리", reason="직접 자름")]),
    )

    chain = manager.chronicle.chain("character", "박동혁", "appearance")

    assert [e.value for e in chain] == ["앞머리가 잘림", "짧게 친 머리"]
    assert chain[1].previous == "앞머리가 잘림"


def test_the_summarizers_own_previous_does_not_override_the_chain(manager):
    """It is reading the chapter, not the history; the chain is the truth."""
    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="긴 머리", reason="기름")]),
    )
    _record(
        manager,
        _episode(2),
        _memory(changes=[FieldChange(
            subject_id="박동혁", section_key="appearance",
            previous="완전히 다른 것을 기억하고 있음",
            value="짧은 머리", reason="잘림",
        )]),
    )

    assert manager.chronicle.chain("character", "박동혁", "appearance")[1].previous == "긴 머리"


def test_a_setting_that_did_not_actually_move_is_not_recorded(manager):
    """Otherwise every episode writes a "no change" line for everyone present."""
    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="단정한 단발", reason="처음 등장")]),
    )
    _record(
        manager,
        _episode(2),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="단정한 단발", reason="여전히 그러함")]),
    )

    assert len(manager.chronicle.chain("character", "박동혁", "appearance")) == 1


def test_a_place_can_break_and_be_repaired(manager):
    """유적 파괴, 게이트 고장, 그리고 수리 — state goes and comes back."""
    _record(
        manager,
        _episode(4),
        _memory(changes=[FieldChange(
            subject_type="location", subject_id="차원게이트", section_key="state",
            value="고장", reason="공격을 받아 파손", kind="removed",
        )]),
    )
    _record(
        manager,
        _episode(6),
        _memory(changes=[FieldChange(
            subject_type="location", subject_id="차원게이트", section_key="state",
            value="수리됨", reason="한창군이 고침", kind="restored",
        )]),
    )

    chain = manager.chronicle.chain("location", "차원게이트", "state")

    assert [e.kind for e in chain] == ["removed", "restored"]
    assert chain[-1].value == "수리됨"


def test_a_rule_can_be_abolished(manager):
    _record(
        manager,
        _episode(5),
        _memory(changes=[FieldChange(
            subject_type="rule", subject_id="비밀-유지", section_key="active",
            value="폐지됨", reason="마법의 존재가 공개됨", kind="removed",
        )]),
    )

    assert manager.chronicle.chain("rule", "비밀-유지", "active")[0].kind == "removed"


def test_what_a_character_did_is_recorded_even_with_no_change(manager):
    """Appearing in a chapter is worth a line in their history."""
    _record(
        manager,
        _episode(1),
        _memory(deeds=[Deed(character_id="박동혁", summary="시월의 정체를 캐물었다.")]),
    )

    deeds = manager.chronicle.chain("character", "박동혁", "deeds")

    assert [e.value for e in deeds] == ["시월의 정체를 캐물었다."]
    assert deeds[0].previous == ""  # a deed does not succeed the last deed


def test_deeds_accumulate_across_episodes(manager):
    _record(
        manager,
        _episode(1), _memory(deeds=[Deed(character_id="박동혁", summary="첫 화의 행적.")])
    )
    _record(
        manager,
        _episode(2), _memory(deeds=[Deed(character_id="박동혁", summary="둘째 화의 행적.")])
    )

    deeds = manager.chronicle.chain("character", "박동혁", "deeds")

    assert [e.episode_number for e in deeds] == [1, 2]
    assert all(e.previous == "" for e in deeds)


def test_a_relationship_that_shifted_gets_its_own_chain(manager):
    """These only ever overwrote each other before."""
    _record(
        manager,
        _episode(2),
        _memory(character_updates=[CharacterStateUpdate(
            character_id="박동혁",
            relationship_updates=[Relationship(
                target_character_id="시월", type="경계하는 상대", sentiment=-0.2,
            )],
        )]),
    )
    _record(
        manager,
        _episode(3),
        _memory(character_updates=[CharacterStateUpdate(
            character_id="박동혁",
            relationship_updates=[Relationship(
                target_character_id="시월", type="신뢰하는 동료", sentiment=0.7,
                description="사념세계에서 감싸 주는 것을 봄",
            )],
        )]),
    )

    chain = manager.chronicle.chain(
        "character", "박동혁", relationship_section_key("시월")
    )

    assert len(chain) == 2
    assert chain[0].value == "경계하는 상대"
    assert "신뢰하는 동료" in chain[1].value
    assert chain[1].previous == "경계하는 상대"


def test_lore_the_episode_established_gets_an_episode_at_last(manager):
    """`world_lore_updates` was a bare list of strings with no attribution."""
    _record(
        manager,
        _episode(3),
        _memory(world_lore_updates=["사념세계의 존재는 현세계에서 형상을 바꿀 수 있다."]),
    )

    events = manager.chronicle.chain("world", "world", "events")

    assert events[0].episode_number == 3
    assert events[0].kind == "revealed"


# ==========================================================================
# The gate
# ==========================================================================


def test_a_change_with_no_reason_never_reaches_the_chronicle():
    """The chronicle overrides the author's setting, so a guess is expensive."""
    memory = _memory(changes=[
        FieldChange(subject_id="박동혁", section_key="personality",
                    value="갑자기 상냥해짐", reason=""),
        FieldChange(subject_id="박동혁", section_key="appearance",
                    value="머리가 잘림", reason="싸움 중 잘림"),
    ])

    cleaned = _sanitise(memory, _episode(1), {"박동혁": object()})

    assert [c.section_key for c in cleaned.changes] == ["appearance"]


def test_an_empty_change_is_dropped():
    memory = _memory(changes=[
        FieldChange(subject_id="박동혁", section_key="appearance", value="   ", reason="이유는 있음")
    ])

    assert _sanitise(memory, _episode(1), {"박동혁": object()}).changes == []


def test_a_change_to_a_character_who_does_not_exist_is_dropped():
    """A hallucinated id would be a history nobody can ever look up."""
    memory = _memory(changes=[
        FieldChange(subject_id="없는사람", section_key="appearance",
                    value="무언가", reason="무언가 때문에")
    ])

    assert _sanitise(memory, _episode(1), {"박동혁": object()}).changes == []


def test_a_change_to_a_place_is_not_checked_against_the_cast():
    """Locations and rules are not characters; the cast check must not eat them."""
    memory = _memory(changes=[
        FieldChange(subject_type="location", subject_id="차원게이트",
                    section_key="state", value="고장", reason="공격받음")
    ])

    assert len(_sanitise(memory, _episode(1), {"박동혁": object()}).changes) == 1


def test_a_deed_by_an_unknown_character_is_dropped():
    memory = _memory(deeds=[
        Deed(character_id="없는사람", summary="무언가 했다."),
        Deed(character_id="박동혁", summary="무언가 했다."),
    ])

    cleaned = _sanitise(memory, _episode(1), {"박동혁": object()})

    assert [d.character_id for d in cleaned.deeds] == ["박동혁"]


# ==========================================================================
# Regeneration
# ==========================================================================


def test_rewriting_a_chapter_replaces_its_history(manager):
    """Both "c → b" and "c → d" in one chain has no defensible current value."""
    _record(
        manager,
        _episode(3),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="첫 번째 결과", reason="첫 생성")]),
    )
    _record(
        manager,
        _episode(3),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="두 번째 결과", reason="다시 생성")]),
    )

    chain = manager.chronicle.chain("character", "박동혁", "appearance")

    assert [e.value for e in chain] == ["두 번째 결과"]


def test_rewriting_a_chapter_leaves_other_chapters_alone(manager):
    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="1화의 변화", reason="a")]),
    )
    _record(
        manager,
        _episode(2),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="2화의 변화", reason="b")]),
    )

    _record(
        manager,
        _episode(2),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="2화 다시", reason="c")]),
    )

    assert [e.value for e in manager.chronicle.chain("character", "박동혁", "appearance")] == [
        "1화의 변화",
        "2화 다시",
    ]


def test_rewriting_a_chapter_leaves_the_authors_own_entries_alone(manager):
    manager.chronicle.record("character", "박동혁", "appearance", "작가가 정한 모습")
    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="1화의 변화", reason="a")]),
    )

    _record(
        manager,
        _episode(1),
        _memory(changes=[FieldChange(subject_id="박동혁", section_key="appearance",
                                     value="1화 다시", reason="b")]),
    )

    chain = manager.chronicle.chain("character", "박동혁", "appearance")
    assert [e.source for e in chain] == ["author", "episode"]
    assert chain[1].previous == "작가가 정한 모습"


# ==========================================================================
# Nothing to record
# ==========================================================================


def test_an_episode_that_moved_nothing_records_nothing(manager):
    _record(manager, _episode(1), _memory())

    assert manager.chronicle.timeline() == []


def test_recording_still_works_with_no_chronicle_content(manager):
    """The rest of the memory layer must not depend on there being changes."""
    memory = _record(
        manager,
        _episode(1), _memory(summary="무슨 일이 있었다.")
    )

    assert memory.summary == "무슨 일이 있었다."
    assert manager.get_episode_summary(1) == "무슨 일이 있었다."
