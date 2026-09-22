"""Two ways an edit can be silently thrown away, and the guards against them.

The fold takes a section's value from the last entry in its chain, so once a
chapter has changed a field, writing that field on the model decides nothing.
An author editing 외모 in the Character Workshop would see it saved, reload and
see it there, and the next chapter would still use the chronicle's value.

And a section the author invented has no typed field at all, so unless it is
rendered into the prompt as prose it reaches the model not at all — which is
the same failure `factions` had for the whole life of the project.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.memory.summarizer import EpisodeMemory, FieldChange
from storyweaver.models import Episode, Rule
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import free_sections_text
from storyweaver.wiki.extras import HEADING


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


def _chapter_changed_appearance(memory: MemoryManager, character_id: str, project: Project):
    memory.record_episode_completion(
        Episode(episode_number=1, title="1화", author_storyline="x",
                final_text="본문.", status="completed"),
        EpisodeMemory(summary="s", changes=[
            FieldChange(subject_id=character_id, section_key="appearance",
                        value="짧게 깎은 머리", reason="싸움 중 잘림")
        ]),
        world=project.world,
        characters=project.character_map(),
        review=False,
    )


# ==========================================================================
# An edit made somewhere other than the wiki
# ==========================================================================


def test_editing_a_chronicled_field_in_the_workshop_joins_the_chain(
    client, loaded, memory, harry
):
    """Otherwise the save works, the page shows it, and the story ignores it."""
    _chapter_changed_appearance(memory, harry.id, loaded)

    edited = harry.model_copy(update={"appearance": "작가가 직접 고친 모습"})
    assert client.post("/api/characters", json=edited.model_dump()).status_code == 200

    chain = memory.chronicle.chain("character", harry.id, "appearance")
    assert [e.value for e in chain] == ["짧게 깎은 머리", "작가가 직접 고친 모습"]
    assert chain[-1].source == "author"


def test_the_edit_then_actually_takes_effect(client, loaded, memory, harry):
    _chapter_changed_appearance(memory, harry.id, loaded)

    edited = harry.model_copy(update={"appearance": "작가가 직접 고친 모습"})
    client.post("/api/characters", json=edited.model_dump())

    folded = deps.folded_project()
    assert folded.character_map()[harry.id].appearance == "작가가 직접 고친 모습"


def test_a_field_with_no_history_is_left_alone(client, loaded, memory, harry):
    """Inventing a chain for every save would fill the history with noise."""
    edited = harry.model_copy(update={"backstory": "새로 쓴 과거"})

    client.post("/api/characters", json=edited.model_dump())

    assert memory.chronicle.chain("character", harry.id, "backstory") == []


def test_saving_without_changing_anything_records_nothing(client, loaded, memory, harry):
    _chapter_changed_appearance(memory, harry.id, loaded)
    folded = deps.folded_project()
    before = len(memory.chronicle.chain("character", harry.id, "appearance"))

    client.post("/api/characters", json=folded.character_map()[harry.id].model_dump())

    assert len(memory.chronicle.chain("character", harry.id, "appearance")) == before


def test_a_relationship_edit_joins_its_own_chain(client, loaded, memory, harry, ron):
    from storyweaver.wiki import relationship_section_key

    key = relationship_section_key(ron.id)
    memory.chronicle.record("character", harry.id, key, "경계하는 상대",
                            source="episode", episode_number=1, reason="x")

    edited = harry.model_copy(update={
        "relationships": [
            r.model_copy(update={"type": "둘도 없는 친구", "description": None})
            if r.target_character_id == ron.id else r
            for r in harry.relationships
        ]
    })
    client.post("/api/characters", json=edited.model_dump())

    assert memory.chronicle.chain("character", harry.id, key)[-1].value == "둘도 없는 친구"


def test_editing_the_world_header_joins_the_chain(client, loaded, memory):
    memory.chronicle.record("world", "world", "tone", "어두움",
                            source="episode", episode_number=2, reason="전쟁")

    client.put("/api/world", json={"tone": "작가가 정한 분위기"})

    chain = memory.chronicle.chain("world", "world", "tone")
    assert chain[-1].value == "작가가 정한 분위기"
    assert chain[-1].source == "author"


def test_reviving_an_abolished_rule_joins_its_chain(client, loaded, memory):
    """A rule the story repealed, put back by the author, must take effect."""
    rule = Rule(id="secrecy", category="society", statement="마법은 비밀이다.")
    client.post("/api/world/rules", json=rule.model_dump())
    memory.chronicle.record("rule", "secrecy", "active", "폐지됨",
                            source="episode", episode_number=5, reason="공개됨")
    assert all(r.id != "secrecy" for r in deps.folded_project().world.rules)

    client.post("/api/world/rules", json=rule.model_dump())

    assert any(r.id == "secrecy" for r in deps.folded_project().world.rules)


def test_the_workshop_still_works_with_memory_off(project_store, loaded, harry):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled")
    with TestClient(app) as client:
        edited = harry.model_copy(update={"appearance": "x"})
        assert client.post("/api/characters", json=edited.model_dump()).status_code == 200
    deps.set_store(None)


# ==========================================================================
# Sections the author invented, on their way to a prompt
# ==========================================================================


def test_a_character_with_no_sections_of_their_own_adds_nothing(memory, harry):
    assert free_sections_text(memory.chronicle, "character", harry.id) == ""


def test_a_free_section_becomes_a_labelled_block(client, loaded, memory, harry):
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})
    client.post(f"/api/wiki/character/{harry.id}/sections/능력/entries",
                json={"value": "파셀텅 — 뱀과 말할 수 있다"})

    block = free_sections_text(memory.chronicle, "character", harry.id)

    assert HEADING in block
    assert "### 능력" in block
    assert "파셀텅" in block


def test_a_free_log_section_is_listed_oldest_first(client, loaded, memory, harry):
    """A 작중 행적 is a sequence; out of order it tells the wrong story."""
    client.post(f"/api/wiki/character/{harry.id}/sections",
                json={"title": "명대사", "kind": "log"})
    for line in ("첫 번째 대사", "두 번째 대사"):
        client.post(f"/api/wiki/character/{harry.id}/sections/명대사/entries",
                    json={"value": line})

    block = free_sections_text(memory.chronicle, "character", harry.id)

    assert block.index("첫 번째 대사") < block.index("두 번째 대사")


def test_an_empty_free_section_is_not_shown(client, loaded, memory, harry):
    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})

    assert free_sections_text(memory.chronicle, "character", harry.id) == ""


def test_a_free_section_reaches_the_character_prompt(
    client, loaded, memory, harry, two_character_scene, world, characters
):
    """The whole reason the author bothered to write it."""
    from storyweaver.agents import character as character_agent

    client.post(f"/api/wiki/character/{harry.id}/sections", json={"title": "능력"})
    client.post(f"/api/wiki/character/{harry.id}/sections/능력/entries",
                json={"value": "파셀텅 — 뱀과 말할 수 있다"})

    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters,
        extra_sections=free_sections_text(memory.chronicle, "character", harry.id),
    )

    assert "파셀텅" in prompt


def test_a_character_without_them_has_no_gap_in_their_prompt(
    harry, two_character_scene, world, characters
):
    from storyweaver.agents import character as character_agent

    prompt = character_agent.build_system_prompt(
        harry, two_character_scene, world, characters, extra_sections=""
    )

    assert "\n\n\n" not in prompt
    assert HEADING not in prompt
