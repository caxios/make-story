"""Phase 3 end-to-end: storyline in, finished chapter out — including the retry loop."""

from __future__ import annotations

import pytest

from storyweaver.agents import episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import (
    MAX_LORE_RETRIES,
    SCENE_BREAK,
    EpisodeTitle,
    PipelineModels,
)
from storyweaver.agents.lore_checker import ValidationResult, Violation
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import StoryBeat, WritingStyle

MAX_TURNS = 4


def _two_scenes() -> DirectorOutput:
    return DirectorOutput(
        scenes=[
            DraftScene(
                title="The Compartment",
                objective="Harry and Ron meet.",
                participating_character_ids=["harry-potter", "ron-weasley"],
                beats=[StoryBeat(description="Ron asks to sit down.", mood="awkward")],
            ),
            DraftScene(
                title="The Sorting",
                objective="The hat hesitates over Harry.",
                participating_character_ids=["harry-potter", "hermione-granger"],
                location_id="great-hall",
            ),
        ]
    )


def _models(scripted_llm, *, lore, prose="Prose for the scene.", title="The Sorting"):
    """One fake per pipeline stage, so each stage's calls stay countable."""
    return PipelineModels(
        director=scripted_llm(DirectorOutput=lambda prompt, index: _two_scenes()),
        character=scripted_llm(
            CharacterTurn=lambda prompt, index: CharacterTurn(
                type="dialogue", content=f"line {index}"
            )
        ),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda prompt, index: SupervisorVerdict(objective_met=False)
        ),
        lore=scripted_llm(ValidationResult=lore),
        writer=scripted_llm(str=lambda prompt, index: f"{prose} ({index})"),
        titler=scripted_llm(EpisodeTitle=lambda prompt, index: EpisodeTitle(title=title)),
        # Its own fake, so the Writer's call count stays about scenes.
        transition=scripted_llm(str=lambda prompt, index: "Later that afternoon,"),
    )


@pytest.fixture
def untitled(episode):
    """The sample episode ships with a title; auto-titling only fires without one."""
    return episode.model_copy(update={"title": ""})


def _always_clean(prompt, index):
    return ValidationResult(passed=True, violations=[])


def _run(episode, world, characters, models, **kwargs):
    return episode_runner.run_episode(
        episode, world, characters, models=models, max_turns_per_scene=MAX_TURNS, **kwargs
    )


# --------------------------------------------------------------------------
# Graph shape
# --------------------------------------------------------------------------

def test_graph_has_every_specified_node():
    nodes = set(episode_runner.build_episode_graph().get_graph().nodes)
    assert {
        "director_plan_scenes",
        "simulate_scene",
        "check_lore",
        "rerun_scene",
        "write_scene",
        "advance_scene",
        "assemble_episode",
    } <= nodes


# --------------------------------------------------------------------------
# Test 1: end-to-end single episode
# --------------------------------------------------------------------------

def test_end_to_end_produces_a_finished_chapter(untitled, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)

    done, state = _run(untitled, world, characters, models)

    assert done.status == "completed"
    assert len(done.scenes) == 2
    assert all(scene.prose for scene in done.scenes)
    assert all(scene.interaction_log for scene in done.scenes)
    assert done.final_text == state["final_episode_text"]
    assert done.final_text.startswith("[Episode 1: The Sorting]")
    assert "Later that afternoon," in done.final_text  # the seam is bridged
    for scene in done.scenes:
        assert scene.prose in done.final_text


def test_every_stage_is_exercised_once_per_scene(untitled, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)

    _run(untitled, world, characters, models)

    assert len(models.director.calls) == 1
    assert len(models.lore.calls) == 2        # one clean check per scene
    assert len(models.writer.calls) == 2      # one prose pass per scene
    assert len(models.transition.calls) == 1  # one seam between two scenes
    assert len(models.titler.calls) == 1
    assert len(models.character.calls) == 2 * MAX_TURNS


def test_the_input_episode_is_not_mutated(episode, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)

    _run(episode, world, characters, models)

    assert episode.scenes == []
    assert episode.final_text == ""
    assert episode.status == "queued"


def test_an_author_supplied_title_is_kept(episode, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)
    titled = episode.model_copy(update={"title": "The Boy Who Lived"})

    done, _ = _run(titled, world, characters, models)

    assert done.title == "The Boy Who Lived"
    assert done.final_text.startswith("[Episode 1: The Boy Who Lived]")
    assert models.titler.calls == []


def test_auto_title_can_be_switched_off(untitled, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)

    done, _ = _run(untitled, world, characters, models, auto_title=False)

    assert done.title == ""
    assert done.final_text.startswith("[Episode 1]")
    assert models.titler.calls == []


def test_writing_style_reaches_the_writer(episode, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)
    style = WritingStyle(language="en", prose_density="sparse", author_style_notes="Terse.")

    _run(episode, world, characters, models, style=style)

    prompt = models.writer.last_prompt
    assert "in en." in prompt
    assert "Lean and quick" in prompt
    assert "Terse." in prompt


# --------------------------------------------------------------------------
# Test 2: lore checker rejection and the retry loop
# --------------------------------------------------------------------------

