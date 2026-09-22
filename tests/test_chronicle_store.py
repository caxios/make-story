"""The chronicle: an append-only history of every setting in the story.

Two properties carry the weight. Nothing is ever lost — a value that changed
twice leaves both steps behind, because the author audits a finished arc by
reading them. And the order of a chain is its own: reordering the episode queue
must not reorder history that already happened.
"""

from __future__ import annotations

import json
import unicodedata

import pytest

from storyweaver.memory.chronicle_store import ChronicleStore, new_entry_id
from storyweaver.models.chronicle import ChronicleEntry


@pytest.fixture
def store(tmp_path) -> ChronicleStore:
    return ChronicleStore(tmp_path / "state")


def _entry(**overrides) -> ChronicleEntry:
    base = {
        "entry_id": new_entry_id(),
        "subject_type": "character",
        "subject_id": "박동혁",
        "section_key": "appearance",
        "source": "author",
        "kind": "initial",
        "value": "단정한 단발",
    }
    return ChronicleEntry.model_validate({**base, **overrides})


# ==========================================================================
# The chain
# ==========================================================================


def test_a_chain_keeps_every_step(store):
    """c → b → d leaves all three behind; this is the point of the store."""
    store.record("character", "박동혁", "appearance", "단정한 단발")
    store.record(
        "character", "박동혁", "appearance", "한쪽 눈을 덮은 앞머리",
        source="episode", episode_number=1, reason="시월과의 실랑이 중 잘림",
    )
    store.record(
        "character", "박동혁", "appearance", "짧게 친 머리",
        source="episode", episode_number=7, reason="사념세계 진입 전 직접 자름",
    )

    chain = store.chain("character", "박동혁", "appearance")

    assert [e.value for e in chain] == ["단정한 단발", "한쪽 눈을 덮은 앞머리", "짧게 친 머리"]
    assert [e.previous for e in chain] == ["", "단정한 단발", "한쪽 눈을 덮은 앞머리"]


def test_the_first_entry_is_initial_and_the_rest_are_changes(store):
    first = store.record("character", "박동혁", "appearance", "단정한 단발")
    second = store.record("character", "박동혁", "appearance", "짧은 머리")

    assert first.kind == "initial"
    assert second.kind == "changed"


def test_each_section_has_its_own_history(store):
    """The key is (subject, section), not (subject)."""
    store.record("character", "박동혁", "appearance", "단정한 단발")
    store.record("character", "박동혁", "personality", "까탈스러움")

    assert len(store.chain("character", "박동혁", "appearance")) == 1
    assert len(store.chain("character", "박동혁", "personality")) == 1
    assert len(store.subject("character", "박동혁")) == 2


def test_a_relationship_is_its_own_chain_per_person(store):
    from storyweaver.wiki import relationship_section_key

    store.record("character", "박동혁", relationship_section_key("시월"), "모르는 사이")
    store.record(
        "character", "박동혁", relationship_section_key("시월"), "신뢰하는 동료",
        source="episode", episode_number=3, reason="사념세계에서 감싸 주는 것을 봄",
    )
    store.record("character", "박동혁", relationship_section_key("한병호"), "경계하는 상대")

    siwol = store.chain("character", "박동혁", relationship_section_key("시월"))
    byeongho = store.chain("character", "박동혁", relationship_section_key("한병호"))

    assert [e.value for e in siwol] == ["모르는 사이", "신뢰하는 동료"]
    assert len(byeongho) == 1


def test_the_authors_own_writing_is_the_first_entry(store):
    """There is no separate base record, which is why nothing has to be synced."""
    first = store.record("character", "박동혁", "appearance", "단정한 단발")

    assert first.source == "author"
    assert first.episode_number is None
    assert store.chain("character", "박동혁", "appearance")[0] == first


def test_an_author_edit_after_an_episode_is_just_the_next_entry(store):
    store.record("character", "박동혁", "appearance", "단정한 단발")
    store.record(
        "character", "박동혁", "appearance", "앞머리가 잘림",
        source="episode", episode_number=1, reason="싸움 중",
    )
    latest = store.record("character", "박동혁", "appearance", "헝클어진 앞머리")

    chain = store.chain("character", "박동혁", "appearance")
    assert chain[-1] == latest
    assert latest.previous == "앞머리가 잘림"


def test_a_log_section_accumulates_rather_than_succeeding_itself(store):
    """작중 행적 has no "before": the entries are the content, not a value."""
    store.record("character", "박동혁", "deeds", "시월의 정체를 캐물음.",
                 source="episode", episode_number=1)
    store.record("character", "박동혁", "deeds", "한병호의 추궁을 막아섬.",
                 source="episode", episode_number=2)

    chain = store.chain("character", "박동혁", "deeds")

    assert [e.previous for e in chain] == ["", ""]
    assert [e.kind for e in chain] == ["added", "added"]
    # And it reads as a deed, not as a change from the last one.
    assert "→" not in chain[1].describe()


