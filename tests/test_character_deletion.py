"""Deleting a character, and what the wiki keeps of them.

A concept session mints a whole cast in one go, and the author asked to be able
to change or cut those people later. Several will be cut before episode one —
they were an idea, not a person in the story, and a page for each would bury
the wiki in people the reader never met.

Someone the story actually used is the opposite case. Their episode records are
the only account of what they did while they were here, and that they were
written out is itself part of what happened. So the deciding question is not
what the author intended but what the story did: any episode entry at all, and
the page stays.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.ui.project import ProjectStore, project_from_sample
from storyweaver.wiki import forget_subject


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
def memory(tmp_path) -> MemoryManager:
    return MemoryManager(vector_store=InertVectors(), data_dir=tmp_path / "state")


@pytest.fixture
def chronicle(memory):
    return memory.chronicle


@pytest.fixture
def client(tmp_path, memory, sample_data):
    from storyweaver.server import app

    store = ProjectStore(tmp_path / "data")
    store.save(project_from_sample(sample_data))
    deps.set_store(store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


def _cast_ids(client) -> list[str]:
    return [c["id"] for c in client.get("/api/characters").json()]


# ==========================================================================
# The policy, on its own
# ==========================================================================


def test_someone_the_story_never_used_is_removed_outright(chronicle):
    """A concept-stage mistake is not history."""
    chronicle.record("character", "조연", "appearance", "키가 크다", source="author")

    kept = forget_subject(chronicle, "character", "조연")

    assert kept is False
    assert chronicle.subject("character", "조연") == []
    assert not chronicle.wiki_path("character", "조연").exists()


def test_someone_the_story_used_keeps_their_page(chronicle):
    chronicle.record("character", "시월", "appearance", "머리가 길다", source="author")
    chronicle.record(
        "character", "시월", "appearance", "머리가 잘렸다",
        source="episode", episode_number=3, reason="추격전에서 잘렸다",
    )

    kept = forget_subject(chronicle, "character", "시월", note="작가가 삭제")

    assert kept is True
    page = chronicle.get_wiki_subject("character", "시월")
    assert page.retired is True
    assert page.retired_note == "작가가 삭제"


def test_a_retired_page_still_has_everything_the_story_recorded(chronicle):
    """An author auditing episode 3 has to be able to find out who that was."""
    chronicle.record("character", "시월", "appearance", "머리가 길다", source="author")
    chronicle.record(
        "character", "시월", "appearance", "머리가 잘렸다",
        source="episode", episode_number=3, reason="추격전에서 잘렸다",
    )

    forget_subject(chronicle, "character", "시월")

    chain = chronicle.chain("character", "시월", "appearance")
    assert [e.value for e in chain] == ["머리가 길다", "머리가 잘렸다"]


def test_a_pending_episode_record_still_counts_as_the_story_using_them(chronicle):
    """It is unreviewed, not untrue — and dropping it would destroy the very
    thing the author is about to review."""
    entry = chronicle.record(
        "character", "시월", "appearance", "흉터가 생겼다",
        source="episode", episode_number=2, reason="싸움",
    )
    chronicle._replace(entry.entry_id, {"pending": True})

    assert forget_subject(chronicle, "character", "시월") is True


def test_deleting_someone_with_no_chronicle_at_all_is_not_an_error(chronicle):
    assert forget_subject(chronicle, "character", "없는사람") is False


# ==========================================================================
# Through the API
# ==========================================================================


def test_deleting_a_character_takes_their_wiki_page_with_them(client, chronicle, harry):
    client.put(
        f"/api/characters/{harry.id}",
        json=harry.model_copy(update={"appearance": "안경을 썼다"}).model_dump(mode="json"),
    )

    client.delete(f"/api/characters/{harry.id}")

    assert harry.id not in _cast_ids(client)
    assert chronicle.subject("character", harry.id) == []


def test_a_character_the_story_used_survives_deletion_as_a_record(
    client, chronicle, harry
):
    chronicle.record(
        "character", harry.id, "appearance", "흉터가 깊어졌다",
        source="episode", episode_number=1, reason="볼드모트와 마주쳤다",
    )

    client.delete(f"/api/characters/{harry.id}")

    assert harry.id not in _cast_ids(client)
    page = chronicle.get_wiki_subject("character", harry.id)
    assert page.retired is True
    assert harry.name in page.retired_note


def test_a_deleted_character_is_gone_from_the_wiki_index(client, chronicle, harry):
    chronicle.record("character", harry.id, "appearance", "안경", source="author")

    client.delete(f"/api/characters/{harry.id}")

    rows = client.get("/api/wiki/subjects").json()
    assert harry.id not in [row["subject_id"] for row in rows]


def test_deleting_someone_who_is_not_there_is_a_404(client, chronicle):
    assert client.delete("/api/characters/없는사람").status_code == 404


def test_a_deleted_character_is_dropped_from_everyone_elses_relationships(
    client, harry, ron
):
    """A dangling target would put an id into prompts that resolves to nobody."""
    client.delete(f"/api/characters/{harry.id}")

    remaining = client.get("/api/characters").json()
    for character in remaining:
        targets = [r["target_character_id"] for r in character["relationships"]]
        assert harry.id not in targets


def test_a_deleted_character_is_out_of_the_prompts(client, chronicle, harry):
    """Retired or dropped, they are out of the cast, and the cast is what the
    agents are given — so this needs no separate filtering to be true."""
    chronicle.record(
        "character", harry.id, "appearance", "흉터", source="episode",
        episode_number=1, reason="x",
    )

    client.delete(f"/api/characters/{harry.id}")

    project = deps.folded_project()
    assert all(c.id != harry.id for c in project.characters)


def test_the_page_is_only_touched_when_the_delete_succeeds(client, chronicle, harry):
    chronicle.record("character", harry.id, "appearance", "안경", source="author")

    client.delete("/api/characters/없는사람")

    assert chronicle.subject("character", harry.id) != []


def test_a_retired_page_is_still_findable_under_their_name(client, chronicle, harry):
    """Their title is normally looked up from the cast they are no longer in."""
    chronicle.record(
        "character", harry.id, "appearance", "흉터", source="episode",
        episode_number=1, reason="x",
    )

    client.delete(f"/api/characters/{harry.id}")

    row = next(
        r for r in client.get("/api/wiki/subjects").json()
        if r["subject_id"] == harry.id
    )
    assert row["title"] == harry.name
    assert row["retired"] is True


def test_the_page_says_they_were_written_out(client, chronicle, harry):
    chronicle.record(
        "character", harry.id, "appearance", "흉터", source="episode",
        episode_number=1, reason="x",
    )

    client.delete(f"/api/characters/{harry.id}")

    page = client.get(f"/api/wiki/character/{harry.id}").json()
    assert page["retired"] is True
    assert harry.name in page["retired_note"]
