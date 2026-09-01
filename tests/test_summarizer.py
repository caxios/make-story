"""The Episode Summarizer decides what is worth remembering — and must not invent."""

from __future__ import annotations

import pytest

from storyweaver.memory import summarizer
from storyweaver.memory.plot_tracker import PlotThread
from storyweaver.memory.summarizer import (
    CharacterStateUpdate,
    EpisodeMemory,
    ThreadUpdate,
)
from storyweaver.models import Episode, InteractionRecord, Relationship, Scene


@pytest.fixture
def written_episode(two_character_scene) -> Episode:
    scene = two_character_scene.model_copy(
        update={
            "prose": "The compartment smelled of soot. Ron slid the door shut behind him.",
            "interaction_log": ["[1] ron-weasley (dialogue): Anyone sitting there?"],
        }
    )
    return Episode(
        episode_number=3,
        title="The Compartment",
        author_storyline="Harry meets Ron on the train.",
        scenes=[scene],
        final_text="The compartment smelled of soot.",
        status="completed",
    )


def _clean_memory(**kwargs) -> EpisodeMemory:
    return EpisodeMemory(summary=kwargs.pop("summary", "They met on the train."), **kwargs)


def test_prompt_carries_the_policy_the_episode_and_the_open_threads(
    written_episode, world, characters
):
    threads = [
        PlotThread(
            id="rons_broken_wand",
            name="Ron's broken wand",
            description="It barely works.",
            opened_in_episode=1,
        )
    ]

    prompt = summarizer.build_prompt(written_episode, world, characters, threads, language="en")

    assert "Episode 3 has just been completed" in prompt
    assert "떡밥" in prompt                                  # granularity policy
    assert "It is better to over-record" in prompt
    assert "Ron's broken wand" in prompt                     # open threads offered
    assert "The compartment smelled of soot." in prompt      # the prose itself
    assert "Harry meets Ron on the train." in prompt
    assert "Write in en." in prompt


def test_prompt_says_there_are_no_threads_on_the_first_episode(
    written_episode, world, characters
):
    assert "(none yet)" in summarizer.build_prompt(written_episode, world, characters)


def test_prompt_falls_back_to_the_interaction_log_when_prose_is_missing(
    written_episode, world, characters
):
    unwritten = written_episode.model_copy(
        update={"scenes": [written_episode.scenes[0].model_copy(update={"prose": ""})]}
    )

    prompt = summarizer.build_prompt(unwritten, world, characters)

    assert "Anyone sitting there?" in prompt


def test_summarize_stamps_the_episode_number_onto_every_record(
    written_episode, world, characters, scripted_llm
):
    llm = scripted_llm(
        EpisodeMemory=lambda prompt, index: _clean_memory(
            interactions=[
                InteractionRecord(
                    episode_number=999,  # the model guessed wrong
                    scene_number=1,
                    participants=["harry-potter"],
                    summary="They met.",
                )
            ]
        )
    )

    memory = summarizer.summarize_episode(written_episode, world, characters, llm=llm)

    assert memory.interactions[0].episode_number == 3


def test_invented_character_ids_are_dropped_everywhere(
    written_episode, world, characters, scripted_llm
):
    """A hallucinated id is a memory nobody can ever retrieve."""
    llm = scripted_llm(
        EpisodeMemory=lambda prompt, index: _clean_memory(
            interactions=[
                InteractionRecord(
                    episode_number=3,
                    scene_number=1,
                    participants=["harry-potter", "draco-malfoy"],
                    summary="They met.",
                    emotional_impact={"harry-potter": "wary", "draco-malfoy": "smug"},
                )
            ],
            character_updates=[
                CharacterStateUpdate(character_id="draco-malfoy", internal_state="Smug."),
                CharacterStateUpdate(
                    character_id="harry-potter",
                    internal_state="Wary.",
                    relationship_updates=[
                        Relationship(target_character_id="draco-malfoy", type="rival"),
                        Relationship(target_character_id="ron-weasley", type="friend"),
                    ],
                ),
            ],
            thread_updates=[
                ThreadUpdate(id="a_thread", action="open", name="A thread",
                             linked_characters=["draco-malfoy", "harry-potter"]),
            ],
        )
    )

    memory = summarizer.summarize_episode(written_episode, world, characters, llm=llm)

    assert memory.interactions[0].participants == ["harry-potter"]
    assert memory.interactions[0].emotional_impact == {"harry-potter": "wary"}
    assert [u.character_id for u in memory.character_updates] == ["harry-potter"]
    assert [r.target_character_id for r in memory.character_updates[0].relationship_updates] == [
        "ron-weasley"
    ]
    assert memory.thread_updates[0].linked_characters == ["harry-potter"]


def test_a_record_with_no_known_participants_is_discarded(
    written_episode, world, characters, scripted_llm
):
    llm = scripted_llm(
        EpisodeMemory=lambda prompt, index: _clean_memory(
            interactions=[
                InteractionRecord(
                    episode_number=3, scene_number=1, participants=["dumbledore"],
                    summary="Somebody we do not know did something.",
                ),
                InteractionRecord(
                    episode_number=3, scene_number=1, participants=["harry-potter"],
                    summary="Harry did something.",
                ),
            ]
        )
    )

    memory = summarizer.summarize_episode(written_episode, world, characters, llm=llm)

    assert len(memory.interactions) == 1
    assert memory.interactions[0].participants == ["harry-potter"]


def test_characters_involved_gathers_everyone_the_memory_touches(
    written_episode, world, characters, scripted_llm
):
    llm = scripted_llm(
        EpisodeMemory=lambda prompt, index: _clean_memory(
            interactions=[
                InteractionRecord(
                    episode_number=3, scene_number=1,
                    participants=["harry-potter", "ron-weasley"], summary="They met.",
                )
            ],
            character_updates=[
                CharacterStateUpdate(character_id="hermione-granger", internal_state="Busy.")
            ],
        )
    )

    memory = summarizer.summarize_episode(written_episode, world, characters, llm=llm)

    assert memory.characters_involved() == [
        "harry-potter", "hermione-granger", "ron-weasley",
    ]


def test_an_unwritten_episode_cannot_be_summarized(world, characters, scripted_llm):
    empty = Episode(episode_number=1, author_storyline="Nothing was generated.")
    llm = scripted_llm(EpisodeMemory=lambda prompt, index: _clean_memory())

    with pytest.raises(ValueError, match="no scenes or text"):
        summarizer.summarize_episode(empty, world, characters, llm=llm)

    assert llm.calls == []


def test_a_long_scene_is_truncated_before_it_reaches_the_prompt(world, characters):
    long_prose = "word " * 20000
    episode = Episode(
        episode_number=1,
        author_storyline="Something long.",
        scenes=[
            Scene(
                scene_number=1,
                title="Long",
                participating_character_ids=["harry-potter"],
                objective="Go on at length.",
                prose=long_prose,
            )
        ],
    )

    prompt = summarizer.build_prompt(episode, world, characters)

    assert len(prompt) < len(long_prose)