def test_a_section_the_author_invented_can_be_declared_a_log(store):
    """The registry has never heard of it, so the caller has to say."""
    store.record("character", "박동혁", "quotes", "첫 번째 명대사", section_kind="log")
    store.record("character", "박동혁", "quotes", "두 번째 명대사", section_kind="log")

    assert [e.previous for e in store.chain("character", "박동혁", "quotes")] == ["", ""]


def test_a_section_the_author_invented_is_stateful_by_default(store):
    store.record("character", "박동혁", "ability", "평범함")
    store.record("character", "박동혁", "ability", "영혼석을 다룸",
                 source="episode", episode_number=5, reason="각성")

    chain = store.chain("character", "박동혁", "ability")

    assert chain[1].previous == "평범함"
    assert chain[1].kind == "changed"


# ==========================================================================
# Ordering
# ==========================================================================


def test_entries_are_ordered_by_sequence_not_by_episode(store):
    """An author correcting episode 3 after episode 7 belongs where they put it."""
    store.record("character", "박동혁", "appearance", "처음", source="episode", episode_number=7)
    store.record("character", "박동혁", "appearance", "나중", source="episode", episode_number=3)

    chain = store.chain("character", "박동혁", "appearance")

    assert [e.value for e in chain] == ["처음", "나중"]
    assert [e.sequence for e in chain] == sorted(e.sequence for e in chain)


def test_sequence_numbers_are_unique_across_subjects(store):
    a = store.record("character", "박동혁", "appearance", "x")
    b = store.record("character", "임소희", "appearance", "y")
    c = store.record("location", "차원게이트", "state", "작동")

    assert len({a.sequence, b.sequence, c.sequence}) == 3


def test_a_batch_is_numbered_in_the_order_given(store):
    written = store.append_many([
        _entry(section_key="appearance", value="첫째"),
        _entry(section_key="personality", value="둘째"),
        _entry(section_key="speech", value="셋째"),
    ])

    assert [e.value for e in written] == ["첫째", "둘째", "셋째"]
    assert [e.sequence for e in written] == sorted(e.sequence for e in written)


def test_the_counter_survives_a_restart(store, tmp_path):
    store.record("character", "박동혁", "appearance", "처음")
    reopened = ChronicleStore(tmp_path / "state")

    later = reopened.record("character", "박동혁", "appearance", "나중")

    assert later.sequence > 0
    assert len(reopened.chain("character", "박동혁", "appearance")) == 2


def test_a_corrupt_counter_is_recovered_from_the_entries(store):
    """Losing the counter must not make new entries sort before old ones."""
    first = store.record("character", "박동혁", "appearance", "처음")
    store.sequence_path.write_text("not json at all", encoding="utf-8")

    later = store.record("character", "박동혁", "appearance", "나중")

    assert later.sequence > first.sequence


# ==========================================================================
# Retracting and editing
# ==========================================================================


def test_a_retracted_entry_is_marked_not_deleted(store):
    """A mistaken retraction has to be recoverable, and the audit trail whole."""
    store.record("character", "박동혁", "appearance", "단정한 단발")
    wrong = store.record(
        "character", "박동혁", "appearance", "머리가 하얗게 셈",
        source="episode", episode_number=2, reason="요약기가 지어냄",
    )

    store.retract(wrong.entry_id)

    assert [e.value for e in store.chain("character", "박동혁", "appearance")] == ["단정한 단발"]
    assert len(store.chain("character", "박동혁", "appearance", include_all=True)) == 2
    assert store.get(wrong.entry_id).superseded is True


def test_a_retraction_can_be_undone(store):
    entry = store.record("character", "박동혁", "appearance", "단정한 단발")
    store.retract(entry.entry_id)

    store.restore(entry.entry_id)

    assert store.get(entry.entry_id).superseded is False


def test_editing_an_entry_does_not_move_it(store):
    """An entry that could move would make the chain unreadable as a history."""
    first = store.record("character", "박동혁", "appearance", "단정한 단발")
    second = store.record("character", "박동혁", "appearance", "짧은 머리")

    store.edit(second.entry_id, value="아주 짧은 머리", reason="작가 수정")

    chain = store.chain("character", "박동혁", "appearance")
    assert [e.value for e in chain] == ["단정한 단발", "아주 짧은 머리"]
    assert chain[1].sequence > first.sequence


