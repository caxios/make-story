"""Reading an author's paragraph back as a character or a world.

These endpoints hand the author's own words to the model and return a filled-in
profile. Two things matter beyond "it parsed": nothing is saved (the author has
not seen it yet), and the ids that come back cannot collide with ids that
already mean someone — saving a character upserts by id, so a colliding id
would quietly overwrite a member of the cast.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps, parse
from storyweaver.models import CharacterProfile, WorldLore
from storyweaver.ui.project import Project, ProjectStore, project_from_sample

CHARACTER_TEXT = (
    "지민은 19세 미대생으로, 짧은 검은 머리카락에 조용하지만 강단 있는 성격이다. "
    "어릴 때부터 유나와 절친한 친구였지만, 최근 유나가 비밀을 숨기고 있다는 걸 느끼고 있다."
)

WORLD_TEXT = (
    "현대 한국 서울을 배경으로 한 스릴러. 대기업들이 정치권과 결탁해 사회를 지배한다. "
    "주요 장소는 여의도 금융타워와 강남의 지하 클럽이다."
)


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def client(project_store):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled for tests")
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)


@pytest.fixture
def loaded(project_store, sample_data) -> Project:
    project = project_from_sample(sample_data)
    project_store.save(project)
    return project


def _character(**overrides) -> CharacterProfile:
    base = {
        "id": "지민",
        "name": "지민",
        "role": "주인공",
        "age": 19,
        "appearance": "짧은 검은 머리.",
        "personality_summary": "조용하지만 강단 있다.",
        "speech_style": "담담한 평서체.",
    }
    return CharacterProfile.model_validate({**base, **overrides})


def _world(**overrides) -> WorldLore:
    base = {
        "title": "서울, 2026",
        "genre": "thriller",
        "tone": "차갑고 숨 막히는",
        "overview": "대기업이 정치권과 결탁한 현대 서울.",
    }
    return WorldLore.model_validate({**base, **overrides})


def _answers_with(monkeypatch, result, *, structured: bool = True, raw: str | None = None):
    """Stub the model. `structured=False` forces the raw-JSON fallback path."""
    calls: dict = {"structured": 0, "plain": 0, "stage": None, "prompt": ""}

    class Structured:
        def invoke(self, prompt):
            calls["structured"] += 1
            calls["prompt"] = prompt
            if not structured:
                raise RuntimeError("this model will not honour a schema")
            return result

    class Model:
        def with_structured_output(self, schema):
            return Structured()

        def invoke(self, prompt):
            calls["plain"] += 1
            calls["prompt"] = prompt

            class Response:
                content = raw

            return Response()

    def fake_get_llm(stage="unknown", **kwargs):
        calls["stage"] = stage
        return Model()

    monkeypatch.setattr(parse, "get_llm", fake_get_llm)
    return calls


# ==========================================================================
# Characters
# ==========================================================================


def test_a_description_comes_back_as_a_character(client, loaded, monkeypatch):
    calls = _answers_with(monkeypatch, _character())

    response = client.post(
        "/api/parse/character", json={"text": CHARACTER_TEXT, "existing_character_ids": []}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "지민"
    assert body["age"] == 19
    assert body["role"] in parse.ROLES
    # The author's own words reached the model.
    assert CHARACTER_TEXT in calls["prompt"]
    # And it ran on the cold stage, not the prose one.
    assert calls["stage"] == "parse"


def test_parsing_saves_nothing(client, project_store, loaded, monkeypatch):
    """The author has not seen it yet, so it is not theirs yet."""
    _answers_with(monkeypatch, _character())
    before = len(project_store.load().characters)

    client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    assert len(project_store.load().characters) == before


def test_an_id_that_belongs_to_someone_already_is_moved_aside(
    client, project_store, loaded, monkeypatch
):
    """Saving upserts by id, so a collision here would overwrite the cast."""
    existing = loaded.characters[0]
    _answers_with(monkeypatch, _character(id=existing.id, name="다른 사람"))

    body = client.post("/api/parse/character", json={"text": CHARACTER_TEXT}).json()

    assert body["id"] != existing.id
    assert body["id"].startswith(existing.id)  # recognisably derived, not random


def test_an_unsaved_id_the_browser_is_holding_also_counts(client, loaded, monkeypatch):
    _answers_with(monkeypatch, _character(id="지민"))

    body = client.post(
        "/api/parse/character",
        json={"text": CHARACTER_TEXT, "existing_character_ids": ["지민"]},
    ).json()

    assert body["id"] != "지민"


def test_an_id_with_spaces_or_capitals_is_tidied(client, loaded, monkeypatch):
    _answers_with(monkeypatch, _character(id="Park Ji Min"))

    body = client.post("/api/parse/character", json={"text": CHARACTER_TEXT}).json()

    assert body["id"] == "park-ji-min"


def test_an_empty_id_falls_back_to_the_name(client, loaded, monkeypatch):
    _answers_with(monkeypatch, _character(id="   "))

    body = client.post("/api/parse/character", json={"text": CHARACTER_TEXT}).json()

    assert body["id"] == "지민"  # Korean is kept rather than transliterated


def test_the_cast_is_named_in_the_prompt_so_the_model_can_avoid_them(
    client, loaded, monkeypatch
):
    calls = _answers_with(monkeypatch, _character())

    client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    for character in loaded.characters:
        assert character.id in calls["prompt"]


def test_an_empty_description_is_refused_before_the_model_is_called(
    client, loaded, monkeypatch
):
    """Nothing to read is not worth a model call to discover."""
    calls = _answers_with(monkeypatch, _character())

    assert client.post("/api/parse/character", json={"text": ""}).status_code == 422
    assert client.post("/api/parse/character", json={"text": "   "}).status_code == 422
    assert client.post("/api/parse/world", json={"text": "\n\t "}).status_code == 422
    assert calls["structured"] == 0  # the model was never reached


# ==========================================================================
# Worlds
# ==========================================================================


def test_a_description_comes_back_as_a_world(client, monkeypatch):
    calls = _answers_with(
        monkeypatch,
        _world(
            locations=[
                {"id": "yeouido-tower", "name": "여의도 금융타워", "description": "유리 탑."},
                {
                    "id": "gangnam-club",
                    "name": "강남 지하 클럽",
                    "description": "지하.",
                    "parent_location_id": "yeouido-tower",
                },
            ],
            rules=[{"id": "chaebol", "category": "politics", "statement": "대기업이 지배한다."}],
        ),
    )

    response = client.post("/api/parse/world", json={"text": WORLD_TEXT})

    assert response.status_code == 200
    body = response.json()
    assert body["genre"] == "thriller"
    assert [location["name"] for location in body["locations"]] == [
        "여의도 금융타워",
        "강남 지하 클럽",
    ]
    assert body["locations"][1]["parent_location_id"] == "yeouido-tower"
    assert WORLD_TEXT in calls["prompt"]


def test_parsing_a_world_saves_nothing(client, project_store, loaded, monkeypatch):
    _answers_with(monkeypatch, _world(title="완전히 다른 세계"))

    client.post("/api/parse/world", json={"text": WORLD_TEXT})

    assert project_store.load().world.title == loaded.world.title


def test_duplicate_location_ids_are_separated_and_parents_follow(client, monkeypatch):
    """Two locations sharing an id would collapse into one in the world."""
    _answers_with(
        monkeypatch,
        _world(
            locations=[
                {"id": "tower", "name": "북쪽 탑", "description": "북."},
                {"id": "tower", "name": "남쪽 탑", "description": "남."},
                {"id": "room", "name": "꼭대기 방", "description": "방.", "parent_location_id": "tower"},
            ]
        ),
    )

    body = client.post("/api/parse/world", json={"text": WORLD_TEXT}).json()

    ids = [location["id"] for location in body["locations"]]
    assert ids == ["tower", "tower-2", "room"]
    assert len(set(ids)) == 3
    # The child still points at a location that exists.
    assert body["locations"][2]["parent_location_id"] in ids


def test_a_parent_that_points_at_nothing_is_dropped_to_the_root(client, monkeypatch):
    _answers_with(
        monkeypatch,
        _world(
            locations=[
                {"id": "room", "name": "방", "description": "방.", "parent_location_id": "없는-곳"}
            ]
        ),
    )

    body = client.post("/api/parse/world", json={"text": WORLD_TEXT}).json()

    assert body["locations"][0]["parent_location_id"] is None


# ==========================================================================
# When the model will not cooperate
# ==========================================================================


def test_a_model_that_refuses_a_schema_falls_back_to_reading_its_json(
    client, loaded, monkeypatch
):
    payload = json.dumps(json.loads(_character(id="fallback").model_dump_json()))
    calls = _answers_with(
        monkeypatch, None, structured=False, raw=f"```json\n{payload}\n```"
    )

    response = client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    assert response.status_code == 200
    assert response.json()["id"] == "fallback"
    assert calls["structured"] == 1 and calls["plain"] == 1  # tried both, in order


def test_output_that_is_not_json_at_all_is_reported_as_such(client, loaded, monkeypatch):
    _answers_with(monkeypatch, None, structured=False, raw="죄송하지만 도와드릴 수 없습니다.")

    response = client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    assert response.status_code == 422
    assert "단순하게" in response.json()["detail"]  # the author is told what to do


def test_json_that_is_not_a_character_is_reported_as_such(client, loaded, monkeypatch):
    _answers_with(monkeypatch, None, structured=False, raw='{"nickname": "지민"}')

    response = client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    assert response.status_code == 422


def test_a_dead_model_is_a_bad_gateway_rather_than_a_crash(client, loaded, monkeypatch):
    class Dead:
        def with_structured_output(self, schema):
            raise RuntimeError("no schema support")

        def invoke(self, prompt):
            raise RuntimeError("quota exhausted")

    monkeypatch.setattr(parse, "get_llm", lambda **kwargs: Dead())

    response = client.post("/api/parse/character", json={"text": CHARACTER_TEXT})

    assert response.status_code == 502
    assert "quota exhausted" in response.json()["detail"]


# ==========================================================================
# Wiring
# ==========================================================================


def test_both_endpoints_are_registered_under_the_parse_tag(client):
    schema = client.get("/openapi.json").json()

    assert "/api/parse/character" in schema["paths"]
    assert "/api/parse/world" in schema["paths"]
    assert schema["paths"]["/api/parse/character"]["post"]["tags"] == ["parse"]
