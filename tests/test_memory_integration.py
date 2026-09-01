"""Memory wired into the episode pipeline: injected before, recorded after."""

from __future__ import annotations

from storyweaver.agents import episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import EpisodeTitle, PipelineModels
from storyweaver.agents.lore_checker import ValidationResult
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.memory.manager import NOTHING_YET
from storyweaver.memory.summarizer import (
    CharacterStateUpdate,
    EpisodeMemory,
    ThreadUpdate,
)
from storyweaver.models import Episode, InteractionRecord, Relationship

MAX_TURNS = 2


def _one_scene() -> DirectorOutput:
    return DirectorOutput(
        scenes=[
            DraftScene(
                title="The Compartment",
                objective="Harry and Ron meet.",
                participating_character_ids=["harry-potter", "ron-weasley"],
            )
        ]
    )


def _episode_memory(summary: str = "Harry met Ron and made him a promise.") -> EpisodeMemory:
    return EpisodeMemory(
        summary=summary,
        key_events=["first meeting"],
        mood="warm",
        interactions=[
            InteractionRecord(
                episode_number=0,  # the pipeline stamps the real number on
                scene_number=1,
                participants=["harry-potter", "ron-weasley"],
                summary="Harry promised Ron he would never mention the wand.",
            )
        ],
        thread_updates=[
            ThreadUpdate(
                id="rons_broken_wand",
                action="open",
                name="Ron's broken wand",
                description="Ron's wand is a hand-me-down.",
            )
        ],
        character_updates=[
            CharacterStateUpdate(
                character_id="harry-potter",
                internal_state="Determined to keep his word.",
                current_goals=["Keep Ron's secret"],
                relationship_updates=[
                    Relationship(target_character_id="ron-weasley", type="friend", sentiment=0.8)
                ],
            )
        ],
    )


def _models(scripted_llm, summary: str = "Harry met Ron and made him a promise."):
    return PipelineModels(
        director=scripted_llm(DirectorOutput=lambda prompt, index: _one_scene()),
        character=scripted_llm(
            CharacterTurn=lambda prompt, index: CharacterTurn(
                type="dialogue", content=f"line {index}"
            )
        ),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda prompt, index: SupervisorVerdict(objective_met=False)
        ),
        lore=scripted_llm(
            ValidationResult=lambda prompt, index: ValidationResult(passed=True, violations=[])
        ),
        writer=scripted_llm(str=lambda prompt, index: "The compartment smelled of soot."),
        titler=scripted_llm(EpisodeTitle=lambda prompt, index: EpisodeTitle(title="Meeting")),
        summarizer=scripted_llm(EpisodeMemory=lambda prompt, index: _episode_memory(summary)),
    )


def _run(episode, world, characters, models, memory, **kwargs):
    return episode_runner.run_episode(
        episode,
        world,
        characters,
        models=models,
        memory=memory,
        max_turns_per_scene=MAX_TURNS,
        **kwargs,
    )


def _episode(number: int, storyline: str = "Harry meets Ron on the train.") -> Episode:
    return Episode(episode_number=number, author_storyline=storyline)


# --------------------------------------------------------------------------
# Recording after completion
# --------------------------------------------------------------------------

def test_a_finished_episode_is_summarized_into_memory(world, characters, memory, scripted_llm):
    models = _models(scripted_llm)

    done, state = _run(_episode(1), world, characters, models, memory)

    assert done.status == "completed"
    assert len(models.summarizer.calls) == 1
    assert memory.get_episode_summary(1) == "Harry met Ron and made him a promise."
    assert [t.id for t in memory.get_active_plot_threads()] == ["rons_broken_wand"]
    assert memory.get_character_state("harry-potter").internal_state == (
        "Determined to keep his word."
    )
    assert state["episode_memory"].summary.startswith("Harry met Ron")


def test_recording_can_be_switched_off(world, characters, memory, scripted_llm):
    models = _models(scripted_llm)

    _run(_episode(1), world, characters, models, memory, record_memory=False)

    assert models.summarizer.calls == []
    assert memory.get_episode_summary(1) == ""


def test_a_failed_summarization_does_not_cost_the_chapter(
    world, characters, memory, scripted_llm, caplog
):
    """The prose is the expensive part; memory is best-effort on top of it."""
    models = _models(scripted_llm)
    models.summarizer = scripted_llm()  # any call raises

    done, state = _run(_episode(1), world, characters, models, memory)

    assert done.status == "completed"
    assert done.final_text
    assert "episode_memory" not in state
    assert memory.get_episode_summary(1) == ""


def test_the_pipeline_runs_without_any_memory_at_all(world, characters, scripted_llm):
    models = _models(scripted_llm)

    done, _ = episode_runner.run_episode(
        _episode(1), world, characters, models=models, max_turns_per_scene=MAX_TURNS
    )

    assert done.status == "completed"
    assert models.summarizer.calls == []


# --------------------------------------------------------------------------
# Injection before generation
# --------------------------------------------------------------------------

def test_the_first_episode_tells_every_agent_there_is_no_history(
    world, characters, memory, scripted_llm
):
    models = _models(scripted_llm)

    _run(_episode(1), world, characters, models, memory)

    # The manager supplies one consistent phrase; the agents' own fallbacks are
    # for when no MemoryManager is wired up at all.
    for prompt in (
        models.director.last_prompt,
        models.character.last_prompt,
        models.writer.last_prompt,
    ):
        assert NOTHING_YET in prompt


def test_the_second_episode_carries_the_first_into_every_prompt(
    world, characters, memory, scripted_llm
):
    _run(_episode(1), world, characters, _models(scripted_llm), memory)

    second = _models(scripted_llm, summary="They met again.")
    _run(_episode(2, "Harry and Ron meet again."), world, characters, second, memory)

    director_prompt = second.director.last_prompt
    assert "Story So Far" in director_prompt
    assert "Harry met Ron and made him a promise." in director_prompt
    assert "Ron's broken wand" in director_prompt              # active thread
    assert "Harry Potter -> Ron Weasley: friend" in director_prompt

    harry_prompts = [p for p in second.character.prompts_for(CharacterTurn)
                     if "You are Harry Potter." in p]
    assert harry_prompts
    assert "Determined to keep his word." in harry_prompts[0]
    assert "Keep Ron's secret" in harry_prompts[0]

    assert "Established Prose Tone" in second.writer.last_prompt


def test_each_character_is_told_only_their_own_memory(
    world, characters, memory, scripted_llm
):
    _run(_episode(1), world, characters, _models(scripted_llm), memory)

    second = _models(scripted_llm, summary="They met again.")
    _run(_episode(2), world, characters, second, memory)

    ron_prompts = [p for p in second.character.prompts_for(CharacterTurn)
                   if "You are Ron Weasley." in p]
    assert ron_prompts
    # Harry's private resolve is Harry's, not Ron's.
    assert "Determined to keep his word." not in ron_prompts[0]


def test_the_summarizer_is_shown_the_threads_already_open(
    world, characters, memory, scripted_llm
):
    _run(_episode(1), world, characters, _models(scripted_llm), memory)

    second = _models(scripted_llm, summary="They met again.")
    _run(_episode(2), world, characters, second, memory)

    assert "Ron's broken wand" in second.summarizer.last_prompt


def test_the_writing_language_reaches_the_summarizer(
    world, characters, memory, scripted_llm
):
    from storyweaver.models import WritingStyle

    models = _models(scripted_llm)

    _run(
        _episode(1), world, characters, models, memory,
        style=WritingStyle(language="en"),
    )

    assert "Write in en." in models.summarizer.last_prompt