def test_an_entry_cannot_be_moved_to_another_subject(store):
    entry = store.record("character", "박동혁", "appearance", "단정한 단발")

    store.edit(entry.entry_id, subject_id="임소희", sequence=999, section_key="speech")

    unchanged = store.get(entry.entry_id)
    assert unchanged.subject_id == "박동혁"
    assert unchanged.section_key == "appearance"
    assert unchanged.sequence == entry.sequence


# ==========================================================================
# Episode integrity
# ==========================================================================


def test_regenerating_an_episode_can_drop_its_records(store):
    """Otherwise a chain holds both "c → b" and "c → d" for the same chapter."""
    store.record("character", "박동혁", "appearance", "단정한 단발")
    store.record(
        "character", "박동혁", "appearance", "짧은 머리",
        source="episode", episode_number=3, reason="첫 번째 생성",
    )
    store.record("character", "임소희", "personality", "냉정함", source="episode", episode_number=3)
    store.record("character", "임소희", "goals", "탈출", source="episode", episode_number=4)

    dropped = store.drop_episode(3)

    assert dropped == 2
    assert [e.value for e in store.chain("character", "박동혁", "appearance")] == ["단정한 단발"]
    assert store.chain("character", "임소희", "personality") == []
    assert len(store.chain("character", "임소희", "goals")) == 1


def test_dropping_an_episode_leaves_author_entries_alone(store):
    store.record("character", "박동혁", "appearance", "작가가 쓴 것")
    store.record("character", "박동혁", "appearance", "3화", source="episode", episode_number=3)

    store.drop_episode(3)

    assert [e.source for e in store.chain("character", "박동혁", "appearance")] == ["author"]


def test_renumbering_follows_the_queue(store):
    """delete_episode and move_episode renumber the whole queue behind us."""
    store.record("character", "박동혁", "appearance", "a", source="episode", episode_number=3)
    store.record("character", "박동혁", "personality", "b", source="episode", episode_number=4)
    store.record("character", "박동혁", "goals", "c", source="episode", episode_number=5)

    moved = store.renumber({3: None, 4: 3, 5: 4})

    assert moved == 3
    assert store.chain("character", "박동혁", "appearance") == []  # its episode is gone
    assert store.chain("character", "박동혁", "personality")[0].episode_number == 3
    assert store.chain("character", "박동혁", "goals")[0].episode_number == 4


def test_renumbering_does_not_reorder_history(store):
    """Reordering the queue does not reorder what already happened."""
    first = store.record("character", "박동혁", "appearance", "먼저", source="episode", episode_number=3)
    second = store.record("character", "박동혁", "appearance", "나중", source="episode", episode_number=4)

    store.renumber({3: 9, 4: 1})

    chain = store.chain("character", "박동혁", "appearance")
    assert [e.value for e in chain] == ["먼저", "나중"]
    assert [e.sequence for e in chain] == [first.sequence, second.sequence]


# ==========================================================================
# Finding things
# ==========================================================================


def test_an_episodes_records_can_be_gathered_across_subjects(store):
    """This is what the author reviews after a chapter is written."""
    store.record("character", "박동혁", "appearance", "a", source="episode", episode_number=5)
    store.record("character", "임소희", "goals", "b", source="episode", episode_number=5)
    store.record("location", "차원게이트", "state", "고장", source="episode", episode_number=5)
    store.record("character", "박동혁", "goals", "c", source="episode", episode_number=6)

    found = store.by_episode(5)

    assert len(found) == 3
    assert [e.sequence for e in found] == sorted(e.sequence for e in found)


def test_the_timeline_is_the_whole_story_in_order(store):
    store.record("character", "박동혁", "appearance", "a")
    store.record("location", "차원게이트", "state", "작동")
    retracted = store.record("character", "임소희", "goals", "b")
    store.retract(retracted.entry_id)

    timeline = store.timeline()

    assert len(timeline) == 2
    assert len(store.timeline(include_all=True)) == 3


def test_subjects_with_a_history_can_be_listed(store):
    store.record("character", "박동혁", "appearance", "a")
    store.record("location", "차원게이트", "state", "작동")

    assert sorted(store.known_subjects()) == [
        ("character", "박동혁"),
        ("location", "차원게이트"),
    ]


def test_a_subjects_sections_are_listed_in_the_order_they_were_written(store):
    store.record("character", "박동혁", "appearance", "a")
    store.record("character", "박동혁", "goals", "b")
    store.record("character", "박동혁", "appearance", "c")

    assert store.section_keys("character", "박동혁") == ["appearance", "goals"]


def test_an_empty_store_answers_without_a_directory(store):
    assert store.is_empty() is True
    assert store.timeline() == []
    assert store.known_subjects() == []
    assert store.by_episode(1) == []
    assert store.chain("character", "아무개", "appearance") == []


