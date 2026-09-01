"""Phase 4, Tests 1 & 4: retrieval accuracy and cross-episode continuity."""

from __future__ import annotations

import pytest

from storyweaver.memory.manager import NOTHING_YET
from storyweaver.memory.summarizer import (
    CharacterStateUpdate,
    EpisodeMemory,
    ThreadUpdate,
)
from storyweaver.models import Episode, InteractionRecord, Relationship


def _episode(number: int, storyline: str = "Something happens.") -> Episode:
    return Episode(
        episode_number=number,
        title=f"Episode {number}",
        author_storyline=storyline,
        final_text="Prose.",
    )


def _memory_for(number: int, summary: str, **kwargs) -> EpisodeMemory:
    return EpisodeMemory(summary=summary, **kwargs)


# ==========================================================================
# Test 1: retrieval accuracy across several episodes
# ==========================================================================

@pytest.fixture
def five_episodes(memory, world):
    """Five recorded episodes, one of which is about the trapdoor."""
    memory.seed_world(world)

    beats = {
        1: ("Harry got his Hogwarts letter and met Hagrid.", ["harry-potter"]),
        2: ("Harry met Ron on the Hogwarts express and they became friends.",
            ["harry-potter", "ron-weasley"]),
        3: ("Harry, Ron and Hermione found a three-headed dog standing on a trapdoor "
            "in the forbidden corridor.",
            ["harry-potter", "ron-weasley", "hermione-granger"]),
        4: ("Ron won a game of wizard chess against nobody in particular.", ["ron-weasley"]),
        5: ("Hermione read about Nicolas Flamel in the library.", ["hermione-granger"]),
    }
    for number, (summary, participants) in beats.items():
        memory.record_episode_completion(
            _episode(number),
            _memory_for(
                number,
                summary,
                interactions=[
                    InteractionRecord(
                        episode_number=number,
                        scene_number=1,
                        participants=participants,
                        summary=summary,
                    )
                ],
            ),
        )
    return memory


def test_a_query_finds_the_right_episode(five_episodes):
    found = five_episodes.get_relevant_memories("What is under the trapdoor?", top_k=3)

    assert any("trapdoor" in text for text in found)
    assert "(Episode 3)" in found[0]


def test_retrieval_can_be_scoped_to_one_character(five_episodes):
    harry = five_episodes.search("trapdoor dog corridor", character_id="harry-potter")
    hermione = five_episodes.search("library flamel", character_id="hermione-granger")

    assert all(
        "harry-potter" in (m.metadata.get("participants") or [])
        or "harry-potter" in (m.metadata.get("characters_involved") or [])
        for m in harry
    )
    assert any("Flamel" in m.document for m in hermione)


def test_a_named_episode_summary_is_an_exact_lookup(five_episodes):
    assert "trapdoor" in five_episodes.get_episode_summary(3)
    assert five_episodes.get_episode_summary(99) == ""


def test_recent_context_is_the_last_three_episodes_in_order(five_episodes):
    context = five_episodes.get_recent_context()

    assert "### Episode 3" in context
    assert "### Episode 5" in context
    assert "### Episode 1" not in context
    assert context.index("Episode 3") < context.index("Episode 5")


def test_recent_context_length_is_configurable(five_episodes):
    assert "### Episode 4" not in five_episodes.get_recent_context(n_episodes=1)


# ==========================================================================
# Recording an episode
# ==========================================================================

