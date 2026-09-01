"""Phase 6 flagship: ten episodes of the Wizarding World, end to end.

This is the whole system under load — 8 characters, 15 rules, 10 locations, 10
episodes — with every model call scripted so the arc is deterministic and the
suite still needs no API key.

What it can prove without a real model: that ten episodes generate without
error, that memory accumulates and reaches the next episode's prompts, that plot
threads open, progress and resolve across the arc, and that the finished story
assembles. What it cannot prove is prose quality — that is what
`scripts/run_wizarding_world.py` and a human reader are for.
"""

from __future__ import annotations

import json

import pytest

from storyweaver import config, export, telemetry
from storyweaver.agents import episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import EpisodeTitle, PipelineModels
from storyweaver.agents.lore_checker import ValidationResult, Violation
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.memory.summarizer import (
    CharacterStateUpdate,
    EpisodeMemory,
    ThreadUpdate,
)
from storyweaver.models import InteractionRecord, Relationship
from storyweaver.ui.project import Project, project_from_sample

MAX_TURNS = 4
SCENES_PER_EPISODE = 2

# The arc the scripted summarizer plays out: the Stone mystery is planted in
# episode 3, advanced in 6 and 9, and paid off in 10; Ron's wand is planted
# early and deliberately never touched again, so it should go stale.
THREAD_SCRIPT = {
    3: [("open", "the_stone_mystery", "What Hagrid took from the vault")],
    4: [("open", "rons_broken_wand", "Ron's hand-me-down wand")],
    6: [("progress", "the_stone_mystery", "The third-floor corridor is guarding it")],
    9: [("progress", "the_stone_mystery", "Nicolas Flamel made it")],
    10: [("resolve", "the_stone_mystery", "It is the Philosopher's Stone")],
}


@pytest.fixture(scope="module")
def wizarding_world() -> Project:
    """The flagship dataset: 8 characters, 15 rules, 10 locations, 10 episodes."""
    raw = json.loads(
        (config.EXAMPLES_DIR / "wizarding_world.json").read_text(encoding="utf-8")
    )
    return project_from_sample(raw)


# --------------------------------------------------------------------------
# The scripted cast
# --------------------------------------------------------------------------

def _director(project: Project):
    """Two scenes per episode, drawn from the episode's actual cast and places."""

    def plan(prompt, index):
        # Pick characters the prompt itself offers, so ids are always real.
        cast = [c.id for c in project.characters if c.id in prompt][:3] or ["harry-potter"]
        location = next((l.id for l in project.world.locations if l.id in prompt), None)
        return DirectorOutput(
            scenes=[
                DraftScene(
                    title=f"Scene {n}",
                    objective=f"Objective {n} of this episode.",
                    participating_character_ids=cast[:2],
                    location_id=location,
                )
                for n in range(1, SCENES_PER_EPISODE + 1)
            ]
        )

    return plan


def _character_turn(prompt, index):
    """A line that names the speaker, so voice can be checked in the log."""
    for name in ("Harry Potter", "Ron Weasley", "Hermione Granger", "Rubeus Hagrid",
                 "Albus Dumbledore", "Severus Snape", "Draco Malfoy", "Vernon Dursley"):
        if f"You are {name}." in prompt:
            return CharacterTurn(type="dialogue", content=f"{name} says something.")
    return CharacterTurn(type="action", content="Someone moves.")


def _lore_for(fail_on_episode: int | None):
    """Clean, except one deliberate violation on the given episode."""
    seen = {"failed": set()}

    def check(prompt, index):
        if fail_on_episode is not None and fail_on_episode not in seen["failed"]:
            seen["failed"].add(fail_on_episode)
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(
                        turn=1,
                        category="world_rule",
                        violated="Deliberate spellcasting requires a wand.",
                        suggested_fix="Draw your wand before casting.",
                    )
                ],
            )
        return ValidationResult(passed=True, violations=[])

    return check


