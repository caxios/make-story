"""The project layer: what the UI does to a story, minus the UI."""

from __future__ import annotations

import json

import pytest

from storyweaver.models import CharacterProfile, Location, Rule
from storyweaver.ui.project import (
    Project,
    ProjectStore,
    load_sample_project,
    project_from_sample,
)


@pytest.fixture
def sample_project(sample_data) -> Project:
    return project_from_sample(sample_data)


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


# ==========================================================================
# Loading
# ==========================================================================

def test_the_bundled_sample_loads_as_a_project(sample_project):
    assert sample_project.name == "The Wizarding World"
    assert len(sample_project.characters) == 3
    assert len(sample_project.episodes) == 1
    assert sample_project.world.rules


def test_load_sample_project_reads_from_disk():
    assert load_sample_project().get_character("harry-potter") is not None


def test_an_empty_project_is_usable(project_store):
    project = project_store.load()

    assert project.characters == []
    assert project.next_episode_number() == 1
    assert project.next_queued_episode() is None
    assert project.stats().total_words == 0


# ==========================================================================
# Characters
# ==========================================================================

def test_upsert_replaces_in_place(sample_project):
    harry = sample_project.get_character("harry-potter")
    sample_project.upsert_character(harry.model_copy(update={"name": "H. Potter"}))

    assert len(sample_project.characters) == 3
    assert sample_project.get_character("harry-potter").name == "H. Potter"
    assert sample_project.characters[0].id == "harry-potter"  # order preserved


def test_removing_a_character_removes_relationships_pointing_at_them(sample_project):
    """A dangling target would put an unresolvable id into every prompt."""
    assert any(
        r.target_character_id == "ron-weasley"
        for c in sample_project.characters
        for r in c.relationships
    )

    sample_project.remove_character("ron-weasley")

    assert sample_project.get_character("ron-weasley") is None
    assert not any(
        r.target_character_id == "ron-weasley"
        for c in sample_project.characters
        for r in c.relationships
    )


def test_cloning_copies_deeply(sample_project):
    clone = sample_project.clone_character("harry-potter", "draco-malfoy", "Draco Malfoy")

    assert clone.id == "draco-malfoy"
    assert clone.name == "Draco Malfoy"
    assert len(clone.traits) == len(sample_project.get_character("harry-potter").traits)

    clone.traits[0].name = "changed"
    assert sample_project.get_character("harry-potter").traits[0].name != "changed"


def test_cloning_rejects_a_duplicate_id(sample_project):
    with pytest.raises(ValueError, match="already exists"):
        sample_project.clone_character("harry-potter", "ron-weasley", "Ron II")


def test_cloning_an_unknown_character_raises(sample_project):
    with pytest.raises(KeyError):
        sample_project.clone_character("nobody", "x", "X")


# ==========================================================================
# World
# ==========================================================================

def test_rules_upsert_and_delete(sample_project):
    sample_project.upsert_rule(Rule(id="rule-new", category="magic", statement="A new rule."))
    assert len(sample_project.world.rules) == 4

    sample_project.upsert_rule(Rule(id="rule-new", category="magic", statement="Revised."))
    assert len(sample_project.world.rules) == 4
    assert sample_project.world.rules[-1].statement == "Revised."

    sample_project.remove_rule("rule-new")
    assert len(sample_project.world.rules) == 3


def test_removing_a_location_reparents_its_children(sample_project):
    sample_project.upsert_location(
        Location(id="hogwarts", name="Hogwarts", description="A castle.")
    )
    sample_project.upsert_location(
        Location(id="dais", name="The dais", description="Raised.", parent_location_id="great-hall")
    )

    sample_project.remove_location("great-hall")

    assert sample_project.world.locations[-1].parent_location_id is None


def test_location_tree_nests_children_under_parents(sample_project):
    sample_project.upsert_location(
        Location(id="hogwarts", name="Hogwarts", description="A castle.")
    )
    sample_project.upsert_location(
        Location(id="dais", name="The dais", description="Raised.", parent_location_id="great-hall")
    )

    tree = sample_project.location_tree()

    assert [(depth, loc.id) for depth, loc in tree] == [
        (0, "hogwarts"),
        (1, "great-hall"),
        (2, "dais"),
    ]


def test_a_location_whose_parent_is_missing_sits_at_the_root(sample_project):
    # The sample's great-hall names a parent that is not in the world.
    tree = sample_project.location_tree()

    assert [(depth, loc.id) for depth, loc in tree] == [(0, "great-hall")]


def test_a_cycle_in_the_hierarchy_still_lists_every_location():
    project = Project()
    project.upsert_location(Location(id="a", name="A", description="", parent_location_id="b"))
    project.upsert_location(Location(id="b", name="B", description="", parent_location_id="a"))

    assert {loc.id for _, loc in project.location_tree()} == {"a", "b"}


# ==========================================================================
# Episode queue
# ==========================================================================

def test_adding_episodes_numbers_them_in_order():
    project = Project()

    first = project.add_episode("Harry gets his letter.")
    second = project.add_episode("Diagon Alley.", title="Shopping")

    assert (first.episode_number, second.episode_number) == (1, 2)
    assert second.title == "Shopping"
    assert project.next_queued_episode() is first


def test_moving_an_episode_renumbers_the_queue():
    project = Project()
    project.add_episode("first")
    project.add_episode("second")
    project.add_episode("third")

    project.move_episode(3, -1)

    assert [e.author_storyline for e in project.episodes] == ["first", "third", "second"]
    assert [e.episode_number for e in project.episodes] == [1, 2, 3]


