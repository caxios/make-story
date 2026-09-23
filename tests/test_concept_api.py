"""The concept session: on disk, and the one call that writes to the project.

Two things carry the weight. A session survives a browser restart, because
working out what a novel is takes more than one sitting. And committing is
refused on a project that already has a story in it — committing over one
would replace the world, append a second cast and a second queue, and leave
the author with no way to tell by looking what had happened.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import concept as agent
from storyweaver.api import concept as route
from storyweaver.concept_store import ConceptStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models.concept import (
    ConceptCharacter,
    ConceptEpisode,
    ConceptOutline,
    ConceptProposals,
    StoryConcept,
)
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import STORY_SUBJECT_ID


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
    return MemoryManager(vector_store=InertVectors(), data_dir=tmp_path / "data" / "state")


@pytest.fixture
def client(project_store, memory):
    from storyweaver.api import deps
    from storyweaver.server import app

    project_store.save(Project(name="새 이야기"))
    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


@pytest.fixture
def store(project_store) -> ConceptStore:
    return ConceptStore(project_store.state_dir)


def _character(name: str, **overrides) -> ConceptCharacter:
    base = {
        "name": name,
        "role": "조연",
        "age": 17,
        "appearance": "평범하다.",
        "personality": "눈에 띄는 걸 싫어한다.",
        "speech": "담담한 평서체.",
        "goal": "살아남는다",
        "secret": "사실 겁이 많다",
    }
    return ConceptCharacter.model_validate({**base, **overrides})


def _concept(**overrides) -> StoryConcept:
    base = {
        "title": "사념세계의 문",
        "logline": "평범한 고등학생이 구미호와 얽혀 두 세계를 오간다.",
        "genre": "fantasy",
        "tone": "차갑고 위태로운",
        "era": "현대",
        "premise": "현세계와 사념세계가 맞닿아 있다.",
        "arc": "1부 만남, 2부 진입, 3부 경계가 무너짐.",
        "ending": "동혁이 사념세계에 남는다.",
        "rules": ["사념세계의 존재는 비밀이다.", "게이트는 밤에만 열린다."],
        "locations": ["학교", "차원게이트"],
        "factions": ["사념 추적자"],
        "characters": [
            _character("박동혁", role="주인공", relationships=["시월 — 경계하는 상대"]),
            _character("시월", role="연인 / 히로인", age=27),
        ],
        "episodes": [
            ConceptEpisode(number=1, line="시월이 학교로 찾아온다."),
            ConceptEpisode(number=2, line="정체를 들킬 뻔한다."),
        ],
    }
    return StoryConcept.model_validate({**base, **overrides})


@pytest.fixture
def stubbed(monkeypatch):
    """The agent, without a model behind it."""
    calls: dict = {"propose": 0, "outline": 0, "refine": 0}

    def propose(seed="", count=3, llm=None):
        calls["propose"] += 1
        calls["seed"] = seed
        return [_concept(title=f"제안 {i}", episodes=[]) for i in range(count)]

    def outline(concept, count=12, llm=None):
        calls["outline"] += 1
        calls["episodes"] = count
        return concept.model_copy(
            update={
                "episodes": [
                    ConceptEpisode(number=n, line=f"{n}화 구상") for n in range(1, count + 1)
                ]
            }
        )

    def refine(concept, instruction, llm=None):
        calls["refine"] += 1
        revised = concept.model_copy(update={"tone": "완전히 달라진 분위기"})
        return revised, agent.describe_changes(concept, revised)

    monkeypatch.setattr(route.agent, "propose", propose)
    monkeypatch.setattr(route.agent, "outline", outline)
    monkeypatch.setattr(route.agent, "refine", refine)
    return calls


# ==========================================================================
# The session on disk
# ==========================================================================


def test_there_is_no_session_until_one_is_started(client):
    assert client.get("/api/concept").json()["session"] is None


def test_proposing_opens_a_session(client, stubbed):
    body = client.post("/api/concept/propose", json={"seed": "학원물", "count": 3}).json()

    assert body["session"]["status"] == "proposing"
    assert len(body["session"]["proposals"]) == 3
    assert stubbed["seed"] == "학원물"


def test_a_session_survives_a_restart(client, stubbed, store):
    """Working out what a novel is takes more than one sitting."""
    client.post("/api/concept/propose", json={})

    reopened = ConceptStore(store.data_dir).load()

    assert reopened is not None
    assert len(reopened.proposals) == 3


def test_a_session_can_be_thrown_away(client, stubbed):
    client.post("/api/concept/propose", json={})

    assert client.delete("/api/concept").status_code == 204
    assert client.get("/api/concept").json()["session"] is None


def test_an_unreadable_session_does_not_take_the_app_down(client, stubbed, store):
    """A session is worth much less than the project."""
    client.post("/api/concept/propose", json={})
    store.path.write_text("{ broken", encoding="utf-8")

    assert client.get("/api/concept").json()["session"] is None


# ==========================================================================
# Choosing, and the outline
# ==========================================================================


def test_choosing_keeps_one_and_draws_its_outline(client, stubbed):
    client.post("/api/concept/propose", json={})

    body = client.post("/api/concept/choose", json={"index": 1, "episodes": 8}).json()

    assert body["session"]["status"] == "refining"
    assert body["session"]["chosen"]["title"] == "제안 1"
    assert len(body["session"]["chosen"]["episodes"]) == 8
    assert stubbed["outline"] == 1


def test_the_outline_is_drawn_once_not_for_the_whole_spread(client, stubbed):
    """Two dozen lines written to be thrown away, and it starved the last
    concept when it was all asked for in one call."""
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    assert stubbed["propose"] == 1
    assert stubbed["outline"] == 1


def test_choosing_a_proposal_that_is_not_there_is_a_404(client, stubbed):
    client.post("/api/concept/propose", json={})

    assert client.post("/api/concept/choose", json={"index": 9}).status_code == 404


def test_the_outline_can_be_redrawn_at_a_different_length(client, stubbed):
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0, "episodes": 5})

    body = client.post("/api/concept/outline", json={"episodes": 20}).json()

    assert len(body["session"]["chosen"]["episodes"]) == 20
    assert any("회차 수" in line for line in body["changed"])


# ==========================================================================
# Refining
# ==========================================================================


def test_refining_before_choosing_is_refused(client, stubbed):
    client.post("/api/concept/propose", json={})

    response = client.post("/api/concept/refine", json={"instruction": "더 어둡게"})

    assert response.status_code == 409


def test_an_empty_instruction_is_refused_before_the_model(client, stubbed):
    """It would spend a call to return roughly what it was given."""
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    assert client.post("/api/concept/refine", json={"instruction": "   "}).status_code == 422
    assert stubbed["refine"] == 0


def test_every_refinement_is_kept_as_a_turn(client, stubbed):
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    for instruction in ("더 어둡게", "주인공을 어리게", "결말을 바꿔"):
        body = client.post("/api/concept/refine", json={"instruction": instruction}).json()

    instructions = [t["instruction"] for t in body["session"]["turns"]]
    assert instructions[-3:] == ["더 어둡게", "주인공을 어리게", "결말을 바꿔"]


def test_a_refinement_reports_what_moved(client, stubbed):
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    body = client.post("/api/concept/refine", json={"instruction": "분위기를 바꿔"}).json()

    assert any("분위기" in line for line in body["changed"])


def test_refining_without_a_session_is_a_404(client):
    assert client.post("/api/concept/refine", json={"instruction": "x"}).status_code == 404


# ==========================================================================
# Committing — the one call that writes
# ==========================================================================


@pytest.fixture
def ready(client, stubbed, monkeypatch):
    """A session refined to the point of commit."""
    monkeypatch.setattr(
        route.agent, "outline", lambda concept, count=12, llm=None: _concept()
    )
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})
    return client


def test_committing_fills_the_world(ready, project_store):
    ready.post("/api/concept/commit")

    world = project_store.load().world
    assert world.title == "사념세계의 문"
    assert world.tone == "차갑고 위태로운"
    assert world.overview == "현세계와 사념세계가 맞닿아 있다."
    assert world.factions == ["사념 추적자"]
    assert len(world.rules) == 2
    assert len(world.locations) == 2


def test_a_rules_id_is_cut_where_words_end(client, stubbed, monkeypatch, project_store):
    """The Lore Checker cites rules by id and the author reads them.

    A character slice of a Korean sentence ends mid-word, and the id is
    permanent — it goes into prompts and into the World Builder.
    """
    long_rule = "던전의 마력 소비 효율은 장부로 추적할 수 있으며 위조가 불가능하다."
    monkeypatch.setattr(
        route.agent, "outline", lambda c, count=12, llm=None: _concept(rules=[long_rule])
    )
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    client.post("/api/concept/commit")

    rule = project_store.load().world.rules[0]
    assert rule.id == "던전의-마력-소비-효율은"
    assert rule.statement == long_rule  # the rule itself is not truncated


def test_two_rules_that_open_the_same_way_still_get_their_own_id(
    client, stubbed, monkeypatch, project_store
):
    monkeypatch.setattr(
        route.agent,
        "outline",
        lambda c, count=12, llm=None: _concept(
            rules=["마법은 비밀이다. 예외는 없다.", "마법은 비밀이다. 다만 왕실은 안다."]
        ),
    )
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    client.post("/api/concept/commit")

    ids = [rule.id for rule in project_store.load().world.rules]
    assert len(ids) == len(set(ids))


def test_committing_fills_the_cast(ready, project_store):
    ready.post("/api/concept/commit")

    cast = project_store.load().characters
    assert [c.name for c in cast] == ["박동혁", "시월"]
    assert cast[0].role == "주인공"
    assert cast[0].goals == ["살아남는다"]
    assert cast[0].secrets == ["사실 겁이 많다"]


def test_a_relationship_resolves_to_an_id_that_exists(ready, project_store):
    """A dangling id would put a name into prompts that resolves to nobody."""
    ready.post("/api/concept/commit")

    project = project_store.load()
    ids = {c.id for c in project.characters}
    hero = next(c for c in project.characters if c.name == "박동혁")

    assert hero.relationships[0].target_character_id in ids
    assert hero.relationships[0].type == "경계하는 상대"


def test_a_relationship_naming_nobody_is_dropped_and_reported(client, stubbed, monkeypatch):
    monkeypatch.setattr(
        route.agent,
        "outline",
        lambda concept, count=12, llm=None: _concept(
            characters=[_character("박동혁", relationships=["없는사람 — 친구"]), _character("시월")]
        ),
    )
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    body = client.post("/api/concept/commit").json()

    assert body["dropped"]


def test_committing_fills_the_queue(ready, project_store):
    ready.post("/api/concept/commit")

    episodes = project_store.load().episodes
    assert [e.episode_number for e in episodes] == [1, 2]
    assert episodes[0].author_storyline == "시월이 학교로 찾아온다."


def test_committing_writes_the_works_own_page(ready, memory):
    ready.post("/api/concept/commit")

    logline = memory.chronicle.chain("story", STORY_SUBJECT_ID, "logline")
    arc = memory.chronicle.chain("story", STORY_SUBJECT_ID, "arc")
    episodes = memory.chronicle.chain("story", STORY_SUBJECT_ID, "episodes")

    assert logline[0].value.startswith("평범한 고등학생")
    assert arc[0].value.startswith("1부 만남")
    assert len(episodes) == 2


def test_everything_lands_as_a_first_entry_the_author_can_change(ready, memory):
    """The point of committing here rather than straight into the models."""
    ready.post("/api/concept/commit")

    for entry in memory.chronicle.chain("story", STORY_SUBJECT_ID, "arc"):
        assert entry.source == "author"
        assert entry.pending is False


def test_the_reasoning_is_kept_alongside_the_result(client, stubbed, monkeypatch, memory):
    """Otherwise the arc arrives looking like it was always obvious."""
    monkeypatch.setattr(route.agent, "outline", lambda c, count=12, llm=None: _concept())
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})
    client.post("/api/concept/refine", json={"instruction": "분위기를 더 어둡게"})

    client.post("/api/concept/commit")

    decisions = memory.chronicle.chain("story", STORY_SUBJECT_ID, "decisions")
    assert any("분위기를 더 어둡게" in entry.value for entry in decisions)


def test_committing_marks_the_session_done(ready):
    ready.post("/api/concept/commit")

    session = ready.get("/api/concept").json()["session"]
    assert session["status"] == "committed"
    assert session["committed_at"] is not None


def test_committing_does_not_call_the_model(ready, stubbed):
    before = dict(stubbed)

    ready.post("/api/concept/commit")

    assert stubbed["propose"] == before["propose"]
    assert stubbed["outline"] == before["outline"]
    assert stubbed["refine"] == before["refine"]


# ==========================================================================
# Committing over an existing novel
# ==========================================================================


def test_committing_over_an_existing_story_is_refused(
    client, stubbed, monkeypatch, project_store, sample_data
):
    """It would replace the world and append a second cast, quietly."""
    monkeypatch.setattr(route.agent, "outline", lambda c, count=12, llm=None: _concept())
    project_store.save(project_from_sample(sample_data))
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    response = client.post("/api/concept/commit")

    assert response.status_code == 409
    assert "초기화" in response.json()["detail"]


def test_a_refused_commit_changes_nothing(
    client, stubbed, monkeypatch, project_store, sample_data
):
    monkeypatch.setattr(route.agent, "outline", lambda c, count=12, llm=None: _concept())
    project_store.save(project_from_sample(sample_data))
    before = project_store.load()
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})

    client.post("/api/concept/commit")

    after = project_store.load()
    assert [c.id for c in after.characters] == [c.id for c in before.characters]
    assert after.world.title == before.world.title


def test_committing_without_choosing_is_refused(client, stubbed):
    client.post("/api/concept/propose", json={})

    assert client.post("/api/concept/commit").status_code == 409


# ==========================================================================
# When the model fails
# ==========================================================================


def test_a_dead_model_is_a_bad_gateway_rather_than_a_crash(client, monkeypatch):
    def dies(*a, **k):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(route.agent, "propose", dies)

    response = client.post("/api/concept/propose", json={})

    assert response.status_code == 502
    assert "quota exhausted" in response.json()["detail"]


def test_a_failed_proposal_leaves_no_session_behind(client, monkeypatch):
    def dies(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(route.agent, "propose", dies)
    client.post("/api/concept/propose", json={})

    assert client.get("/api/concept").json()["session"] is None


def test_a_failed_refinement_keeps_the_concept_it_had(client, stubbed, monkeypatch):
    client.post("/api/concept/propose", json={})
    client.post("/api/concept/choose", json={"index": 0})
    before = client.get("/api/concept").json()["session"]["chosen"]

    def dies(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(route.agent, "refine", dies)
    client.post("/api/concept/refine", json={"instruction": "x"})

    assert client.get("/api/concept").json()["session"]["chosen"] == before


# ==========================================================================
# Without a memory layer
# ==========================================================================


def test_committing_works_with_memory_switched_off(project_store, stubbed, monkeypatch):
    """The wiki page is lost, but the project must still be created."""
    from storyweaver.api import deps
    from storyweaver.server import app

    monkeypatch.setattr(route.agent, "outline", lambda c, count=12, llm=None: _concept())
    project_store.save(Project(name="새 이야기"))
    deps.set_store(project_store)
    deps.set_memory(None, "disabled")
    with TestClient(app) as client:
        client.post("/api/concept/propose", json={})
        client.post("/api/concept/choose", json={"index": 0})
        assert client.post("/api/concept/commit").status_code == 200
    deps.set_store(None)

    assert len(project_store.load().characters) == 2
