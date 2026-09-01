"""Every model must instantiate, serialize to JSON, and round-trip without loss."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storyweaver.models import (
    CharacterMemory,
    CharacterProfile,
    Episode,
    InteractionRecord,
    Location,
    Relationship,
    Rule,
    Scene,
    StoryBeat,
    StoryMemory,
    Trait,
    WorldLore,
)

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "examples" / "harry_potter_sample.json"


def _round_trip(instance):
    """Serialize to JSON and back; the result must equal the original."""
    restored = type(instance).model_validate_json(instance.model_dump_json())
    assert restored == instance
    return restored


# --- character -------------------------------------------------------------

def test_trait_round_trip():
    _round_trip(Trait(name="courageous", intensity=0.9, description="Acts first."))


def test_relationship_round_trip():
    _round_trip(Relationship(target_character_id="hermione-granger", type="friend", sentiment=0.6))


def test_character_profile_round_trip():
    profile = CharacterProfile(
        id="harry-potter",
        name="Harry Potter",
        aliases=["The Boy Who Lived"],
        age=11,
        appearance="Small and thin, untidy black hair.",
        personality_summary="Quietly brave, stubbornly loyal.",
        traits=[Trait(name="courageous")],
        speech_style="Plain and informal.",
        values=["loyalty"],
        goals=["Belong somewhere"],
        relationships=[Relationship(target_character_id="hermione-granger", type="friend")],
        secrets=["His scar prickles."],
    )
    restored = _round_trip(profile)
    assert restored.traits[0].intensity == 0.8  # default preserved
    assert restored.gender is None


def test_character_profile_requires_core_fields():
    with pytest.raises(ValueError):
        CharacterProfile(id="x", name="X")


def test_mutable_defaults_are_not_shared():
    a = CharacterProfile(
        id="a", name="A", appearance="-", personality_summary="-", speech_style="-"
    )
    b = CharacterProfile(
        id="b", name="B", appearance="-", personality_summary="-", speech_style="-"
    )
    a.aliases.append("Alpha")
    assert b.aliases == []


# --- world -----------------------------------------------------------------

def test_rule_round_trip():
    _round_trip(Rule(id="rule-wand", category="magic", statement="A wand is required.", exceptions=["Accidental magic."]))


def test_location_round_trip():
    _round_trip(
        Location(
            id="great-hall",
            name="The Great Hall",
            description="Cavernous, candlelit.",
            parent_location_id="hogwarts",
            notable_features=["Enchanted ceiling"],
        )
    )


def test_world_lore_round_trip():
    world = WorldLore(
        title="The Wizarding World",
        genre="fantasy",
        tone="whimsical",
        era="1990s Britain",
        overview="A hidden magical society.",
        rules=[Rule(id="r1", category="magic", statement="Wands are required.")],
        locations=[Location(id="great-hall", name="The Great Hall", description="Candlelit.")],
        factions=["Hogwarts"],
        additional_lore={"currency": "Galleons"},
    )
    restored = _round_trip(world)
    assert restored.additional_lore["currency"] == "Galleons"


# --- episode ---------------------------------------------------------------

def test_story_beat_round_trip():
    _round_trip(StoryBeat(description="The hat hesitates.", involved_character_ids=["harry-potter"], mood="tense"))


def test_scene_round_trip():
    scene = Scene(
        scene_number=1,
        title="The Sorting",
        location_id="great-hall",
        participating_character_ids=["harry-potter", "hermione-granger"],
        objective="Establish Harry's unwanted fame.",
        beats=[StoryBeat(description="The hat hesitates.")],
        interaction_log=["Hermione talks nonstop."],
        prose="The ceiling churned with cloud.",
    )
    _round_trip(scene)


def test_episode_round_trip_and_defaults():
    episode = Episode(episode_number=1, author_storyline="Harry arrives at Hogwarts.")
    restored = _round_trip(episode)
    assert restored.status == "queued"
    assert restored.scenes == []
    assert restored.title == ""


# --- memory ----------------------------------------------------------------

def test_interaction_record_round_trip():
    _round_trip(
        InteractionRecord(
            episode_number=1,
            scene_number=1,
            participants=["harry-potter", "hermione-granger"],
            summary="They meet and irritate each other.",
            emotional_impact={"harry-potter": "annoyed but curious"},
            plot_threads_opened=["Why did the hat hesitate?"],
        )
    )


def test_character_memory_round_trip():
    _round_trip(
        CharacterMemory(
            character_id="harry-potter",
            interaction_history=[
                InteractionRecord(
                    episode_number=1, scene_number=1, participants=["harry-potter"], summary="Sorted."
                )
            ],
            relationship_updates=[Relationship(target_character_id="hermione-granger", type="friend", sentiment=0.3)],
            internal_state="Overwhelmed.",
        )
    )


def test_story_memory_round_trip_with_int_keys():
    memory = StoryMemory(
        active_plot_threads=["Why did the hat hesitate?"],
        episode_summaries={1: "Harry is sorted."},
        character_memories={"harry-potter": CharacterMemory(character_id="harry-potter")},
    )
    restored = _round_trip(memory)
    # JSON object keys are strings; Pydantic must coerce them back to int.
    assert restored.episode_summaries[1] == "Harry is sorted."


# --- sample data -----------------------------------------------------------

def test_sample_file_validates_against_models():
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

    world = WorldLore.model_validate(raw["world"])
    assert len(world.rules) == 3
    assert len(world.locations) == 1

    characters = [CharacterProfile.model_validate(c) for c in raw["characters"]]
    assert {c.id for c in characters} == {"harry-potter", "hermione-granger", "ron-weasley"}

    episodes = [Episode.model_validate(e) for e in raw["episodes"]]
    assert len(episodes) == 1
    assert episodes[0].episode_number == 1

    # Referential integrity of the sample.
    character_ids = {c.id for c in characters}
    for character in characters:
        for rel in character.relationships:
            assert rel.target_character_id in character_ids
