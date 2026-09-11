"""Episode N+1 has to know how episode N ended.

Two things carry that: the structured summary, which says what happened, and
the closing passage, which says where everyone was standing when the curtain
fell. A serial that only has the first restarts every chapter.
"""

from __future__ import annotations

from storyweaver.memory.manager import CLOSING_PASSAGE_CHARS
from storyweaver.memory.summarizer import EpisodeMemory
from storyweaver.models import Episode, InteractionRecord

CLOSING = (
    "동혁은 문을 닫았다. 복도의 불빛이 문틈으로 가늘게 새어 들어왔고, "
    "시월은 그 빛을 등진 채 아무 말도 하지 않았다."
)

FIRST_EPISODE_TEXT = "비좁은 화단 구석에서 시작된 하루였다.\n\n◇◇◇\n\n" + CLOSING


def _memory_for(summary: str = "동혁과 시월이 일진 무리를 피해 학교를 빠져나왔다.") -> EpisodeMemory:
    return EpisodeMemory(
        summary=summary,
        key_events=["일진 무리와 마주침"],
        mood="tense",
        interactions=[
            InteractionRecord(
                episode_number=1,
                scene_number=1,
                participants=["harry-potter"],
                summary="동혁이 시월을 등 뒤로 숨겼다.",
            )
        ],
    )


def _episode(number: int = 1, text: str = FIRST_EPISODE_TEXT) -> Episode:
    return Episode(
        episode_number=number,
        title="별이 지는 밤",
        author_storyline="일진 무리를 피해 학교를 빠져나온다.",
        final_text=text,
        status="completed",
    )


# ==========================================================================
# Recording
# ==========================================================================


def test_recording_an_episode_keeps_its_closing_passage(memory):
    memory.record_episode_completion(_episode(), _memory_for())

    closing = memory.structured_store.get_episode_closing()

    assert closing is not None
    number, passage = closing
    assert number == 1
    # The literal end of the prose, not the summary of it.
    assert passage.endswith("아무 말도 하지 않았다.")
    assert len(passage) <= CLOSING_PASSAGE_CHARS


def test_an_episode_with_no_prose_records_no_closing(memory):
    """A chapter recorded from its interaction log alone has no prose to quote."""
    memory.record_episode_completion(_episode(text=""), _memory_for())

    assert memory.structured_store.get_episode_closing() is None
    # The summary still landed, so the episode is not invisible to the next one.
    assert memory.get_episode_summary(1)


def test_the_closing_passage_opens_on_a_paragraph(memory):
    """A passage that opens mid-sentence reads as damage, not as continuity."""
    # A long paragraph, then the real ending. The budget cannot hold both.
    text = "앞부분.\n\n" + "가" * (CLOSING_PASSAGE_CHARS - 50) + "\n\n" + CLOSING
    memory.record_episode_completion(_episode(text=text), _memory_for())

    _, passage = memory.structured_store.get_episode_closing()

    assert passage == CLOSING  # the last whole paragraph, and only that
    assert text.endswith(passage)  # it really is the end of the chapter


def test_a_single_paragraph_longer_than_the_budget_is_still_quoted(memory):
    """Some of the ending beats none of it."""
    text = "나" * (CLOSING_PASSAGE_CHARS * 2)
    memory.record_episode_completion(_episode(text=text), _memory_for())

    _, passage = memory.structured_store.get_episode_closing()

    assert len(passage) == CLOSING_PASSAGE_CHARS
    assert text.endswith(passage)


# ==========================================================================
# Tier 1 — the continuity brief
# ==========================================================================


def test_the_continuity_brief_quotes_the_previous_ending(memory):
    memory.record_episode_completion(_episode(), _memory_for())

    brief = memory.build_continuity_brief()

    assert "Episode 1 ended here" in brief
    assert "아무 말도 하지 않았다." in brief
    assert "Scene 1 of this episode must follow on" in brief


def test_there_is_no_continuity_brief_before_the_first_episode(memory):
    assert memory.build_continuity_brief() == ""


# ==========================================================================
# What the next Director is handed
# ==========================================================================


def test_the_director_context_is_tiered_and_carries_the_previous_episode(
    memory, world, characters
):
    memory.seed_world(world)
    memory.record_episode_completion(_episode(), _memory_for())

    context = memory.build_director_context(characters, _episode(number=2, text=""))

    # Tier 1: where to pick up from.
    assert "Tier 1" in context
    assert "아무 말도 하지 않았다." in context
    # Tier 2: what happened, in order.
    assert "Tier 2" in context
    assert "일진 무리를 피해" in context or "동혁과 시월이" in context


def test_the_writer_is_shown_real_prose_rather_than_a_summary(memory, two_character_scene):
    """Handing the Writer a summary to 'match the voice of' teaches it to summarize."""
    memory.record_episode_completion(_episode(), _memory_for())

    sample = memory._previous_prose_sample(None)

    assert "아무 말도 하지 않았다." in sample
    assert "동혁과 시월이 일진 무리를" not in sample  # that is the summary, not the prose


# ==========================================================================
# Tier 3 — recall asked several ways
# ==========================================================================


def test_recall_merges_several_queries_and_deduplicates(memory, world, characters):
    memory.seed_world(world)
    memory.record_episode_completion(_episode(), _memory_for())

    found = memory.recall_for_episode(_episode(number=2, text=""), characters)

    assert found
    assert len(found) == len(set(found))  # the same memory reached twice is kept once


def test_recall_survives_an_empty_storyline(memory, world, characters):
    """An episode queued with a blank outline must not take the Director down."""
    memory.seed_world(world)

    found = memory.recall_for_episode(
        Episode(episode_number=2, author_storyline="   "), characters
    )

    assert isinstance(found, list)
