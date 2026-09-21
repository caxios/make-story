"""The two non-semantic stores: exact character state, and the vector collections."""

from __future__ import annotations

from storyweaver.memory import vector_store as vs
from storyweaver.memory.structured_store import StructuredStore
from storyweaver.models import InteractionRecord, Relationship


# ==========================================================================
# StructuredStore
# ==========================================================================

def test_an_unknown_character_gets_an_empty_memory(store):
    memory = store.get_character("harry-potter")

    assert memory.character_id == "harry-potter"
    assert memory.interaction_history == []
    assert memory.internal_state == ""


def test_character_state_updates_merge_rather_than_replace(store):
    store.update_character("harry-potter", internal_state="Wary.", episode=1)
    store.update_character("harry-potter", current_goals=["Find the Stone"], episode=2)

    memory = store.get_character("harry-potter")

    assert memory.internal_state == "Wary."     # not clobbered by the second call
    assert memory.current_goals == ["Find the Stone"]
    assert memory.last_updated_episode == 2


def test_a_relationship_is_replaced_not_appended(store):
    store.update_character(
        "harry-potter",
        relationship_updates=[
            Relationship(target_character_id="ron-weasley", type="stranger", sentiment=0.0)
        ],
    )
    store.update_character(
        "harry-potter",
        relationship_updates=[
            Relationship(target_character_id="ron-weasley", type="friend", sentiment=0.8)
        ],
    )

    updates = store.get_character("harry-potter").relationship_updates

    assert len(updates) == 1
    assert updates[0].type == "friend"
    assert updates[0].sentiment == 0.8


def test_the_episode_counter_never_moves_backwards(store):
    store.update_character("harry-potter", episode=5)
    store.update_character("harry-potter", episode=2)

    assert store.get_character("harry-potter").last_updated_episode == 5


def test_character_ids_cannot_escape_the_data_directory(tmp_path):
    store = StructuredStore(tmp_path / "state")

    store.update_character("../../evil", internal_state="x")

    assert store.character_path("../../evil").parent == (tmp_path / "state")
    assert store.get_character("../../evil").internal_state == "x"


def test_a_korean_cast_does_not_share_one_file(tmp_path):
    """Every character outside [A-Za-z0-9._-] used to become an underscore.

    A Korean cast of three-syllable names all landed on `character____.json`
    and overwrote each other's memory on every episode any of them were in.
    """
    store = StructuredStore(tmp_path / "state")
    cast = ["한병호", "나도현", "임소희", "유라엘", "김현서"]

    for index, character_id in enumerate(cast):
        store.update_character(character_id, internal_state=f"state-{index}")

    paths = {store.character_path(character_id) for character_id in cast}
    assert len(paths) == len(cast)
    for index, character_id in enumerate(cast):
        assert store.get_character(character_id).internal_state == f"state-{index}"


def test_a_korean_id_is_still_readable_in_the_filename(tmp_path):
    """`data/state/` is somewhere the author looks, not only the program."""
    store = StructuredStore(tmp_path / "state")

    assert "한병호" in store.character_path("한병호").name


def test_two_ids_that_differ_only_in_a_stripped_character_stay_apart(tmp_path):
    store = StructuredStore(tmp_path / "state")

    store.update_character("소희", internal_state="one")
    store.update_character("소희?", internal_state="two")

    assert store.get_character("소희").internal_state == "one"
    assert store.get_character("소희?").internal_state == "two"


def test_the_same_name_on_a_mac_and_on_windows_is_the_same_character(tmp_path):
    """Korean composed one way or the other must not fork the memory."""
    import unicodedata

    store = StructuredStore(tmp_path / "state")
    composed = unicodedata.normalize("NFC", "한병호")
    decomposed = unicodedata.normalize("NFD", "한병호")
    assert composed != decomposed  # otherwise this test proves nothing

    store.update_character(composed, internal_state="one")

    assert store.get_character(decomposed).internal_state == "one"


def test_a_windows_reserved_name_is_still_writable(tmp_path):
    """`nul`, `con` and friends are devices, not files, on Windows."""
    store = StructuredStore(tmp_path / "state")

    store.update_character("nul", internal_state="x")

    assert store.get_character("nul").internal_state == "x"


def test_known_characters_are_listed(store):
    store.update_character("harry-potter", internal_state="a")
    store.update_character("ron-weasley", internal_state="b")

    assert store.known_character_ids() == ["harry-potter", "ron-weasley"]


def test_story_memory_tracks_summaries_and_threads(store):
    store.record_episode_summary(1, "Harry gets his letter.", opened_threads=["who_is_hagrid"])
    store.record_episode_summary(
        2, "Hagrid explains.", resolved_threads=["who_is_hagrid"],
        world_lore_updates=["Gringotts is goblin-run."],
    )

    story = store.get_story()

    assert story.episode_summaries == {1: "Harry gets his letter.", 2: "Hagrid explains."}
    assert story.active_plot_threads == []
    assert story.resolved_plot_threads == ["who_is_hagrid"]
    assert story.world_lore_updates == ["Gringotts is goblin-run."]


