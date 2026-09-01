"""Progress reporting: real pipeline events become a checklist an author can read."""

from __future__ import annotations

import pytest

from storyweaver.agents import episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import EpisodeTitle, PipelineModels
from storyweaver.agents.lore_checker import ValidationResult, Violation
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import Episode
from storyweaver.ui.progress import GenerationProgress, Stage

MAX_TURNS = 2


def _scenes(count: int) -> DirectorOutput:
    return DirectorOutput(
        scenes=[
            DraftScene(
                title=f"Scene {n}",
                objective=f"Objective {n}.",
                participating_character_ids=["harry-potter", "ron-weasley"],
            )
            for n in range(1, count + 1)
        ]
    )


def _models(scripted_llm, scene_count=2, lore=None):
    return PipelineModels(
        director=scripted_llm(DirectorOutput=lambda prompt, index: _scenes(scene_count)),
        character=scripted_llm(
            CharacterTurn=lambda prompt, index: CharacterTurn(
                type="dialogue", content="a line of dialogue"
            )
        ),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda prompt, index: SupervisorVerdict(objective_met=False)
        ),
        lore=scripted_llm(
            ValidationResult=lore
            or (lambda prompt, index: ValidationResult(passed=True, violations=[]))
        ),
        writer=scripted_llm(str=lambda prompt, index: "one two three four five"),
        titler=scripted_llm(EpisodeTitle=lambda prompt, index: EpisodeTitle(title="A Title")),
    )


@pytest.fixture
def episode_one() -> Episode:
    return Episode(episode_number=1, author_storyline="Harry meets Ron.")


def _run_with_progress(episode, world, characters, models, **kwargs):
    progress = GenerationProgress(episode_number=episode.episode_number)
    done, final = episode_runner.run_episode(
        episode,
        world,
        characters,
        models=models,
        max_turns_per_scene=MAX_TURNS,
        on_event=progress.update,
        **kwargs,
    )
    return progress, done, final


# ==========================================================================
# Streaming
# ==========================================================================

def test_streaming_reports_every_pipeline_node(episode_one, world, characters, scripted_llm):
    nodes = [
        node
        for node, _ in episode_runner.stream_episode(
            episode_one,
            world,
            characters,
            models=_models(scripted_llm),
            max_turns_per_scene=MAX_TURNS,
        )
    ]

    assert nodes[0] == "director_plan_scenes"
    assert nodes[-1] == "assemble_episode"
    assert nodes.count("write_scene") == 2
    assert "advance_scene" in nodes


def test_streaming_carries_the_accumulated_state(episode_one, world, characters, scripted_llm):
    last_state = None
    for _, state in episode_runner.stream_episode(
        episode_one, world, characters, models=_models(scripted_llm),
        max_turns_per_scene=MAX_TURNS,
    ):
        last_state = state

    assert last_state["episode"].status == "completed"
    assert len(last_state["scene_prose_outputs"]) == 2


def test_run_episode_still_returns_the_same_result(episode_one, world, characters, scripted_llm):
    done, final = episode_runner.run_episode(
        episode_one, world, characters, models=_models(scripted_llm),
        max_turns_per_scene=MAX_TURNS,
    )

    assert done.status == "completed"
    assert final["final_episode_text"] == done.final_text


def test_on_event_fires_for_every_node(episode_one, world, characters, scripted_llm):
    seen = []
    episode_runner.run_episode(
        episode_one, world, characters, models=_models(scripted_llm),
        max_turns_per_scene=MAX_TURNS, on_event=lambda node, state: seen.append(node),
    )

    assert seen[0] == "director_plan_scenes"
    assert seen[-1] == "assemble_episode"


# ==========================================================================
# The checklist
# ==========================================================================

def test_a_clean_run_produces_a_readable_checklist(
    episode_one, world, characters, scripted_llm
):
    progress, done, _ = _run_with_progress(
        episode_one, world, characters, _models(scripted_llm, scene_count=2)
    )

    rendered = [event.render() for event in progress.events]

    assert rendered[0] == "✅ Planned 2 scenes"
    assert "✅ Simulated scene 1/2 — 2 turns" in rendered
    assert "✅ Lore check scene 1/2 — passed" in rendered
    assert "✅ Wrote scene 1/2 — 5 words" in rendered
    assert "✅ Wrote scene 2/2 — 5 words" in rendered
    assert rendered[-1].startswith("✅ Assembled the episode")
    assert progress.finished is True
    assert progress.fraction() == 1.0


