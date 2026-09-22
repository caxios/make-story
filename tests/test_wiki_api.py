"""The wiki: reading a page, and editing by adding to its history.

A page is assembled rather than stored — its sections come from the registry,
from the author, and from the chronicle itself. The property that matters is
that editing never overwrites: what a thing used to be survives becoming
something else, because that is what the author reads when auditing an arc.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.memory.summarizer import Deed, EpisodeMemory, FieldChange
from storyweaver.models import Episode
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import relationship_section_key


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


def _hair_cut(memory: MemoryManager, character_id: str, project: Project) -> None:
    memory.record_episode_completion(
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
        review=False,
    )


def _section(page: dict, key: str) -> dict:
    return next(s for s in page["sections"] if s["key"] == key)


# ==========================================================================
# The list
# ==========================================================================


def test_every_setting_has_a_page_from_the_moment_it_is_written(client, loaded):
    """A wiki whose pages appear only after a chapter touches them is empty
    exactly when the author most needs it."""
    rows = client.get("/api/wiki/subjects").json()

    types = {row["subject_type"] for row in rows}
    assert "character" in types and "world" in types and "rule" in types
    assert all(row["entry_count"] == 0 for row in rows)


def test_a_page_says_how_much_has_happened_to_it(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)

    rows = client.get("/api/wiki/subjects").json()
    row = next(r for r in rows if r["subject_id"] == harry.id)

    assert row["entry_count"] == 2  # the change and the deed
    assert row["last_episode"] == 1


def test_a_subject_the_chronicle_invented_still_gets_a_row(client, loaded, memory):
    """The story may name a place the author never wrote down."""
    memory.chronicle.record("location", "없던-장소", "description", "새로 나타난 곳",
                            source="episode", episode_number=2, reason="등장")

    rows = client.get("/api/wiki/subjects").json()

    assert any(r["subject_id"] == "없던-장소" for r in rows)


# ==========================================================================
# A page
# ==========================================================================


def test_a_page_shows_the_current_value_and_how_it_got_there(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)

    page = client.get(f"/api/wiki/character/{harry.id}").json()
    appearance = _section(page, "appearance")

    assert appearance["current"] == "짧게 깎은 머리"
    assert len(appearance["entries"]) == 1
    assert appearance["entries"][0]["previous"] == harry.appearance


def test_a_section_with_no_history_shows_what_the_author_wrote(client, loaded, harry):
    page = client.get(f"/api/wiki/character/{harry.id}").json()

    assert _section(page, "speech")["current"] == harry.speech_style
    assert _section(page, "speech")["entries"] == []


def test_a_log_section_has_no_current_value(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)

    deeds = _section(client.get(f"/api/wiki/character/{harry.id}").json(), "deeds")

    assert deeds["kind"] == "log"
    assert deeds["current"] == ""
    assert [e["value"] for e in deeds["entries"]] == ["말포이와 맞붙었다."]


def test_each_relationship_is_its_own_section(client, loaded, harry, ron):
    page = client.get(f"/api/wiki/character/{harry.id}").json()

    key = relationship_section_key(ron.id)
    section = _section(page, key)
    assert ron.name in section["title"]
    assert section["current"]


def test_a_retracted_entry_is_still_shown_but_not_counted(client, loaded, memory, harry):
    """An author needs to see that they took something back, not just its absence."""
    _hair_cut(memory, harry.id, loaded)
    entry = memory.chronicle.chain("character", harry.id, "appearance")[0]
    client.post(f"/api/wiki/entries/{entry.entry_id}/retract")

    appearance = _section(client.get(f"/api/wiki/character/{harry.id}").json(), "appearance")

    assert len(appearance["entries"]) == 1
    assert appearance["entries"][0]["superseded"] is True
    assert appearance["current"] == harry.appearance  # back to what it was


def test_the_world_has_a_page(client, loaded):
    page = client.get("/api/wiki/world/world").json()

    assert page["title"] == loaded.world.title
    assert _section(page, "overview")["current"] == loaded.world.overview


# ==========================================================================
# Editing is appending
# ==========================================================================


def test_an_edit_becomes_the_next_entry_rather_than_overwriting(client, loaded, harry):
    page = client.post(
        f"/api/wiki/character/{harry.id}/sections/appearance/entries",
        json={"value": "새로 정한 모습", "reason": "작가 메모"},
    ).json()

    appearance = _section(page, "appearance")
    assert appearance["current"] == "새로 정한 모습"
    assert appearance["entries"][0]["previous"] == harry.appearance
    assert appearance["entries"][0]["source"] == "author"


def test_the_first_edit_records_where_the_story_started(client, loaded, harry):
    """Otherwise the one step the author most wants to see would be missing."""
    page = client.post(
        f"/api/wiki/character/{harry.id}/sections/appearance/entries",
        json={"value": "바뀐 모습"},
    ).json()

    assert _section(page, "appearance")["entries"][0]["previous"] == harry.appearance


def test_an_empty_value_is_refused(client, loaded, harry):
    response = client.post(
        f"/api/wiki/character/{harry.id}/sections/appearance/entries",
        json={"value": "   "},
    )

    assert response.status_code == 422


def test_editing_an_unknown_section_is_a_404(client, loaded, harry):
    response = client.post(
        f"/api/wiki/character/{harry.id}/sections/그런거없음/entries",
        json={"value": "x"},
    )

    assert response.status_code == 404


def test_an_author_edit_outranks_an_earlier_episode(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)

    page = client.post(
        f"/api/wiki/character/{harry.id}/sections/appearance/entries",
        json={"value": "작가가 다시 정한 모습"},
    ).json()

    assert _section(page, "appearance")["current"] == "작가가 다시 정한 모습"


# ==========================================================================
# Sections the author adds
# ==========================================================================


def test_an_author_can_add_a_section(client, loaded, harry):
    page = client.post(
        f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"}
    ).json()

    ability = _section(page, "능력")
    assert ability["title"] == "능력"
    assert ability["author_made"] is True
    assert ability["bound_field"] is None


def test_a_free_section_holds_a_value_like_any_other(client, loaded, harry):
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})

    page = client.post(
        f"/api/wiki/character/{harry.id}/sections/능력/entries",
        json={"value": "파셀텅 — 뱀과 말할 수 있다"},
    ).json()

    assert _section(page, "능력")["current"] == "파셀텅 — 뱀과 말할 수 있다"


def test_a_free_section_can_be_a_log(client, loaded, harry):
    client.post(
        f"/api/wiki/character/{harry.id}/sections",
        json={"title": "명대사", "kind": "log"},
    )

    client.post(f"/api/wiki/character/{harry.id}/sections/명대사/entries",
                json={"value": "첫 번째"})
    page = client.post(f"/api/wiki/character/{harry.id}/sections/명대사/entries",
                       json={"value": "두 번째"}).json()

    quotes = _section(page, "명대사")
    assert [e["value"] for e in quotes["entries"]] == ["첫 번째", "두 번째"]
    assert all(e["previous"] == "" for e in quotes["entries"])


def test_a_section_cannot_shadow_a_built_in_one(client, loaded, harry):
    response = client.post(
        f"/api/wiki/character/{harry.id}/sections", json={"title": "appearance"}
    )

    assert response.status_code == 409


def test_the_same_section_cannot_be_added_twice(client, loaded, harry):
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})

    assert client.post(
        f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"}
    ).status_code == 409


def test_deleting_a_section_keeps_its_history(client, loaded, harry):
    """A wiki that lost history on a layout change would not be a record."""
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})
    client.post(f"/api/wiki/character/{harry.id}/sections/능력/entries",
                json={"value": "파셀텅"})

    page = client.delete(f"/api/wiki/character/{harry.id}/sections/능력").json()
    assert all(s["key"] != "능력" for s in page["sections"])

    # Re-adding it brings the history back into view.
    page = client.post(
        f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"}
    ).json()
    assert _section(page, "능력")["current"] == "파셀텅"


def test_a_built_in_section_cannot_be_deleted(client, loaded, harry):
    assert client.delete(
        f"/api/wiki/character/{harry.id}/sections/appearance"
    ).status_code == 404


def test_a_section_can_be_renamed(client, loaded, harry):
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})

    page = client.put(
        f"/api/wiki/character/{harry.id}/sections/능력", json={"title": "가진 힘"}
    ).json()

    assert _section(page, "능력")["title"] == "가진 힘"


# ==========================================================================
# The page's own summary
# ==========================================================================


def test_the_summary_is_editable_and_is_not_chronicled(client, loaded, harry):
    page = client.put(
        f"/api/wiki/character/{harry.id}/summary", json={"summary": "한 문단 소개."}
    ).json()

    assert page["summary"] == "한 문단 소개."
    assert client.get(f"/api/wiki/character/{harry.id}").json()["summary"] == "한 문단 소개."


# ==========================================================================
# The timeline
# ==========================================================================


def test_the_timeline_is_the_whole_story_in_order(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)
    memory.chronicle.record("world", "world", "events", "무언가 밝혀짐",
                            source="episode", episode_number=2, reason="드러남")

    timeline = client.get("/api/wiki/timeline").json()

    assert len(timeline) == 3
    assert [e["sequence"] for e in timeline] == sorted(e["sequence"] for e in timeline)


def test_the_timeline_can_be_narrowed_to_one_chapter(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)
    memory.chronicle.record("world", "world", "events", "2화의 일",
                            source="episode", episode_number=2, reason="x")

    assert len(client.get("/api/wiki/timeline?episode=1").json()) == 2
    assert len(client.get("/api/wiki/timeline?episode=2").json()) == 1


# ==========================================================================
# Retracting
# ==========================================================================


def test_an_entry_can_be_taken_back_and_put_back(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)
    entry = memory.chronicle.chain("character", harry.id, "appearance")[0]

    assert client.post(f"/api/wiki/entries/{entry.entry_id}/retract").json()["superseded"]
    assert not client.post(f"/api/wiki/entries/{entry.entry_id}/restore").json()["superseded"]


def test_an_entrys_wording_can_be_corrected(client, loaded, memory, harry):
    _hair_cut(memory, harry.id, loaded)
    entry = memory.chronicle.chain("character", harry.id, "appearance")[0]

    updated = client.put(
        f"/api/wiki/entries/{entry.entry_id}", json={"reason": "더 정확한 이유"}
    ).json()

    assert updated["reason"] == "더 정확한 이유"
    assert updated["sequence"] == entry.sequence  # its place did not move


def test_retracting_something_that_does_not_exist_is_a_404(client, loaded):
    assert client.post("/api/wiki/entries/없는아이디/retract").status_code == 404


# ==========================================================================
# Without a memory layer
# ==========================================================================


def test_the_wiki_says_so_when_memory_is_off(project_store, loaded):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled")
    with TestClient(app) as client:
        assert client.get("/api/wiki/subjects").status_code == 503
    deps.set_store(None)
