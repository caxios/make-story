"""The work's own wiki page: what the novel is, and where it is going.

A logline, a premise, an arc and a planned ending belong to no character, place
or rule — and above all they do not belong to the world.

`context.format_world_summary` is rendered into five prompts: the Director's,
the Character Agent's, the Lore Checker's, the Writer's and the Summarizer's.
Keeping the plan on the world page would put the ending in front of every
character, and they would play their scenes already knowing it. That failure
shows up in no single chapter — it shows up as nobody ever being surprised — so
it is tested here harder than anything else.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import character as character_agent
from storyweaver.agents import context, lore_checker
from storyweaver.agents.writer import _character_sheets
from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import STORY_SUBJECT_ID

ENDING = "동혁이 사념세계에 남고 시월이 현세계로 건너온다"
ARC = "1부 만남과 은폐, 2부 사념세계 진입, 3부 두 세계의 경계가 무너짐"


class InertVectors:
    def add_episode_summary(self, *a, **k):
        return None

    def add_interaction_records(self, records):
        return 0

    def add_lore(self, *a, **k):
        return None

    def seed_world_lore(self, world):
        return 0


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def memory(tmp_path) -> MemoryManager:
    return MemoryManager(vector_store=InertVectors(), data_dir=tmp_path / "state")


@pytest.fixture
def client(project_store, memory):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


@pytest.fixture
def loaded(project_store, sample_data) -> Project:
    project = project_from_sample(sample_data)
    project_store.save(project)
    return project


@pytest.fixture
def planned(client, loaded, memory) -> None:
    """A work with its arc and ending written down."""
    for key, value in (("arc", ARC), ("ending", ENDING), ("logline", "평범한 학생과 구미호")):
        client.post(
            f"/api/wiki/story/{STORY_SUBJECT_ID}/sections/{key}/entries",
            json={"value": value},
        )


def _section(page: dict, key: str) -> dict:
    return next(s for s in page["sections"] if s["key"] == key)


# ==========================================================================
# The plan must not leak into the prose
# ==========================================================================


def test_the_plan_is_not_part_of_the_world(client, loaded, planned):
    """Nothing written on the story page reaches `WorldLore`."""
    world = client.get("/api/world").json()

    blob = str(world)
    assert ENDING not in blob
    assert ARC not in blob


def test_the_world_summary_every_agent_sees_does_not_carry_the_ending(
    client, loaded, planned
):
    summary = context.format_world_summary(deps.folded_project().world)

    assert ENDING not in summary
    assert ARC not in summary


def test_a_character_does_not_know_how_the_story_ends(
    client, loaded, planned, harry, two_character_scene, world, characters
):
    """A character who has read the ending stops being surprised by it."""
    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, deps.folded_project().world, characters
    )

    assert ENDING not in prompt
    assert ARC not in prompt


def test_the_writer_does_not_know_how_the_story_ends(
    client, loaded, planned, harry, ron, characters
):
    sheets = _character_sheets(characters, [harry.id, ron.id], harry.id)

    assert ENDING not in sheets


def test_the_lore_checker_does_not_judge_scenes_against_the_plan(
    client, loaded, planned, two_character_scene, characters
):
    """It would flag every chapter for not having reached the ending yet."""
    prompt = lore_checker.build_prompt(
        [], deps.folded_project().world, characters, scene=two_character_scene
    )

    assert ENDING not in prompt
    assert ARC not in prompt


# ==========================================================================
# The page itself
# ==========================================================================


def test_the_work_has_a_page_from_the_start(client, loaded):
    page = client.get(f"/api/wiki/story/{STORY_SUBJECT_ID}").json()

    keys = [s["key"] for s in page["sections"]]
    assert keys == ["logline", "premise", "arc", "ending", "episodes", "decisions"]


def test_the_page_is_named_after_the_work_not_the_project(client, loaded):
    """They diverge once a concept names the novel, and the page is the work's."""
    page = client.get(f"/api/wiki/story/{STORY_SUBJECT_ID}").json()

    assert page["title"] == loaded.world.title


def test_an_unnamed_project_still_gets_a_readable_title(project_store, memory):
    from storyweaver.server import app

    blank = Project(name="   ")
    blank.world = blank.world.model_copy(update={"title": "   "})
    project_store.save(blank)
    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as client:
        page = client.get(f"/api/wiki/story/{STORY_SUBJECT_ID}").json()
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")

    assert page["title"] == "작품 기획"


def test_the_work_comes_first_in_the_wiki(client, loaded):
    """It is what an author opens the wiki to remember."""
    rows = client.get("/api/wiki/subjects").json()

    assert rows[0]["subject_type"] == "story"


def test_every_section_starts_empty(client, loaded):
    """There is no typed model behind a plan, so there is nothing to inherit."""
    page = client.get(f"/api/wiki/story/{STORY_SUBJECT_ID}").json()

    assert all(section["current"] == "" for section in page["sections"])
    assert all(section["bound_field"] is None for section in page["sections"])


# ==========================================================================
# Writing on it
# ==========================================================================


def test_the_author_can_write_the_arc_by_hand(client, loaded):
    page = client.post(
        f"/api/wiki/story/{STORY_SUBJECT_ID}/sections/arc/entries",
        json={"value": ARC},
    ).json()

    assert _section(page, "arc")["current"] == ARC


def test_changing_the_arc_keeps_what_it_was(client, loaded, planned):
    """The plan changes over a long serial; how it changed is worth keeping."""
    page = client.post(
        f"/api/wiki/story/{STORY_SUBJECT_ID}/sections/arc/entries",
        json={"value": "3부를 통째로 다시 짬", "reason": "2부가 길어져서"},
    ).json()

    arc = _section(page, "arc")
    assert arc["current"] == "3부를 통째로 다시 짬"
    assert [e["value"] for e in arc["entries"]] == [ARC, "3부를 통째로 다시 짬"]
    assert arc["entries"][1]["previous"] == ARC


def test_the_episode_outline_accumulates(client, loaded):
    """One rough line per episode, in order — not a value that replaces itself."""
    for line in ("1화 — 시월이 학교로 찾아온다.", "2화 — 정체를 들킬 뻔한다."):
        page = client.post(
            f"/api/wiki/story/{STORY_SUBJECT_ID}/sections/episodes/entries",
            json={"value": line},
        ).json()

    episodes = _section(page, "episodes")
    assert [e["value"] for e in episodes["entries"]] == [
        "1화 — 시월이 학교로 찾아온다.",
        "2화 — 정체를 들킬 뻔한다.",
    ]
    assert all(entry["previous"] == "" for entry in episodes["entries"])


def test_the_author_can_add_a_section_of_their_own(client, loaded):
    page = client.post(
        f"/api/wiki/story/{STORY_SUBJECT_ID}/sections", json={"title": "참고 작품"}
    ).json()

    assert _section(page, "참고-작품")["author_made"] is True


def test_the_page_survives_a_reload(client, loaded, planned):
    page = client.get(f"/api/wiki/story/{STORY_SUBJECT_ID}").json()

    assert _section(page, "ending")["current"] == ENDING
