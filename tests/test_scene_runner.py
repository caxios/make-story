"""Phase 2, Tests 2 & 3: the scene simulation runs, stays in turn, and stops."""

from __future__ import annotations

import pytest

from storyweaver.agents import scene_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import InteractionEntry


def _character_only(llm_factory, turn_fn):
    """A model that plays characters and never lets the supervisor end the scene."""
    return llm_factory(
        CharacterTurn=turn_fn,
        SupervisorVerdict=lambda prompt, index: SupervisorVerdict(
            objective_met=False, reason="still building"
        ),
    )


# --------------------------------------------------------------------------
# Graph shape
# --------------------------------------------------------------------------

def test_graph_has_the_specified_nodes():
    graph = scene_runner.build_scene_graph().get_graph()
    assert {"select_next_character", "character_act", "check_scene_complete"} <= set(graph.nodes)


# --------------------------------------------------------------------------
# Turn-taking
# --------------------------------------------------------------------------

def test_two_character_scene_alternates_and_produces_a_log(
    two_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
    )

    scene, entries = scene_runner.run_scene(
        two_character_scene, world, characters, llm=llm, max_turns=6
    )

    assert [e.character_id for e in entries] == [
        "harry-potter", "ron-weasley", "harry-potter",
        "ron-weasley", "harry-potter", "ron-weasley",
    ]
    assert [e.turn for e in entries] == [1, 2, 3, 4, 5, 6]
    assert len(scene.interaction_log) == 6
    assert scene.interaction_log[0].startswith("[1] harry-potter (dialogue)")
    assert two_character_scene.interaction_log == []  # the input scene is untouched


def test_three_character_scene_round_robins_in_director_order(
    three_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="action", content=f"act {index}"),
    )

    _, entries = scene_runner.run_scene(
        three_character_scene, world, characters, llm=llm, max_turns=6
    )

    order = three_character_scene.participating_character_ids
    assert [e.character_id for e in entries] == order * 2


def test_a_directed_turn_gets_answered_next(
    three_character_scene, world, characters, scripted_llm
):
    def turn_fn(prompt, index):
        # Harry opens by addressing Hermione, who is last in the rota.
        if index == 0:
            return CharacterTurn(
                type="dialogue", content="What did the hat say to you?", directed_at="hermione-granger"
            )
        return CharacterTurn(type="dialogue", content=f"line {index}")

    llm = _character_only(scripted_llm, turn_fn)

    _, entries = scene_runner.run_scene(
        three_character_scene, world, characters, llm=llm, max_turns=4
    )

    assert entries[0].character_id == "harry-potter"
    assert entries[1].character_id == "hermione-granger"  # priority beat the rota
    assert entries[2].character_id == "ron-weasley"       # rota resumes after her


def test_a_character_never_immediately_follows_themselves(
    three_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm,
        # Every character insists on addressing Harry, including Harry.
        lambda prompt, index: CharacterTurn(
            type="dialogue", content=f"line {index}", directed_at="harry-potter"
        ),
    )

    _, entries = scene_runner.run_scene(
        three_character_scene, world, characters, llm=llm, max_turns=8
    )

    speakers = [e.character_id for e in entries]
    assert all(a != b for a, b in zip(speakers, speakers[1:]))


def test_directed_replies_do_not_starve_the_third_character(
    three_character_scene, world, characters, scripted_llm
):
    """Harry keeps addressing Hermione; Ron must still get his turns.

    Resuming the rota from whoever was pulled forward to reply would skip
    everyone sitting between the two of them.
    """

    def turn_fn(prompt, index):
        if "You are Harry Potter." in prompt:
            return CharacterTurn(
                type="dialogue", content=f"line {index}", directed_at="hermione-granger"
            )
        return CharacterTurn(type="dialogue", content=f"line {index}")

    llm = _character_only(scripted_llm, turn_fn)

    _, entries = scene_runner.run_scene(
        three_character_scene, world, characters, llm=llm, max_turns=9
    )

    speakers = [e.character_id for e in entries]
    assert set(speakers) == set(three_character_scene.participating_character_ids)
    assert speakers.count("ron-weasley") >= 2


# --------------------------------------------------------------------------
# Stopping conditions (Test 3)
# --------------------------------------------------------------------------

def test_scene_stops_at_max_turns(two_character_scene, world, characters, scripted_llm):
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
    )

    final = scene_runner.simulate_scene(
        two_character_scene, world, characters, llm=llm, max_turns=20
    )

    assert final["completed"] is True
    assert final["current_turn"] == 20
    assert len(final["interaction_log"]) == 20
    assert "max_turns" in final["stop_reason"]


def test_scene_stops_early_when_the_objective_is_met(
    two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
        SupervisorVerdict=lambda prompt, index: SupervisorVerdict(
            objective_met=True, reason="they have clearly become friends"
        ),
    )

    final = scene_runner.simulate_scene(
        two_character_scene, world, characters, llm=llm, max_turns=20
    )

    # Two participants, so the first supervisor check lands on turn 4.
    assert final["current_turn"] == 4
    assert final["completed"] is True
    assert "objective met" in final["stop_reason"]
    assert "clearly become friends" in final["stop_reason"]


def test_supervisor_is_not_consulted_before_a_full_round(
    two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
        SupervisorVerdict=lambda prompt, index: SupervisorVerdict(objective_met=True),
    )

    scene_runner.simulate_scene(two_character_scene, world, characters, llm=llm, max_turns=20)

    # One check only, at turn 4 — turns 1-3 must not have triggered one.
    assert len(llm.prompts_for(SupervisorVerdict)) == 1