def _fail_then_pass(fail_times: int, turn: int = 3):
    """A Lore Checker that objects `fail_times` times, then accepts."""
    state = {"failures": 0}

    def lore(prompt, index):
        if state["failures"] < fail_times:
            state["failures"] += 1
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        turn=turn,
                        category="world_rule",
                        violated="Deliberate spellcasting requires a wand.",
                        suggested_fix="Draw your wand before casting.",
                    )
                ],
            )
        return ValidationResult(passed=True, violations=[])

    return lore


def test_a_violation_triggers_a_rerun_that_then_passes(
    episode, world, characters, scripted_llm
):
    models = _models(scripted_llm, lore=_fail_then_pass(1))

    done, state = _run(episode, world, characters, models)

    reports = [r for r in state["lore_reports"] if r["scene_number"] == 1]
    assert [r["passed"] for r in reports] == [False, True]
    assert reports[0]["first_bad_turn"] == 3
    assert done.scenes[0].prose  # the scene was written after the retry
    assert done.status == "completed"


def test_the_suggested_fix_is_injected_into_the_character_prompt(
    episode, world, characters, scripted_llm
):
    models = _models(scripted_llm, lore=_fail_then_pass(1))

    _run(episode, world, characters, models)

    rerun_prompts = [p for p in models.character.prompts_for(CharacterTurn)
                     if "Draw your wand before casting." in p]
    assert rerun_prompts, "no character prompt carried the Lore Checker's fix"
    assert "world rule" in rerun_prompts[0]


def test_the_rerun_keeps_the_turns_before_the_violation(
    episode, world, characters, scripted_llm
):
    """Turns 1-2 were already validated; only turn 3 onward is redone."""
    models = _models(scripted_llm, lore=_fail_then_pass(1, turn=3))

    done, _ = _run(episode, world, characters, models)

    log = done.scenes[0].interaction_log
    assert len(log) == MAX_TURNS
    assert log[0].startswith("[1] ")
    assert "line 0" in log[0]   # the original opening survived the re-run
    assert "line 1" in log[1]
    assert "line 0" not in log[2]  # turn 3 was re-rolled


def test_retries_stop_after_the_maximum_and_the_scene_is_accepted(
    episode, world, characters, scripted_llm, caplog
):
    models = _models(scripted_llm, lore=_fail_then_pass(99))  # never satisfied

    done, state = _run(episode, world, characters, models)

    scene_one = [r for r in state["lore_reports"] if r["scene_number"] == 1]
    assert len(scene_one) == MAX_LORE_RETRIES + 1  # first check plus two retries
    assert not any(r["passed"] for r in scene_one)
    assert done.status == "completed"
    assert done.scenes[0].prose  # accepted with warnings rather than abandoned


def test_a_violation_in_one_scene_does_not_burden_the_next(
    episode, world, characters, scripted_llm
):
    """The retry budget and the injected fixes reset when the pipeline advances."""
    models = _models(scripted_llm, lore=_fail_then_pass(1))

    _, state = _run(episode, world, characters, models)

    scene_two = [r for r in state["lore_reports"] if r["scene_number"] == 2]
    assert [r["attempt"] for r in scene_two] == [1]
    assert state["retry_count"] == 0
    assert state["constraints"] == []


# --------------------------------------------------------------------------
# Assembly and validation
# --------------------------------------------------------------------------

def test_a_bridged_seam_uses_the_transition(untitled, world, characters, scripted_llm):
    models = _models(scripted_llm, lore=_always_clean)

    done, state = _run(untitled, world, characters, models)

    body = done.final_text.split("]\n\n", 1)[1].rstrip("\n")
    first, second = state["scene_prose_outputs"]
    assert body == f"{first}\n\nLater that afternoon,\n\n{second}"


def test_an_unbridged_seam_falls_back_to_the_scene_break(
    untitled, world, characters, scripted_llm
):
    """With transitions off — or when one fails — the divider does the work."""
    models = _models(scripted_llm, lore=_always_clean)

    done, state = _run(untitled, world, characters, models, transitions=False)

    body = done.final_text.split("]\n\n", 1)[1].rstrip("\n")
    assert body == f"\n\n{SCENE_BREAK}\n\n".join(state["scene_prose_outputs"])
    assert models.transition.calls == []


def test_a_failing_transition_does_not_lose_the_episode(
    untitled, world, characters, scripted_llm
):
    models = _models(scripted_llm, lore=_always_clean)
    models.transition = scripted_llm()  # any call raises

    done, _ = _run(untitled, world, characters, models)

    assert done.status == "completed"
    assert SCENE_BREAK in done.final_text


def test_episode_without_a_storyline_is_rejected(episode, world, characters):
    blank = episode.model_copy(update={"author_storyline": "   "})

    with pytest.raises(ValueError, match="author_storyline"):
        episode_runner.run_episode(blank, world, characters)


def test_episode_without_characters_is_rejected(episode, world):
    with pytest.raises(ValueError, match="at least one character"):
        episode_runner.run_episode(episode, world, {})


def test_a_director_that_returns_nothing_usable_fails_loudly(
    episode, world, characters, scripted_llm
):
    models = _models(scripted_llm, lore=_always_clean)
    models.director = scripted_llm(
        DirectorOutput=lambda prompt, index: DirectorOutput(
            scenes=[
                DraftScene(
                    title="Nobody",
                    objective="No known cast.",
                    participating_character_ids=["voldemort"],
                )
            ]
        )
    )

    with pytest.raises(RuntimeError, match="no usable scenes"):
        _run(episode, world, characters, models)