def _summarizer_for(project: Project, number: int):
    """A memory record that plays the scripted thread arc for this episode."""

    def summarize(prompt, index):
        updates = []
        for action, thread_id, description in THREAD_SCRIPT.get(number, []):
            updates.append(
                ThreadUpdate(
                    id=thread_id,
                    action=action,
                    name=description,
                    description=description,
                    event=f"Episode {number}: {description}",
                    resolution=description if action == "resolve" else "",
                    linked_characters=["harry-potter"],
                )
            )
        return EpisodeMemory(
            summary=(
                f"Episode {number}. Harry and Ron were at Hogwarts. "
                f"{'The Stone mystery moved forward. ' if number in THREAD_SCRIPT else ''}"
                f"A distinctive detail from episode {number}: the number {number * 7}."
            ),
            key_events=[f"event {number}"],
            mood="tense",
            interactions=[
                InteractionRecord(
                    episode_number=number,
                    scene_number=1,
                    participants=["harry-potter", "ron-weasley"],
                    summary=f"In episode {number} Harry and Ron talked about the trapdoor.",
                )
            ],
            thread_updates=updates,
            character_updates=[
                CharacterStateUpdate(
                    character_id="harry-potter",
                    internal_state=f"After episode {number}, wary and curious.",
                    current_goals=["Find out what is under the trapdoor"],
                    relationship_updates=[
                        Relationship(
                            target_character_id="ron-weasley",
                            type="best friend",
                            sentiment=min(0.5 + number * 0.05, 1.0),
                        )
                    ],
                )
            ],
        )

    return summarize


def _models(project: Project, scripted_llm, number: int, fail_on_episode=None):
    return PipelineModels(
        director=scripted_llm(DirectorOutput=_director(project)),
        character=scripted_llm(CharacterTurn=_character_turn),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda p, i: SupervisorVerdict(objective_met=False)
        ),
        lore=scripted_llm(ValidationResult=_lore_for(fail_on_episode)),
        writer=scripted_llm(
            str=lambda p, i: f"Prose for episode {number}, passage {i}. " * 20
        ),
        titler=scripted_llm(EpisodeTitle=lambda p, i: EpisodeTitle(title=f"Chapter {number}")),
        transition=scripted_llm(str=lambda p, i: "Later that week,"),
        summarizer=scripted_llm(EpisodeMemory=_summarizer_for(project, number)),
    )


@pytest.fixture
def ten_episodes(wizarding_world, memory, scripted_llm):
    """Generate all ten episodes in order, recording usage as we go."""
    project = wizarding_world.model_copy(deep=True)
    memory.seed_world(project.world)

    per_episode = []
    with telemetry.record_usage("ten-episode arc") as usage:
        for episode in list(project.episodes):
            models = _models(
                project, scripted_llm, episode.episode_number,
                fail_on_episode=5 if episode.episode_number == 5 else None,
            )
            done, state = episode_runner.run_episode(
                episode,
                project.world,
                project.character_map(),
                style=project.style,
                models=models,
                max_turns_per_scene=MAX_TURNS,
                memory=memory,
            )
            project.update_episode(done)
            per_episode.append((done, state, models))

    return project, memory, per_episode, usage


# ==========================================================================
# Success criteria
# ==========================================================================

def test_all_ten_episodes_generate_without_error(ten_episodes):
    project, _, per_episode, _ = ten_episodes

    assert len(per_episode) == 10
    assert len(project.completed_episodes()) == 10
    for done, _, _ in per_episode:
        assert done.status == "completed"
        assert done.final_text.strip()
        assert len(done.scenes) == SCENES_PER_EPISODE
        assert all(scene.prose for scene in done.scenes)


def test_the_dataset_is_at_the_promised_scale(wizarding_world):
    assert len(wizarding_world.world.rules) == 15
    assert len(wizarding_world.world.locations) == 10
    assert len(wizarding_world.world.factions) == 4
    assert len(wizarding_world.characters) == 8
    assert len(wizarding_world.episodes) == 10


def test_no_lore_violation_slips_through_unnoticed(ten_episodes):
    """The one planted violation must be caught, re-run, and then pass."""
    _, _, per_episode, _ = ten_episodes

    reports = {
        done.episode_number: state["lore_reports"] for done, state, _ in per_episode
    }
    episode_five = reports[5]

    assert any(not r["passed"] for r in episode_five)  # it was caught
    assert episode_five[-1]["passed"]                  # and resolved by the re-run
    for number, episode_reports in reports.items():
        if number != 5:
            assert all(r["passed"] for r in episode_reports)