def test_progress_counts_scenes_as_the_director_planned_them(
    episode_one, world, characters, scripted_llm
):
    progress, _, _ = _run_with_progress(
        episode_one, world, characters, _models(scripted_llm, scene_count=4)
    )

    assert progress.scene_count == 4
    assert sum(1 for e in progress.events if e.stage is Stage.WRITING) == 4


def test_a_lore_violation_shows_as_a_warning_and_a_re_simulation(
    episode_one, world, characters, scripted_llm
):
    state = {"failed": False}

    def lore(prompt, index):
        if not state["failed"]:
            state["failed"] = True
            return ValidationResult(
                passed=False,
                violations=[
                    Violation(turn=1, category="world_rule", violated="A rule.",
                              suggested_fix="Do it differently.")
                ],
            )
        return ValidationResult(passed=True, violations=[])

    progress, done, _ = _run_with_progress(
        episode_one, world, characters, _models(scripted_llm, scene_count=1, lore=lore)
    )

    rendered = [event.render() for event in progress.events]

    assert "⚠️ Lore check scene 1/1 — 1 violation, re-running" in rendered
    assert "✅ Re-simulated scene 1/1 — 2 turns" in rendered
    assert "✅ Lore check scene 1/1 — passed" in rendered
    assert done.status == "completed"


def test_every_lore_report_is_described_exactly_once(
    episode_one, world, characters, scripted_llm
):
    """`lore_reports` accumulates across scenes; each entry must be narrated once."""
    progress, _, final = _run_with_progress(
        episode_one, world, characters, _models(scripted_llm, scene_count=3)
    )

    checks = [e for e in progress.events if e.stage is Stage.CHECKING]

    assert len(checks) == len(final["lore_reports"]) == 3
    assert [e.scene_number for e in checks] == [1, 2, 3]


def test_pending_work_is_listed_while_the_run_is_underway(
    episode_one, world, characters, scripted_llm
):
    progress = GenerationProgress(episode_number=1)
    models = _models(scripted_llm, scene_count=3)

    lines_midway = None
    for node, state in episode_runner.stream_episode(
        episode_one, world, characters, models=models, max_turns_per_scene=MAX_TURNS
    ):
        progress.update(node, state)
        if node == "write_scene" and lines_midway is None:
            lines_midway = progress.lines()

    assert lines_midway is not None
    assert any("🔄" in line for line in lines_midway)
    assert any("⬜ Scene 3/3" in line for line in lines_midway)
    assert any("⬜ Assembling final text" in line for line in lines_midway)
    # By the end, nothing is pending.
    assert not any("⬜" in line for line in progress.lines())


def test_the_fraction_only_moves_forward(episode_one, world, characters, scripted_llm):
    progress = GenerationProgress(episode_number=1)
    fractions = []

    for node, state in episode_runner.stream_episode(
        episode_one, world, characters, models=_models(scripted_llm, scene_count=2),
        max_turns_per_scene=MAX_TURNS,
    ):
        progress.update(node, state)
        fractions.append(progress.fraction())

    assert fractions == sorted(fractions)
    assert 0.0 < fractions[0] <= 1.0
    assert fractions[-1] == 1.0


def test_bookkeeping_nodes_produce_no_line(episode_one, world, characters, scripted_llm):
    progress = GenerationProgress(episode_number=1)

    assert progress.update("advance_scene", {"current_scene_index": 1}) == []
    assert progress.events == []
    assert progress.current_scene == 1


def test_a_failure_is_recorded_and_stops_the_pending_list():
    progress = GenerationProgress(episode_number=1)
    progress.update("director_plan_scenes", {"scenes": [object(), object()]})

    progress.note_failed("Generation failed: the model refused")

    lines = progress.lines()
    assert lines[-1] == "⚠️ Generation failed: the model refused"
    assert not any("⬜" in line for line in lines)


def test_recording_to_memory_is_its_own_line():
    progress = GenerationProgress(episode_number=1)
    progress.note_recorded()

    assert progress.events[-1].stage is Stage.RECORDING
    assert progress.events[-1].render() == "✅ Recorded to memory"


def test_a_single_scene_episode_reads_naturally(episode_one, world, characters, scripted_llm):
    progress, _, _ = _run_with_progress(
        episode_one, world, characters, _models(scripted_llm, scene_count=1)
    )

    assert progress.events[0].render() == "✅ Planned 1 scene"