def test_recording_writes_to_every_store(memory, world):
    memory.seed_world(world)

    memory.record_episode_completion(
        _episode(1),
        _memory_for(
            1,
            "Harry met Ron on the train.",
            key_events=["first meeting"],
            locations=["hogwarts-express"],
            mood="warm",
            interactions=[
                InteractionRecord(
                    episode_number=1,
                    scene_number=1,
                    participants=["harry-potter", "ron-weasley"],
                    summary="Harry promised Ron he would never mention the wand.",
                    emotional_impact={"ron-weasley": "relieved"},
                )
            ],
            thread_updates=[
                ThreadUpdate(
                    id="rons_broken_wand",
                    action="open",
                    name="Ron's broken wand",
                    description="Ron's hand-me-down wand barely works.",
                    linked_characters=["ron-weasley"],
                )
            ],
            character_updates=[
                CharacterStateUpdate(
                    character_id="ron-weasley",
                    internal_state="Relieved, and quietly grateful.",
                    current_goals=["Keep the wand a secret"],
                    relationship_updates=[
                        Relationship(
                            target_character_id="harry-potter", type="friend", sentiment=0.8
                        )
                    ],
                )
            ],
            world_lore_updates=["Wands can be inherited, and inherited wands serve poorly."],
        ),
    )

    # Structured store
    ron = memory.get_character_state("ron-weasley")
    assert ron.internal_state == "Relieved, and quietly grateful."
    assert ron.current_goals == ["Keep the wand a secret"]
    assert ron.relationship_updates[0].sentiment == 0.8
    assert len(ron.interaction_history) == 1
    assert ron.last_updated_episode == 1

    # Plot tracker
    assert [t.id for t in memory.get_active_plot_threads()] == ["rons_broken_wand"]

    # Vector store
    assert memory.get_episode_summary(1) == "Harry met Ron on the train."
    assert memory.get_relevant_memories("promise wand", top_k=5)


def test_an_interaction_is_filed_under_every_participant(memory):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(
            1,
            "They met.",
            interactions=[
                InteractionRecord(
                    episode_number=1,
                    scene_number=1,
                    participants=["harry-potter", "ron-weasley"],
                    summary="They met on the train.",
                )
            ],
        ),
    )

    assert len(memory.get_character_state("harry-potter").interaction_history) == 1
    assert len(memory.get_character_state("ron-weasley").interaction_history) == 1


def test_resolving_a_thread_moves_it_out_of_active(memory):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(1, "Opened.", thread_updates=[
            ThreadUpdate(id="the_mystery", action="open", name="The mystery",
                         description="Something is hidden."),
        ]),
    )
    memory.record_episode_completion(
        _episode(5),
        _memory_for(5, "Closed.", thread_updates=[
            ThreadUpdate(id="the_mystery", action="resolve",
                         resolution="It was the Stone all along."),
        ]),
    )

    assert memory.get_active_plot_threads() == []
    thread = memory.plot_tracker.get("the_mystery")
    assert thread.status == "resolved"
    assert thread.resolved_in_episode == 5
    assert memory.structured_store.get_story().resolved_plot_threads == ["the_mystery"]


def test_progressing_an_unknown_thread_opens_it_first(memory):
    """Summarizers cite threads they forgot to open; recording must not crash."""
    memory.record_episode_completion(
        _episode(3),
        _memory_for(3, "Progressed.", thread_updates=[
            ThreadUpdate(id="never_opened", action="progress", event="It advanced.",
                         name="Never opened", description="A thread from nowhere."),
        ]),
    )

    thread = memory.plot_tracker.get("never_opened")
    assert thread is not None
    assert thread.status == "progressing"


def test_re_recording_an_episode_corrects_rather_than_duplicates(memory):
    memory.record_episode_completion(_episode(1), _memory_for(1, "First attempt."))
    memory.record_episode_completion(_episode(1), _memory_for(1, "Corrected version."))

    assert memory.get_episode_summary(1) == "Corrected version."
    assert memory.vector_store.count("episode_summaries") == 1


# ==========================================================================
# Test 4: cross-episode continuity
# ==========================================================================

def test_a_promise_in_episode_one_reaches_the_character_in_episode_three(
    memory, harry, ron, characters, two_character_scene
):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(
            1,
            "Harry promised Ron he would never tell anyone about the wand.",
            interactions=[
                InteractionRecord(
                    episode_number=1,
                    scene_number=1,
                    participants=["harry-potter", "ron-weasley"],
                    summary="Harry made Ron a promise about the wand, and meant it.",
                    emotional_impact={"ron-weasley": "trusting"},
                )
            ],
            character_updates=[
                CharacterStateUpdate(
                    character_id="harry-potter",
                    internal_state="Determined to keep his word.",
                    current_goals=["Keep Ron's secret"],
                    relationship_updates=[
                        Relationship(
                            target_character_id="ron-weasley",
                            type="close friend",
                            sentiment=0.9,
                            description="Bound by a promise about the wand.",
                        )
                    ],
                )
            ],
        ),
    )

    packet = memory.build_character_context(harry, two_character_scene, characters)

    assert "promise" in packet.lower()
    assert "Determined to keep his word." in packet
    assert "Keep Ron's secret" in packet
    assert "Ron Weasley — close friend" in packet
    assert "+0.9" in packet