def test_moving_off_the_end_does_nothing():
    project = Project()
    project.add_episode("only")

    project.move_episode(1, -1)
    project.move_episode(1, 1)

    assert [e.episode_number for e in project.episodes] == [1]


def test_moving_an_unknown_episode_raises():
    with pytest.raises(KeyError):
        Project().move_episode(7, 1)


def test_deleting_then_renumbering_closes_the_gap():
    project = Project()
    for text in ("first", "second", "third"):
        project.add_episode(text)

    project.remove_episode(2)
    project.renumber_episodes()

    assert [(e.episode_number, e.author_storyline) for e in project.episodes] == [
        (1, "first"),
        (2, "third"),
    ]


def test_batch_add_splits_on_the_separator():
    project = Project()

    added = project.add_episodes_from_text(
        "Harry gets his letter.\n---\nDiagon Alley.\n---\n\n---\nThe train."
    )

    assert len(added) == 3  # the empty section is skipped
    assert [e.episode_number for e in added] == [1, 2, 3]


def test_next_queued_skips_completed_episodes():
    project = Project()
    project.add_episode("first")
    project.add_episode("second")
    project.update_episode(project.episodes[0].model_copy(update={"status": "completed"}))

    assert project.next_queued_episode().episode_number == 2


def test_stats_count_only_completed_words():
    project = Project()
    project.add_episode("first")
    project.add_episode("second")
    project.update_episode(
        project.episodes[0].model_copy(
            update={"status": "completed", "final_text": "one two three four"}
        )
    )

    stats = project.stats(open_thread_count=3)

    assert stats.episodes_total == 2
    assert stats.episodes_completed == 1
    assert stats.episodes_queued == 1
    assert stats.total_words == 4
    assert stats.open_thread_count == 3


# ==========================================================================
# Persistence (Test 2)
# ==========================================================================

def test_a_project_round_trips_through_disk(project_store, sample_project):
    sample_project.add_episode("A new outline.")
    project_store.save(sample_project)

    reloaded = ProjectStore(project_store.data_dir).load()

    assert reloaded.name == sample_project.name
    assert len(reloaded.characters) == 3
    assert reloaded.get_character("harry-potter").speech_style == (
        sample_project.get_character("harry-potter").speech_style
    )
    assert [e.author_storyline for e in reloaded.episodes][-1] == "A new outline."
    assert reloaded.style == sample_project.style


def test_a_corrupt_project_file_does_not_break_the_app(project_store):
    project_store.data_dir.mkdir(parents=True)
    project_store.path.write_text("{not json at all", encoding="utf-8")

    project = project_store.load()

    assert project.characters == []


def test_reset_clears_the_project_and_its_memory(project_store, sample_project):
    project_store.save(sample_project)
    project_store.state_dir.mkdir(parents=True)
    (project_store.state_dir / "story_memory.json").write_text("{}", encoding="utf-8")

    project_store.reset()

    assert project_store.load().characters == []
    assert not project_store.state_dir.exists()


def test_reset_can_keep_memory(project_store, sample_project):
    project_store.save(sample_project)
    project_store.state_dir.mkdir(parents=True)
    (project_store.state_dir / "story_memory.json").write_text("{}", encoding="utf-8")

    project_store.reset(keep_memory=True)

    assert project_store.state_dir.exists()


# ==========================================================================
# Import / export
# ==========================================================================

def test_export_and_import_round_trip_with_memory(project_store, sample_project):
    project_store.save(sample_project)
    project_store.state_dir.mkdir(parents=True)
    (project_store.state_dir / "plot_threads.json").write_text(
        json.dumps({"threads": []}), encoding="utf-8"
    )

    archive = project_store.export_zip(sample_project)

    target = ProjectStore(project_store.data_dir.parent / "restored")
    restored = target.import_zip(archive)

    assert restored.name == sample_project.name
    assert len(restored.characters) == 3
    assert (target.state_dir / "plot_threads.json").is_file()


def test_export_can_leave_memory_out(project_store, sample_project):
    project_store.state_dir.mkdir(parents=True)
    (project_store.state_dir / "plot_threads.json").write_text("{}", encoding="utf-8")

    archive = project_store.export_zip(sample_project, include_memory=False)

    target = ProjectStore(project_store.data_dir.parent / "restored")
    target.import_zip(archive)

    assert not (target.state_dir / "plot_threads.json").exists()


def test_importing_a_zip_without_a_project_is_rejected(project_store, tmp_path):
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nonsense.txt", "hello")

    with pytest.raises(ValueError, match="does not contain"):
        project_store.import_zip(buffer.getvalue())


def test_an_archive_cannot_write_outside_the_project(project_store, sample_project):
    """A path-traversal entry must be skipped, not followed."""
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("project.json", sample_project.model_dump_json())
        archive.writestr("../../escaped.txt", "should not be written")

    project_store.import_zip(buffer.getvalue())

    assert not (project_store.data_dir.parent.parent / "escaped.txt").exists()
    assert project_store.load().name == sample_project.name


def test_a_character_import_replaces_by_id(sample_project):
    incoming = CharacterProfile(
        id="harry-potter",
        name="Harry J. Potter",
        appearance="-",
        personality_summary="-",
        speech_style="-",
    )

    sample_project.upsert_character(incoming)

    assert len(sample_project.characters) == 3
    assert sample_project.get_character("harry-potter").name == "Harry J. Potter"
