"""Partial-episode recovery, and the export formats a reader actually receives."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from storyweaver import export
from storyweaver.agents import episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.checkpoint import CheckpointStore, EpisodeCheckpoint
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import SCENE_BREAK, EpisodeTitle, PipelineModels
from storyweaver.agents.lore_checker import ValidationResult
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import Episode

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


def _models(scripted_llm, scene_count=3, writer=None):
    return PipelineModels(
        director=scripted_llm(DirectorOutput=lambda p, i: _scenes(scene_count)),
        character=scripted_llm(
            CharacterTurn=lambda p, i: CharacterTurn(type="dialogue", content="a line")
        ),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda p, i: SupervisorVerdict(objective_met=False)
        ),
        lore=scripted_llm(ValidationResult=lambda p, i: ValidationResult(passed=True)),
        writer=scripted_llm(str=writer or (lambda p, i: f"Scene prose {i}.")),
        titler=scripted_llm(EpisodeTitle=lambda p, i: EpisodeTitle(title="A Title")),
        transition=scripted_llm(str=lambda p, i: "Later,"),
    )


@pytest.fixture
def checkpoints(tmp_path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "state")


def _episode(number: int = 1) -> Episode:
    return Episode(episode_number=number, author_storyline="Harry meets Ron.")


# ==========================================================================
# Checkpointing
# ==========================================================================

def test_a_completed_run_leaves_no_checkpoint_behind(
    world, characters, scripted_llm, checkpoints
):
    episode_runner.run_episode(
        _episode(), world, characters, models=_models(scripted_llm),
        max_turns_per_scene=MAX_TURNS, checkpoints=checkpoints,
    )

    assert checkpoints.load(1) is None
    assert checkpoints.pending() == []


def test_a_failure_mid_episode_leaves_the_finished_scenes_on_disk(
    world, characters, scripted_llm, checkpoints
):
    """The scenes already paid for must survive an outage in the middle."""
    def writer(prompt, index):
        if index >= 2:
            raise RuntimeError("the API went away")
        return f"Scene prose {index}."

    with pytest.raises(Exception):
        episode_runner.run_episode(
            _episode(), world, characters, models=_models(scripted_llm, writer=writer),
            max_turns_per_scene=MAX_TURNS, checkpoints=checkpoints,
        )

    saved = checkpoints.load(1)
    assert saved is not None
    assert saved.scenes_completed == 2
    assert saved.scene_prose_outputs == ["Scene prose 0.", "Scene prose 1."]
    assert len(saved.scenes) == 3          # the plan survived too
    assert saved.current_scene_index == 2  # resume at the third scene


def test_resuming_writes_only_the_scenes_that_are_missing(
    world, characters, scripted_llm, checkpoints
):
    calls = {"writer": 0, "director": 0}

    def writer(prompt, index):
        calls["writer"] += 1
        if calls["writer"] > 2 and calls["writer"] <= 3:
            raise RuntimeError("the API went away")
        return f"prose {calls['writer']}"

    models = _models(scripted_llm, writer=writer)
    with pytest.raises(Exception):
        episode_runner.run_episode(
            _episode(), world, characters, models=models,
            max_turns_per_scene=MAX_TURNS, checkpoints=checkpoints,
        )

    before = len(models.director.calls)
    resumed = _models(scripted_llm)
    done, _ = episode_runner.run_episode(
        _episode(), world, characters, models=resumed,
        max_turns_per_scene=MAX_TURNS, checkpoints=checkpoints,
    )

    assert done.status == "completed"
    assert before == 1
    assert resumed.director.calls == []  # the Director was not paid twice
    assert len(done.scenes) == 3
    assert checkpoints.load(1) is None


def test_resume_can_be_switched_off(world, characters, scripted_llm, checkpoints):
    checkpoints.save(
        EpisodeCheckpoint(
            episode_number=1,
            author_storyline="Harry meets Ron.",
            scenes=[],
            scene_prose_outputs=["stale"],
            current_scene_index=1,
        )
    )
    models = _models(scripted_llm)

    episode_runner.run_episode(
        _episode(), world, characters, models=models, max_turns_per_scene=MAX_TURNS,
        checkpoints=checkpoints, resume=False,
    )

    assert len(models.director.calls) == 1  # planned from scratch


def test_an_edited_storyline_invalidates_the_checkpoint(
    world, characters, scripted_llm, checkpoints
):
    """Different storyline, different scenes — the saved plan is the wrong plan."""
    checkpoints.save(
        EpisodeCheckpoint(
            episode_number=1,
            author_storyline="An entirely different story.",
            scenes=[],
            scene_prose_outputs=["stale prose"],
            current_scene_index=1,
        )
    )
    models = _models(scripted_llm)

    done, _ = episode_runner.run_episode(
        _episode(), world, characters, models=models,
        max_turns_per_scene=MAX_TURNS, checkpoints=checkpoints,
    )

    assert len(models.director.calls) == 1
    assert "stale prose" not in done.final_text


def test_a_corrupt_checkpoint_is_discarded_rather_than_crashing(checkpoints):
    checkpoints.directory.mkdir(parents=True)
    checkpoints.path_for(4).write_text("{ not json", encoding="utf-8")

    assert checkpoints.load(4) is None
    assert not checkpoints.path_for(4).exists()


def test_pending_checkpoints_are_listed_in_order(checkpoints):
    for number in (3, 1, 2):
        checkpoints.save(
            EpisodeCheckpoint(episode_number=number, author_storyline=f"story {number}")
        )

    assert [c.episode_number for c in checkpoints.pending()] == [1, 2, 3]


def test_running_without_checkpoints_still_works(world, characters, scripted_llm):
    done, _ = episode_runner.run_episode(
        _episode(), world, characters, models=_models(scripted_llm),
        max_turns_per_scene=MAX_TURNS,
    )

    assert done.status == "completed"


# ==========================================================================
# Export
# ==========================================================================

@pytest.fixture
def written(sample_data) -> list[Episode]:
    body = f"The ceiling churned with cloud.\n\n{SCENE_BREAK}\n\n“Potter, Harry,” she called."
    return [
        Episode(
            episode_number=1,
            title="The Sorting",
            author_storyline="Harry is sorted.",
            status="completed",
            final_text=f"[Episode 1: The Sorting]\n\n{body}\n",
        ),
        Episode(
            episode_number=2,
            title="",
            author_storyline="Potions.",
            status="completed",
            final_text="[Episode 2]\n\nSnape swept in.\n",
        ),
    ]


def test_the_assembled_header_is_not_repeated_in_exports(written):
    text = export.to_text(written[0])

    assert text.startswith("Episode 1: The Sorting")
    assert "[Episode 1" not in text
    assert "The ceiling churned" in text


def test_markdown_uses_a_heading_and_centres_scene_breaks(written):
    markdown = export.to_markdown(written[0])

    assert markdown.startswith("# Episode 1: The Sorting")
    assert f'<div align="center">{SCENE_BREAK}</div>' in markdown


def test_an_untitled_episode_still_exports(written):
    assert export.to_text(written[1]).startswith("Episode 2\n")


def test_the_full_story_has_contents_and_appendices(written, sample_data):
    from storyweaver.ui.project import project_from_sample

    project = project_from_sample(sample_data)
    story = export.assemble_story(
        "The Wizarding World", written, project.characters, project.world
    )

    assert story.startswith("# The Wizarding World")
    assert "2 episodes" in story
    assert "## Contents" in story
    assert "[Episode 1: The Sorting](#episode-1-the-sorting)" in story
    assert "## Appendix: Characters" in story
    assert "### Harry Potter" in story
    assert "## Appendix: The Wizarding World" in story
    assert "wands are required" in story.lower() or "wand" in story


def test_appendices_can_be_left_out(written, sample_data):
    from storyweaver.ui.project import project_from_sample

    project = project_from_sample(sample_data)
    story = export.assemble_story(
        "S", written, project.characters, project.world, include_appendices=False
    )

    assert "Appendix" not in story


def test_episodes_are_ordered_regardless_of_input_order(written):
    story = export.assemble_story("S", list(reversed(written)))

    assert story.index("Episode 1") < story.index("Episode 2")


def test_an_empty_story_says_so():
    assert "No episodes" in export.assemble_story("S", [])


def test_docx_export_produces_a_readable_document(written):
    data = export.to_docx(written[0])

    assert data[:2] == b"PK"  # a zip, which is what .docx is
    with zipfile.ZipFile(BytesIO(data)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "The ceiling churned with cloud." in document
    assert "Episode 1: The Sorting" in document


def test_the_whole_story_exports_to_docx(written, sample_data):
    from storyweaver.ui.project import project_from_sample

    project = project_from_sample(sample_data)
    data = export.story_to_docx(
        "The Wizarding World", written, project.characters, project.world
    )

    with zipfile.ZipFile(BytesIO(data)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert "Contents" in document
    assert "Snape swept in." in document
    assert "Appendix: Characters" in document