# ==========================================================================
# Files on disk
# ==========================================================================


def test_a_korean_cast_does_not_share_one_file(store):
    """The scheme this replaced collapsed every three-syllable name into one."""
    cast = ["한병호", "나도현", "임소희", "유라엘", "김현서"]

    for index, name in enumerate(cast):
        store.record("character", name, "appearance", f"모습-{index}")

    paths = {store.subject_path("character", name) for name in cast}
    assert len(paths) == len(cast)
    for index, name in enumerate(cast):
        assert store.chain("character", name, "appearance")[0].value == f"모습-{index}"


def test_the_same_name_composed_two_ways_is_one_subject(store):
    composed = unicodedata.normalize("NFC", "한병호")
    decomposed = unicodedata.normalize("NFD", "한병호")
    assert composed != decomposed  # otherwise this test proves nothing

    store.record("character", composed, "appearance", "하나")

    assert len(store.chain("character", decomposed, "appearance")) == 1


def test_a_subject_id_cannot_escape_the_directory(store):
    store.record("character", "../../evil", "appearance", "x")

    path = store.subject_path("character", "../../evil")
    assert path.parent == store.root / "character"
    assert ".." not in path.name


def test_two_types_can_share_an_id(store):
    """A place and a faction may both be called 사념세계."""
    store.record("location", "사념세계", "description", "장소")
    store.record("faction", "사념세계", "description", "세력")

    assert store.chain("location", "사념세계", "description")[0].value == "장소"
    assert store.chain("faction", "사념세계", "description")[0].value == "세력"


def test_korean_is_readable_on_disk(store):
    """`data/state/` is somewhere the author looks, not only the program."""
    store.record("character", "박동혁", "appearance", "단정한 단발")
    path = store.subject_path("character", "박동혁")

    assert "박동혁" in path.name
    assert "단정한 단발" in path.read_text(encoding="utf-8")


def test_entries_survive_a_restart(store, tmp_path):
    store.record(
        "character", "박동혁", "appearance", "짧은 머리",
        source="episode", episode_number=1, reason="잘림",
    )

    reopened = ChronicleStore(tmp_path / "state")
    entry = reopened.chain("character", "박동혁", "appearance")[0]

    assert entry.value == "짧은 머리"
    assert entry.episode_number == 1
    assert entry.reason == "잘림"


def test_an_unreadable_subject_file_does_not_take_the_store_down(store):
    store.record("character", "박동혁", "appearance", "a")
    store.subject_path("character", "박동혁").write_text("{ broken", encoding="utf-8")

    assert store.chain("character", "박동혁", "appearance") == []
    assert store.timeline() == []


# ==========================================================================
# Wiki subjects
# ==========================================================================


def test_a_page_that_has_never_been_saved_comes_back_empty(store):
    subject = store.get_wiki_subject("character", "박동혁")

    assert subject.subject_id == "박동혁"
    assert subject.summary == ""
    assert subject.free_sections == []


def test_free_sections_survive_a_restart(store, tmp_path):
    from storyweaver.models.chronicle import SectionSpec

    subject = store.get_wiki_subject("character", "박동혁")
    subject.summary = "지극히 평범한 고등학생."
    subject.free_sections.append(
        SectionSpec(key="ability", title="능력", order=200, author_made=True)
    )
    store.save_wiki_subject(subject)

    reopened = ChronicleStore(tmp_path / "state").get_wiki_subject("character", "박동혁")

    assert reopened.summary == "지극히 평범한 고등학생."
    assert reopened.section("ability").title == "능력"


# ==========================================================================
# The entry itself
# ==========================================================================


def test_an_entry_describes_itself_the_way_the_wiki_shows_it(store):
    entry = store.record(
        "character", "박동혁", "appearance", "짧게 친 머리",
        source="episode", episode_number=7, reason="직접 자름", previous="긴 앞머리",
    )

    line = entry.describe()

    assert "7화" in line and "긴 앞머리 → 짧게 친 머리" in line and "직접 자름" in line


def test_an_author_entry_is_labelled_by_hand_not_by_chapter(store):
    entry = store.record("character", "박동혁", "appearance", "단정한 단발")

    assert entry.describe().startswith("[작가]")


def test_the_file_is_json_a_person_can_read(store):
    store.record("character", "박동혁", "appearance", "단정한 단발")

    raw = json.loads(store.subject_path("character", "박동혁").read_text(encoding="utf-8"))

    assert raw["entries"][0]["value"] == "단정한 단발"
    assert raw["entries"][0]["section_key"] == "appearance"