def test_supervisor_sees_the_objective_and_the_log(
    two_character_scene, world, characters, scripted_llm
):
    llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
        SupervisorVerdict=lambda prompt, index: SupervisorVerdict(objective_met=True),
    )

    scene_runner.simulate_scene(two_character_scene, world, characters, llm=llm, max_turns=20)

    prompt = llm.prompts_for(SupervisorVerdict)[0]
    assert two_character_scene.objective in prompt
    assert "line 0" in prompt
    assert "Harry Potter" in prompt  # log rendered with names, not raw ids


def test_a_separate_supervisor_model_can_be_supplied(
    two_character_scene, world, characters, scripted_llm, never_done_supervisor
):
    character_llm = scripted_llm(
        CharacterTurn=lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}")
    )

    final = scene_runner.simulate_scene(
        two_character_scene,
        world,
        characters,
        llm=character_llm,
        supervisor_llm=never_done_supervisor,
        max_turns=6,
    )

    assert final["current_turn"] == 6
    # One check, at turn 4; turn 6 hits the cap before the supervisor is asked.
    assert len(never_done_supervisor.calls) == 1
    assert len(character_llm.calls) == 6          # the character model saw no supervisor calls


def test_odd_max_turns_still_terminates(two_character_scene, world, characters, scripted_llm):
    """max_turns that is not a multiple of the participant count must still cut off."""
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
    )

    final = scene_runner.simulate_scene(
        two_character_scene, world, characters, llm=llm, max_turns=7
    )

    assert final["current_turn"] == 7


# --------------------------------------------------------------------------
# Resuming a scene (used by the Phase 3 lore-retry loop)
# --------------------------------------------------------------------------

def test_a_seeded_log_is_continued_not_restarted(
    two_character_scene, world, characters, scripted_llm
):
    seed = [
        {"turn": 1, "character_id": "harry-potter", "type": "dialogue",
         "content": "kept 1", "directed_at": None},
        {"turn": 2, "character_id": "ron-weasley", "type": "dialogue",
         "content": "kept 2", "directed_at": None},
    ]
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="dialogue", content=f"new {index}"),
    )

    _, entries = scene_runner.run_scene(
        two_character_scene, world, characters, llm=llm, max_turns=4, initial_log=seed
    )

    assert [e.content for e in entries] == ["kept 1", "kept 2", "new 0", "new 1"]
    assert [e.turn for e in entries] == [1, 2, 3, 4]
    # The rota resumes past whoever spoke last in the seed.
    assert [e.character_id for e in entries[2:]] == ["harry-potter", "ron-weasley"]


def test_constraints_reach_every_character_prompt(
    two_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="dialogue", content=f"line {index}"),
    )

    scene_runner.simulate_scene(
        two_character_scene,
        world,
        characters,
        llm=llm,
        max_turns=2,
        constraints=["Draw your wand before casting."],
    )

    prompts = llm.prompts_for(CharacterTurn)
    assert len(prompts) == 2
    assert all("Draw your wand before casting." in p for p in prompts)


def test_no_constraints_says_so_explicitly(
    two_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm, lambda prompt, index: CharacterTurn(type="dialogue", content="hi")
    )

    scene_runner.simulate_scene(two_character_scene, world, characters, llm=llm, max_turns=1)

    assert "first attempt at the scene" in llm.prompts_for(CharacterTurn)[0]


def test_a_seed_that_already_fills_the_turn_budget_is_rejected(
    two_character_scene, world, characters
):
    seed = [
        {"turn": i, "character_id": "harry-potter", "type": "dialogue",
         "content": "x", "directed_at": None}
        for i in range(1, 5)
    ]

    with pytest.raises(ValueError, match="meets max_turns"):
        scene_runner.simulate_scene(
            two_character_scene, world, characters, max_turns=4, initial_log=seed
        )


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

def test_unknown_participant_is_rejected_up_front(
    two_character_scene, world, harry, scripted_llm
):
    llm = _character_only(
        scripted_llm, lambda prompt, index: CharacterTurn(type="dialogue", content="hi")
    )

    with pytest.raises(KeyError, match="ron-weasley"):
        scene_runner.simulate_scene(two_character_scene, world, [harry], llm=llm)


def test_scene_with_no_participants_is_rejected(two_character_scene, world, characters):
    empty = two_character_scene.model_copy(update={"participating_character_ids": []})

    with pytest.raises(ValueError, match="no participants"):
        scene_runner.simulate_scene(empty, world, characters)


def test_max_turns_must_be_positive(two_character_scene, world, characters):
    with pytest.raises(ValueError, match="at least 1"):
        scene_runner.simulate_scene(two_character_scene, world, characters, max_turns=0)


def test_entries_round_trip_through_state_as_plain_dicts(
    two_character_scene, world, characters, scripted_llm
):
    llm = _character_only(
        scripted_llm,
        lambda prompt, index: CharacterTurn(type="reaction", content="He goes very still."),
    )

    final = scene_runner.simulate_scene(
        two_character_scene, world, characters, llm=llm, max_turns=2
    )

    assert all(isinstance(e, dict) for e in final["interaction_log"])
    assert [InteractionEntry.model_validate(e).type for e in final["interaction_log"]] == [
        "reaction",
        "reaction",
    ]