def test_recent_summaries_come_back_oldest_first(store):
    for number in range(1, 6):
        store.record_episode_summary(number, f"Episode {number} happened.")

    recent = store.recent_episode_summaries(3)

    assert [number for number, _ in recent] == [3, 4, 5]


def test_character_memories_are_attached_only_on_request(store):
    store.update_character("harry-potter", internal_state="Wary.")
    store.record_episode_summary(1, "Something happened.")

    assert store.get_story().character_memories == {}
    assert "harry-potter" in store.get_story(include_characters=True).character_memories


def test_saving_the_story_does_not_duplicate_character_memories(store):
    store.update_character("harry-potter", internal_state="Wary.")
    store.save_story(store.get_story(include_characters=True))

    assert '"character_memories": {}' in store.story_path.read_text(encoding="utf-8")


def test_stores_survive_a_restart(tmp_path):
    first = StructuredStore(tmp_path / "state")
    first.update_character("harry-potter", internal_state="Wary.", episode=3)
    first.record_episode_summary(3, "The trapdoor.")

    second = StructuredStore(tmp_path / "state")

    assert second.get_character("harry-potter").internal_state == "Wary."
    assert second.get_episode_summary(3) == "The trapdoor."


# ==========================================================================
# VectorStore
# ==========================================================================

def test_world_lore_is_seeded_from_the_author_input(vector_store, world):
    count = vector_store.seed_world_lore(world)

    # overview + 3 rules + 1 location + 4 factions + 2 lore entries
    assert count == 11
    assert vector_store.count(vs.WORLD_LORE) == 11


def test_seeding_twice_does_not_duplicate(vector_store, world):
    vector_store.seed_world_lore(world)
    vector_store.seed_world_lore(world)

    assert vector_store.count(vs.WORLD_LORE) == 11


def test_list_and_dict_metadata_round_trip(vector_store):
    vector_store.add_episode_summary(
        3,
        "Harry found the trapdoor.",
        characters_involved=["harry-potter", "ron-weasley"],
        locations=["forbidden-corridor"],
        key_events=["discovered fluffy"],
        mood="tense",
    )

    stored = vector_store.get_episode_summary(3)

    assert stored.metadata["characters_involved"] == ["harry-potter", "ron-weasley"]
    assert stored.metadata["key_events"] == ["discovered fluffy"]
    assert stored.metadata["episode_number"] == 3
    assert stored.metadata["mood"] == "tense"


def test_interaction_records_carry_their_participants_and_impact(vector_store):
    stored = vector_store.add_interaction_records(
        [
            InteractionRecord(
                episode_number=7,
                scene_number=2,
                participants=["harry-potter", "ron-weasley"],
                summary="They discovered a three-headed dog on the forbidden corridor.",
                emotional_impact={"harry-potter": "intrigued", "ron-weasley": "scared"},
                plot_threads_opened=["whats_under_trapdoor"],
            )
        ]
    )

    assert stored == 1
    found = vector_store.search("trapdoor dog corridor", collections=[vs.INTERACTION_RECORDS])
    assert found[0].metadata["emotional_impact"]["ron-weasley"] == "scared"
    assert found[0].metadata["plot_threads"] == ["whats_under_trapdoor"]


def test_search_orders_by_distance_across_collections(vector_store, world):
    vector_store.seed_world_lore(world)
    vector_store.add_episode_summary(1, "Harry found the trapdoor in the forbidden corridor.")

    found = vector_store.search("trapdoor corridor", top_k=3)

    assert found[0].collection == vs.EPISODE_SUMMARIES
    assert found[0].distance <= found[-1].distance


def test_search_can_be_filtered_to_one_character(vector_store):
    vector_store.add_interaction_records(
        [
            InteractionRecord(
                episode_number=1, scene_number=1, participants=["harry-potter"],
                summary="Harry saw the trapdoor.",
            ),
            InteractionRecord(
                episode_number=1, scene_number=2, participants=["hermione-granger"],
                summary="Hermione read about the trapdoor in the library.",
            ),
        ]
    )

    found = vector_store.search("trapdoor", character_id="hermione-granger")

    assert len(found) == 1
    assert "Hermione" in found[0].document


def test_an_empty_query_returns_nothing(vector_store, world):
    vector_store.seed_world_lore(world)

    assert vector_store.search("   ") == []
    assert vector_store.search("wand", top_k=0) == []


def test_searching_empty_collections_is_harmless(vector_store):
    assert vector_store.search("anything at all") == []


def test_rendered_memories_name_their_episode(vector_store):
    vector_store.add_episode_summary(4, "The mirror showed Harry his family.")

    rendered = vector_store.search("mirror", top_k=1)[0].render()

    assert rendered.startswith("(Episode 4) ")
