"""The Character Agent's prompt must carry the character, and only their character."""

from __future__ import annotations

from storyweaver.agents import character as character_agent
from storyweaver.agents.character import CharacterTurn
from storyweaver.models import InteractionEntry


def test_system_prompt_contains_the_character_sheet(harry, two_character_scene, world, characters):
    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters
    )

    assert prompt.startswith("You are Harry Potter.")
    assert harry.personality_summary in prompt
    assert harry.speech_style in prompt
    assert "courageous" in prompt                    # traits
    assert harry.goals[0] in prompt
    assert harry.secrets[0] in prompt
    assert two_character_scene.objective in prompt
    assert "Ron Weasley (ron-weasley)" in prompt     # who else is present
    assert "Ron asks to share the compartment." in prompt  # beats


def test_system_prompt_only_shows_relationships_present_in_the_scene(
    harry, two_character_scene, three_character_scene, world, characters
):
    # Harry's only defined relationship is with Hermione, who is absent here.
    two_char = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters
    )
    assert "hermione-granger" not in two_char

    three_char = character_agent.build_system_prompt(
        harry, three_character_scene, world, characters
    )
    assert "hermione-granger" in three_char


def test_system_prompt_resolves_the_location(harry, three_character_scene, world, characters):
    prompt = character_agent.build_system_prompt(
        harry, three_character_scene, world, characters
    )
    assert "The Great Hall" in prompt


def test_opening_speaker_is_told_the_scene_is_empty(harry, two_character_scene, world, characters):
    prompt = character_agent.build_system_prompt(harry, two_character_scene, world, characters)
    assert "nothing yet" in prompt


def test_history_window_is_bounded(harry, two_character_scene, world, characters):
    log = [
        InteractionEntry(turn=i, character_id="ron-weasley", type="dialogue", content=f"line {i}")
        for i in range(1, 21)
    ]

    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters, log, history_limit=5
    )

    assert "line 20" in prompt
    assert "line 15" not in prompt


def test_act_returns_a_numbered_interaction_entry(
    harry, two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(
            type="dialogue", content="  Sorry — is anyone sitting here?  ", directed_at="ron-weasley"
        )
    )

    entry = character_agent.act(
        harry, two_character_scene, world, characters, turn=7, llm=llm
    )

    assert entry.turn == 7
    assert entry.character_id == "harry-potter"
    assert entry.type == "dialogue"
    assert entry.content == "Sorry — is anyone sitting here?"  # whitespace stripped
    assert entry.directed_at == "ron-weasley"


def test_act_drops_a_directed_at_that_is_not_in_the_scene(
    harry, two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(
            type="dialogue", content="Hello?", directed_at="hermione-granger"
        )
    )

    entry = character_agent.act(harry, two_character_scene, world, characters, llm=llm)

    assert entry.directed_at is None


def test_act_drops_a_character_directing_at_themselves(
    harry, two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(
            type="thought", content="I hope he doesn't stare at my scar.", directed_at="harry-potter"
        )
    )

    entry = character_agent.act(harry, two_character_scene, world, characters, llm=llm)

    assert entry.directed_at is None
    assert entry.type == "thought"