def test_plot_threads_open_progress_and_resolve_across_the_arc(ten_episodes):
    _, memory, _, _ = ten_episodes

    stone = memory.plot_tracker.get("the_stone_mystery")
    assert stone is not None
    assert stone.status == "resolved"
    assert stone.opened_in_episode == 3
    assert stone.resolved_in_episode == 10
    # Opened, advanced twice, then paid off.
    assert len(stone.events) == 3
    assert "Philosopher's Stone" in stone.resolution

    assert memory.plot_tracker.get("rons_broken_wand").status == "open"
    assert [t.id for t in memory.get_active_plot_threads()] == ["rons_broken_wand"]


def test_a_thread_nobody_touches_is_flagged_as_going_cold(ten_episodes):
    """Ron's wand is planted in episode 4 and never mentioned again."""
    _, memory, _, _ = ten_episodes

    stale = memory.get_stale_plot_threads(current_episode=10)

    assert [t.id for t in stale] == ["rons_broken_wand"]


def test_episode_five_remembers_episode_two(ten_episodes):
    """The continuity claim the whole memory layer exists to make."""
    _, _, per_episode, _ = ten_episodes

    _, _, models = per_episode[4]  # episode 5
    director_prompt = models.director.last_prompt

    assert "Episode 2." in director_prompt
    assert "the number 14" in director_prompt  # 2 * 7, unique to episode 2's summary


def test_the_final_episode_carries_the_whole_arc_forward(ten_episodes):
    _, _, per_episode, _ = ten_episodes

    _, _, models = per_episode[9]
    director_prompt = models.director.last_prompt

    assert "Story So Far" in director_prompt
    assert "What Hagrid took from the vault" in director_prompt   # the live thread
    assert "Threads Going Cold" in director_prompt                # the neglected one
    assert "Harry Potter -> Ron Weasley: best friend" in director_prompt


def test_each_character_only_recalls_their_own_scenes(ten_episodes):
    _, _, per_episode, _ = ten_episodes

    _, _, models = per_episode[9]
    harry = [p for p in models.character.prompts_for(CharacterTurn) if "You are Harry Potter." in p]

    assert harry
    assert "After episode 9, wary and curious." in harry[0]
    assert "Find out what is under the trapdoor" in harry[0]


def test_character_voices_stay_distinct_in_the_prompts(ten_episodes, wizarding_world):
    """Each character's own sheet reaches their own prompt, and nobody else's."""
    _, _, per_episode, _ = ten_episodes

    prompts = [
        p for _, _, models in per_episode
        for p in models.character.prompts_for(CharacterTurn)
    ]
    hagrid = [p for p in prompts if "You are Rubeus Hagrid." in p]
    snape = [p for p in prompts if "You are Severus Snape." in p]

    if hagrid:
        assert "West Country dialect" in hagrid[0]
        assert "Never shouts" not in hagrid[0]  # that is Snape's voice, not his
    if snape:
        assert "Never shouts" in snape[0]


def test_the_whole_arc_assembles_into_one_story(ten_episodes):
    project, _, _, _ = ten_episodes

    story = export.assemble_story(
        project.name, project.completed_episodes(), project.characters, project.world
    )

    assert "10 episodes" in story
    assert story.count("## Episode ") == 10
    assert "## Contents" in story
    assert "## Appendix: Characters" in story
    for character in project.characters:
        assert character.name in story


def test_cost_is_measured_per_stage(ten_episodes):
    """Benchmarking the arc is the point of the telemetry layer."""
    _, _, _, usage = ten_episodes

    stages = usage.by_stage()

    assert usage.calls > 100
    assert {"director", "character", "lore", "writer", "summarizer"} <= set(stages)
    assert stages["director"].calls == 10
    assert stages["summarizer"].calls == 10
    assert usage.total_tokens > 0
    assert usage.cost() > 0

    report = usage.report()
    assert "ten-episode arc" in report
    assert "TOTAL" in report