def test_a_character_only_recalls_what_they_were_present_for(
    memory, harry, characters, two_character_scene
):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(
            1,
            "Two separate things happened.",
            interactions=[
                InteractionRecord(
                    episode_number=1, scene_number=1, participants=["hermione-granger"],
                    summary="Hermione found the trapdoor alone in the library.",
                ),
                InteractionRecord(
                    episode_number=1, scene_number=2, participants=["harry-potter"],
                    summary="Harry played chess with nobody watching.",
                ),
            ],
        ),
    )

    packet = memory.build_character_context(harry, two_character_scene, characters)

    assert "chess" in packet
    assert "library" not in packet


def test_director_context_carries_threads_relationships_and_the_story_so_far(
    memory, characters, world
):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(
            1,
            "Harry met Ron.",
            thread_updates=[
                ThreadUpdate(id="rons_broken_wand", action="open", name="Ron's broken wand",
                             description="It barely works."),
            ],
            character_updates=[
                CharacterStateUpdate(
                    character_id="harry-potter",
                    relationship_updates=[
                        Relationship(target_character_id="ron-weasley", type="friend",
                                     sentiment=0.8)
                    ],
                )
            ],
        ),
    )

    packet = memory.build_director_context(characters, _episode(2, "They meet again."))

    assert "Story So Far" in packet
    assert "Harry met Ron." in packet
    assert "Ron's broken wand" in packet
    assert "Harry Potter -> Ron Weasley: friend" in packet


def test_director_context_flags_threads_going_cold(memory, characters):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(1, "Opened.", thread_updates=[
            ThreadUpdate(id="forgotten", action="open", name="A forgotten thread",
                         description="Nobody has mentioned it since."),
        ]),
    )

    packet = memory.build_director_context(characters, _episode(9))

    assert "Threads Going Cold" in packet
    assert "A forgotten thread" in packet


def test_the_first_episode_gets_no_memory_context(memory, characters, harry, two_character_scene):
    assert memory.build_director_context(characters, _episode(1)) == NOTHING_YET
    assert memory.build_character_context(harry, two_character_scene, characters) == NOTHING_YET
    assert memory.build_writer_context(two_character_scene) == NOTHING_YET


def test_writer_context_offers_tone_and_callbacks(memory, two_character_scene):
    memory.record_episode_completion(
        _episode(1),
        _memory_for(1, "Harry and Ron met on the express and became friends."),
    )

    packet = memory.build_writer_context(two_character_scene)

    assert "Established Prose Tone" in packet
    assert "became friends" in packet


def test_opening_and_resolving_threads_by_hand(memory):
    memory.open_plot_thread("The locked door", "Nobody knows what is behind it.", episode=1)

    assert [t.id for t in memory.get_active_plot_threads()] == ["the_locked_door"]

    memory.progress_plot_thread("The locked door", "A key turns up.", episode=2)
    memory.resolve_plot_thread("The locked door", "It was a broom cupboard.", episode=3)

    assert memory.get_active_plot_threads() == []


def test_stale_threads_are_reported(memory):
    memory.open_plot_thread("Old news", "Planted and forgotten.", episode=1)

    assert memory.get_stale_plot_threads(current_episode=2) == []
    assert [t.id for t in memory.get_stale_plot_threads(current_episode=10)] == ["old_news"]


def test_memory_survives_a_restart(tmp_path, chroma_client, world):
    from tests.conftest import DeterministicEmbedding
    from storyweaver.memory import MemoryManager, VectorStore

    def build():
        return MemoryManager(
            vector_store=VectorStore(
                client=chroma_client, embedding_function=DeterministicEmbedding()
            ),
            data_dir=tmp_path / "state",
        )

    first = build()
    first.seed_world(world)
    first.record_episode_completion(
        _episode(1),
        _memory_for(1, "Harry found the trapdoor.", thread_updates=[
            ThreadUpdate(id="whats_under_trapdoor", action="open", name="The trapdoor",
                         description="Something is under it."),
        ]),
    )

    second = build()

    assert second.get_episode_summary(1) == "Harry found the trapdoor."
    assert [t.id for t in second.get_active_plot_threads()] == ["whats_under_trapdoor"]
    assert second.get_relevant_memories("trapdoor")
