"""The gate between what a chapter recorded and what the story is told.

The chronicle overrides the author's own setting, so a change the summarizer
invented does not merely sit in a log — it becomes what every later chapter
believes. A proposal therefore counts for nothing until the author accepts it,
and the property that has to hold above all others is that an unreviewed entry
never reaches a prompt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.memory.summarizer import Deed, EpisodeMemory, FieldChange
from storyweaver.models import Episode
from storyweaver.ui.project import Project, ProjectStore, project_from_sample


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


def _chapter(memory: MemoryManager, project: Project, character_id: str, **kwargs):
    return memory.record_episode_completion(
        Episode(episode_number=1, title="1화", author_storyline="x",
                final_text="본문.", status="completed"),
        EpisodeMemory(
            summary="s",
            changes=[FieldChange(subject_id=character_id, section_key="appearance",
                                 value="짧게 깎은 머리", reason="싸움 중 잘림")],
            deeds=[Deed(character_id=character_id, summary="말포이와 맞붙었다.")],
        ),
        world=project.world,
        characters=project.character_map(),
        **kwargs,
    )


# ==========================================================================
# Nothing counts until it is accepted
# ==========================================================================


def test_a_chapters_records_start_out_pending(memory, loaded, harry):
    _chapter(memory, loaded, harry.id)

    assert len(memory.chronicle.pending()) == 2
    assert memory.chronicle.chain("character", harry.id, "appearance") == []


def test_a_pending_entry_does_not_reach_a_prompt(client, memory, loaded, harry):
    """The one property this whole gate exists for."""
    _chapter(memory, loaded, harry.id)

    folded = deps.folded_project()

    assert folded.character_map()[harry.id].appearance == harry.appearance


def test_accepting_makes_it_count(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)
    entry = next(e for e in memory.chronicle.pending() if e.section_key == "appearance")

    memory.chronicle.accept(entry.entry_id)

    assert deps.folded_project().character_map()[harry.id].appearance == "짧게 깎은 머리"


def test_a_discarded_proposal_is_gone_rather_than_struck_through(memory, loaded, harry):
    """Nobody accepted it, so it is not part of the story's history."""
    _chapter(memory, loaded, harry.id)
    entry = memory.chronicle.pending()[0]

    assert memory.chronicle.discard(entry.entry_id) is True
    assert memory.chronicle.get(entry.entry_id) is None


def test_an_accepted_entry_cannot_be_discarded(memory, loaded, harry):
    """Discard is for proposals. An accepted entry is retracted, not deleted."""
    _chapter(memory, loaded, harry.id)
    entry = memory.chronicle.pending()[0]
    memory.chronicle.accept(entry.entry_id)

    assert memory.chronicle.discard(entry.entry_id) is False
    assert memory.chronicle.get(entry.entry_id) is not None


def test_review_can_be_switched_off(memory, loaded, harry):
    """An author who would rather read the wiki afterwards than approve a list."""
    _chapter(memory, loaded, harry.id, review=False)

    assert memory.chronicle.pending() == []
    assert memory.chronicle.chain("character", harry.id, "appearance")[0].value == "짧게 깎은 머리"


def test_the_project_carries_the_setting(loaded):
    assert loaded.review_chronicle is True


# ==========================================================================
# The review endpoints
# ==========================================================================


def test_pending_lists_what_is_waiting(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)

    body = client.get("/api/wiki/pending").json()

    assert len(body["entries"]) == 2
    assert all(entry["pending"] for entry in body["entries"])


def test_pending_can_be_narrowed_to_one_chapter(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)
    memory.chronicle.record("world", "world", "events", "2화의 일",
                            source="episode", episode_number=2, reason="x")

    assert len(client.get("/api/wiki/pending?episode=1").json()["entries"]) == 2
    assert client.get("/api/wiki/pending?episode=2").json()["entries"] == []


def test_applying_a_review_accepts_and_discards_in_one_call(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)
    waiting = memory.chronicle.pending()
    keep = next(e for e in waiting if e.section_key == "appearance")
    drop = next(e for e in waiting if e.section_key == "deeds")

    body = client.post(
        "/api/wiki/pending/apply",
        json={"accept": [keep.entry_id], "discard": [drop.entry_id]},
    ).json()

    assert body["entries"] == []  # nothing left waiting
    assert memory.chronicle.chain("character", harry.id, "appearance")[0].value == "짧게 깎은 머리"
    assert memory.chronicle.chain("character", harry.id, "deeds") == []


def test_the_page_shows_a_pending_entry_without_counting_it(client, memory, loaded, harry):
    """The author has to see what is proposed in order to judge it."""
    _chapter(memory, loaded, harry.id)

    page = client.get(f"/api/wiki/character/{harry.id}").json()
    appearance = next(s for s in page["sections"] if s["key"] == "appearance")

    assert len(appearance["entries"]) == 1
    assert appearance["entries"][0]["pending"] is True
    assert appearance["current"] == harry.appearance  # still what the author wrote


def test_the_timeline_leaves_pending_entries_out(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)

    assert client.get("/api/wiki/timeline").json() == []


# ==========================================================================
# Regeneration
# ==========================================================================


def test_regenerating_clears_the_proposals_it_replaces(memory, loaded, harry):
    """Otherwise the author reviews two versions of the same chapter."""
    _chapter(memory, loaded, harry.id)
    _chapter(memory, loaded, harry.id)

    assert len(memory.chronicle.pending()) == 2


def test_an_accepted_entry_is_still_replaced_by_a_regeneration(memory, loaded, harry):
    _chapter(memory, loaded, harry.id)
    for entry in memory.chronicle.pending():
        memory.chronicle.accept(entry.entry_id)

    _chapter(memory, loaded, harry.id)

    assert len(memory.chronicle.by_episode(1)) == 2
    assert all(e.pending for e in memory.chronicle.by_episode(1))


# ==========================================================================
# What the author writes is never gated
# ==========================================================================


def test_an_author_entry_counts_immediately(client, loaded, harry):
    """They are the author; there is nobody to approve it."""
    page = client.post(
        f"/api/wiki/character/{harry.id}/sections/appearance/entries",
        json={"value": "작가가 정한 모습"},
    ).json()

    appearance = next(s for s in page["sections"] if s["key"] == "appearance")
    assert appearance["current"] == "작가가 정한 모습"
    assert appearance["entries"][0]["pending"] is False


def test_an_author_edit_in_the_workshop_counts_immediately(client, memory, loaded, harry):
    _chapter(memory, loaded, harry.id)
    for entry in memory.chronicle.pending():
        memory.chronicle.accept(entry.entry_id)

    edited = harry.model_copy(update={"appearance": "작가가 직접 고친 모습"})
    client.post("/api/characters", json=edited.model_dump())

    assert deps.folded_project().character_map()[harry.id].appearance == "작가가 직접 고친 모습"
