"""Outlines and plans register the settings they bring in.

A new face in episode 14's outline, a guild the Director needed for episode
20, a detail of someone's past, a moved ending — each is written into the
workshop, the world builder, the wiki and 작품기획 as soon as the text is saved,
so the next planner has heard of it.

What is *not* registered is anything that happens: that stays in the outline
until the episode is written.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import context as ctx
from storyweaver.agents import director, settings_extract
from storyweaver.agents.director import DirectorNewcomer, DirectorNewPlace, DirectorPlan
from storyweaver.agents.settings_extract import (
    CharacterFact,
    DirectionUpdate,
    ExtractedSettings,
    NewCharacter,
    NewFaction,
    NewPlace,
    WorldFact,
)
from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.memory.chronicle_store import ChronicleStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Scene
from storyweaver.models.concept import ConceptSession
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import STORY_SUBJECT_ID
from storyweaver.wiki.fold import current_value, fold_world
from storyweaver.wiki.register import extend_concept, register_settings

from tests.test_concept_api import _concept


@pytest.fixture
def chronicle(tmp_path) -> ChronicleStore:
    return ChronicleStore(tmp_path / "state")


@pytest.fixture
def project(sample_data) -> Project:
    return project_from_sample(sample_data)


def _harry(project: Project):
    return project.get_character("harry-potter")


# ==========================================================================
# Registering
# ==========================================================================


def test_a_new_character_joins_the_workshop_with_their_ties(project, chronicle):
    harry = _harry(project).name
    done = register_settings(project, chronicle, ExtractedSettings(new_characters=[
        NewCharacter(name="강소희", role="적대자 / 악역", secret="왕가의 사생아",
                     relationships=[f"{harry} — 어릴 적 원수"]),
    ]), source="14화 개요")

    added = next(c for c in project.characters if c.name == "강소희")
    assert added.role == "적대자 / 악역"
    assert added.secrets == ["왕가의 사생아"]
    assert added.relationships[0].target_character_id == "harry-potter"
    assert "인물 추가: 강소희 (적대자 / 악역)" in done.lines
    assert done.character_ids["강소희"] == added.id


def test_someone_already_in_the_cast_is_not_added_twice(project, chronicle):
    harry = _harry(project)
    count = len(project.characters)

    done = register_settings(project, chronicle, ExtractedSettings(
        new_characters=[NewCharacter(name=f" {harry.name} ")]
    ), source="3화 개요")

    assert len(project.characters) == count
    assert done.lines == []
    assert done.character_ids[harry.name] == harry.id


def test_a_fact_about_someone_is_their_setting_now(project, chronicle):
    ron = project.get_character("ron-weasley").name
    register_settings(project, chronicle, ExtractedSettings(character_facts=[
        CharacterFact(name=_harry(project).name, field="secret", value="뱀의 말을 알아듣는다"),
        CharacterFact(name=_harry(project).name, field="backstory", value="이모 집 계단 밑에서 자랐다"),
        CharacterFact(name=_harry(project).name, field="relationship", value="먼 친척", target=ron),
    ]), source="5화 기획서")

    harry = _harry(project)
    assert "뱀의 말을 알아듣는다" in harry.secrets
    assert harry.backstory.endswith("이모 집 계단 밑에서 자랐다")
    assert any(r.target_character_id == "ron-weasley" for r in harry.relationships)


def test_a_fact_on_a_field_with_a_history_joins_that_history(project, chronicle):
    """The fold reads the chronicle, so a fact written only to the sheet would
    be invisible for a field the story has already moved."""
    chronicle.record("character", "harry-potter", "goals", "살아남는다",
                     source="episode", episode_number=2, reason="쫓긴다")

    register_settings(project, chronicle, ExtractedSettings(character_facts=[
        CharacterFact(name=_harry(project).name, field="goal", value="부모의 원수를 찾는다"),
    ]), source="6화 개요")

    now = current_value(chronicle, "character", "harry-potter", "goals")
    assert "살아남는다" in now and "부모의 원수를 찾는다" in now


def test_places_rules_and_factions_reach_the_world(project, chronicle):
    register_settings(project, chronicle, ExtractedSettings(
        new_locations=[NewPlace(name="은빛 항구", description="밀수꾼의 항구")],
        new_rules=["마법은 바다 위에서 약해진다."],
        new_factions=[NewFaction(name="검은 돛 길드", description="항구를 쥔 밀수 조직")],
    ), source="20화 개요")

    assert any(p.name == "은빛 항구" for p in project.world.locations)
    assert any(r.statement == "마법은 바다 위에서 약해진다." for r in project.world.rules)
    assert "검은 돛 길드" in project.world.factions
    (faction_id,) = [sid for t, sid in chronicle.known_subjects() if t == "faction"]
    assert chronicle.get_wiki_subject("faction", faction_id).title == "검은 돛 길드"
    assert current_value(chronicle, "faction", faction_id, "description") == "항구를 쥔 밀수 조직"


def test_a_world_fact_is_a_wiki_section_every_agent_sees(project, chronicle):
    register_settings(project, chronicle, ExtractedSettings(world_facts=[
        WorldFact(title="마나석의 성질", detail="달빛에 녹는다"),
    ]), source="9화 개요")

    page = chronicle.get_wiki_subject("world", "world")
    assert [s.title for s in page.free_sections] == ["마나석의 성질"]
    world = fold_world(chronicle, project.world)
    assert "마나석의 성질: 달빛에 녹는다" in ctx.format_world_summary(world)


def test_a_changed_direction_rewrites_the_works_page(project, chronicle):
    chronicle.record("story", STORY_SUBJECT_ID, "ending", "해피엔딩", source="author")

    done = register_settings(project, chronicle, ExtractedSettings(
        direction=DirectionUpdate(ending="주인공이 왕좌를 버리고 떠난다")
    ), source="30화 개요")

    assert current_value(chronicle, "story", STORY_SUBJECT_ID, "ending") == "주인공이 왕좌를 버리고 떠난다"
    assert "작품 방향 수정: 계획된 결말" in done.lines


def test_where_each_setting_came_from_is_logged(project, chronicle):
    register_settings(project, chronicle, ExtractedSettings(
        new_rules=["밤에는 문이 닫힌다."]
    ), source="14화 개요")

    log = chronicle.chain("story", STORY_SUBJECT_ID, "decisions")
    assert log[-1].value == "[14화 개요] 규칙 추가: 밤에는 문이 닫힌다."


def test_the_concept_gains_them_too():
    concept = _concept()
    extended = extend_concept(concept, ExtractedSettings(
        new_characters=[NewCharacter(name="강소희", role="라이벌")],
        new_locations=[NewPlace(name="은빛 항구")],
        new_rules=["밤에는 문이 닫힌다."],
        direction=DirectionUpdate(arc="새 아크"),
    ))

    assert "강소희" in [c.name for c in extended.characters]
    assert "은빛 항구" in extended.locations
    assert "밤에는 문이 닫힌다." in extended.rules
    assert extended.arc == "새 아크"
    assert extended.ending == concept.ending


# ==========================================================================
# Reading the text
# ==========================================================================


@pytest.mark.real_extract
def test_the_extraction_prompt_and_answer(project):
    asked = []

    class Structured:
        def invoke(self, prompt):
            asked.append(prompt)
            return ExtractedSettings(new_rules=["규칙"])

    class Model:
        def with_structured_output(self, schema):
            assert schema is ExtractedSettings
            return Structured()

    found = settings_extract.extract(
        project, [(14, "개요", "강소희가 처음 등장한다.")], brief="결말: 떠난다", llm=Model()
    )

    assert found.new_rules == ["규칙"]
    assert "### 14화 개요\n강소희가 처음 등장한다." in asked[0]
    assert _harry(project).name in asked[0]           # the cast it compares against
    assert "Events." in asked[0]                       # and what it must leave out


def test_the_director_may_add_only_when_planning_for_the_author(episode, world, characters):
    for_author = director.build_prompt(episode, world, characters, allow_new=True)
    in_a_run = director.build_prompt(episode, world, characters)

    assert "You MAY bring in a new character" in for_author
    assert "Use ONLY the character ids" in in_a_run


# ==========================================================================
# Through the API
# ==========================================================================


class InertVectors:
    def seed_world_lore(self, world):
        return 0


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def memory(project_store) -> MemoryManager:
    return MemoryManager(vector_store=InertVectors(), data_dir=project_store.state_dir)


@pytest.fixture
def client(project_store, memory, sample_data):
    from storyweaver.server import app

    loaded = project_from_sample(sample_data)
    loaded.add_episode("해리가 항구에서 강소희를 만난다.", "1화")
    project_store.save(loaded)
    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


def _finding(monkeypatch, found: ExtractedSettings) -> list:
    calls: list = []

    def extract(project, texts, **kwargs):
        calls.append(list(texts))
        return found

    monkeypatch.setattr(settings_extract, "extract", extract)
    return calls


def test_saved_outlines_register_what_they_bring_in(client, project_store, monkeypatch):
    calls = _finding(monkeypatch, ExtractedSettings(new_characters=[NewCharacter(name="강소희")]))

    body = client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]}).json()

    assert body["registered"] == ["인물 추가: 강소희 (조연)"]
    assert [(n, label) for n, label, _ in calls[0]] == [(1, "개요")]
    assert "강소희" in [c.name for c in project_store.load().characters]


def test_an_outline_already_read_is_not_read_again(client, monkeypatch):
    calls = _finding(monkeypatch, ExtractedSettings())

    client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})
    client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})

    assert len(calls) == 1


def test_an_edited_outline_is_read_again(client, monkeypatch):
    calls = _finding(monkeypatch, ExtractedSettings())
    client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})

    client.put("/api/episodes/1", json={"author_storyline": "해리가 등대지기를 만난다."})
    client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})

    assert len(calls) == 2


def test_a_committed_concept_is_kept_in_step(client, project_store, monkeypatch):
    concepts = ConceptStore(project_store.state_dir)
    concepts.save(ConceptSession(chosen=_concept(), committed_concept=_concept(), status="committed"))
    _finding(monkeypatch, ExtractedSettings(new_rules=["밤에는 문이 닫힌다."]))

    client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})

    session = concepts.load()
    assert "밤에는 문이 닫힌다." in session.chosen.rules
    # Already in the work, so a later edit in 작품기획 has nothing to re-apply.
    assert session.chosen == session.committed_concept


def test_a_failed_read_is_reported(client, monkeypatch):
    def extract(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(settings_extract, "extract", extract)

    response = client.post("/api/episodes/extract-settings", json={"episode_numbers": [1]})

    assert response.status_code == 502


def _directed(monkeypatch, *, newcomer_name: str = "강소희"):
    def plan_episode(episode, world, characters, **kwargs):
        return DirectorPlan(
            scenes=[Scene(
                scene_number=1, title="항구", objective="만난다",
                participating_character_ids=["harry-potter", "kang"], location_id="port",
            )],
            new_characters=[DirectorNewcomer(id="kang", name=newcomer_name, role="라이벌")],
            new_locations=[DirectorNewPlace(id="port", name="은빛 항구")],
        )

    monkeypatch.setattr(director, "plan_episode", plan_episode)


def test_the_directors_newcomers_are_registered_and_cast(client, project_store, monkeypatch):
    _directed(monkeypatch)

    body = client.post("/api/episodes/1/plan").json()

    saved = project_store.load()
    kang = next(c for c in saved.characters if c.name == "강소희")
    port = next(p for p in saved.world.locations if p.name == "은빛 항구")
    scene = saved.get_episode(1).scenes[0]
    assert scene.participating_character_ids == ["harry-potter", kang.id]
    assert scene.location_id == port.id
    assert "인물 추가: 강소희 (라이벌)" in body["registered"]


def test_a_newcomer_who_is_already_in_the_cast_is_cast_as_themselves(
    client, project_store, monkeypatch
):
    ron = project_store.load().get_character("ron-weasley")
    _directed(monkeypatch, newcomer_name=ron.name)

    client.post("/api/episodes/1/plan")

    saved = project_store.load()
    assert saved.get_episode(1).scenes[0].participating_character_ids == ["harry-potter", ron.id]
    assert sum(1 for c in saved.characters if c.name == ron.name) == 1


def test_a_saved_plan_is_read_for_settings(client, monkeypatch):
    calls = _finding(monkeypatch, ExtractedSettings(new_rules=["배는 밤에 뜨지 않는다."]))

    body = client.put("/api/episodes/1/plan", json={"scenes": [{
        "title": "부두", "objective": "밀수선을 쫓는다",
        "participating_character_ids": ["harry-potter"],
        "beats": [{"description": "검은 돛 길드의 배를 본다"}],
    }]}).json()

    assert calls[0][0][1] == "기획서"
    assert "검은 돛 길드의 배를 본다" in calls[0][0][2]
    assert body["registered"] == ["규칙 추가: 배는 밤에 뜨지 않는다."]


def test_a_plan_is_saved_even_when_reading_it_fails(client, project_store, monkeypatch):
    def extract(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(settings_extract, "extract", extract)

    response = client.put("/api/episodes/1/plan", json={"scenes": [{
        "title": "부두", "objective": "쫓는다", "participating_character_ids": ["harry-potter"],
    }]})

    assert response.status_code == 200
    assert "quota exhausted" in response.json()["registration_error"]
    assert project_store.load().get_episode(1).status == "planned"
