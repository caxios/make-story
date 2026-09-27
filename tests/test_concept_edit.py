"""Editing a concept by hand, and carrying edits into a committed work.

Before this, a committed concept was read-only: the only way to change the
plan was to throw the session away. Two properties matter now:

- a hand edit changes exactly what the author typed, and says what moved;
- carrying edits into the work moves **only what changed in the concept** —
  never what the story or the author changed in the work since commit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import concept as route
from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models.concept import ConceptEpisode, ConceptSession
from storyweaver.ui.project import ProjectStore
from storyweaver.wiki import STORY_SUBJECT_ID

from tests.test_concept_api import _character, _concept


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
def client(project_store, memory):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


@pytest.fixture
def concepts(project_store) -> ConceptStore:
    return ConceptStore(project_store.state_dir)


@pytest.fixture
def refining(concepts) -> ConceptStore:
    concepts.save(ConceptSession(chosen=_concept(), status="refining"))
    return concepts


@pytest.fixture
def committed(client, refining) -> ConceptStore:
    assert client.post("/api/concept/commit").status_code == 200
    return refining


def _edit(client, **changes):
    concept = client.get("/api/concept").json()["session"]["chosen"]
    concept.update(changes)
    return client.put("/api/concept/chosen", json={"concept": concept})


# ==========================================================================
# Editing by hand
# ==========================================================================


def test_a_hand_edit_changes_what_was_typed_and_says_so(client, refining):
    view = _edit(client, ending="동혁이 현세로 돌아온다.").json()

    assert view["session"]["chosen"]["ending"] == "동혁이 현세로 돌아온다."
    assert view["changed"]
    assert view["session"]["turns"][-1]["instruction"] == "직접 수정"


def test_an_edit_that_changes_nothing_is_not_a_turn(client, refining):
    turns = len(client.get("/api/concept").json()["session"]["turns"])

    view = _edit(client).json()

    assert view["changed"] == ["바뀐 것이 없습니다"]
    assert len(view["session"]["turns"]) == turns


def test_a_committed_concept_edit_reaches_the_work_at_once(client, committed, project_store):
    view = _edit(client, tone="따뜻하고 느린").json()

    assert project_store.load().world.tone == "따뜻하고 느린"
    assert view["unsynced"] is False
    assert any(line.startswith("작품에 반영:") for line in view["changed"])


def test_an_edit_before_commit_does_not_touch_the_work(client, refining, project_store):
    _edit(client, tone="따뜻하고 느린")

    assert project_store.load().world.tone != "따뜻하고 느린"


def test_editing_needs_a_chosen_concept(client, concepts):
    concepts.save(ConceptSession(status="proposing"))

    assert client.put("/api/concept/chosen", json={"concept": _concept().model_dump()}).status_code == 409


# ==========================================================================
# Carrying edits into the work
# ==========================================================================


def _changed(client, concept) -> list[str]:
    return client.put("/api/concept/chosen", json={"concept": concept}).json()["changed"]


def test_a_fresh_commit_has_nothing_to_carry(client, committed):
    assert client.get("/api/concept").json()["unsynced"] is False
    assert client.post("/api/concept/sync/preview").json()["applied"] == []


def test_an_edit_left_unsynced_by_an_older_version_can_still_be_carried(
    client, committed, concepts, project_store
):
    """Edits made before sync was automatic are waiting in the session."""
    session = concepts.load()
    session.chosen = session.chosen.model_copy(update={"title": "바뀐 제목"})
    concepts.save(session)
    assert client.get("/api/concept").json()["unsynced"] is True

    preview = client.post("/api/concept/sync/preview").json()
    assert "세계관 제목" in preview["applied"]
    assert project_store.load().world.title == "사념세계의 문"  # the preview wrote nothing

    client.post("/api/concept/sync")
    assert project_store.load().world.title == "바뀐 제목"
    assert client.get("/api/concept").json()["unsynced"] is False


def test_the_arc_reaches_the_works_page(client, committed, memory):
    _edit(client, arc="천천히 가는 새 아크.")

    assert memory.chronicle.chain("story", STORY_SUBJECT_ID, "arc")[-1].value == "천천히 가는 새 아크."


def test_only_what_changed_in_the_concept_moves(client, committed, project_store):
    # Since commit, the author changed 박동혁's look in the workshop.
    project = project_store.load()
    hero = next(c for c in project.characters if c.name == "박동혁")
    project.upsert_character(hero.model_copy(update={"appearance": "워크숍에서 고친 모습"}))
    project_store.save(project)

    # Now the concept edits his speech, not his look.
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["characters"][0]["speech"] = "거친 반말."
    _changed(client, chosen)

    hero = next(c for c in project_store.load().characters if c.name == "박동혁")
    assert hero.speech_style == "거친 반말."
    assert hero.appearance == "워크숍에서 고친 모습"  # not overwritten


def test_a_new_character_joins_the_cast(client, committed, project_store):
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["characters"].append(
        _character("한유라", role="라이벌", relationships=["박동혁 — 옛 동료"]).model_dump()
    )

    changed = _changed(client, chosen)

    assert "작품에 반영: 인물 추가: 한유라" in changed
    cast = {c.name: c for c in project_store.load().characters}
    assert "한유라" in cast
    assert cast["한유라"].relationships[0].target_character_id == cast["박동혁"].id


def test_a_removed_character_is_not_deleted_and_says_where_to(client, committed, project_store):
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["characters"] = chosen["characters"][:1]

    changed = _changed(client, chosen)

    assert any(
        line.startswith("반영 안 됨:") and "시월" in line and "캐릭터 워크숍" in line
        for line in changed
    )
    assert "시월" in {c.name for c in project_store.load().characters}


def test_a_new_rule_is_added(client, committed, project_store):
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["rules"].append("사념은 거울에 비치지 않는다.")

    _changed(client, chosen)

    statements = [r.statement for r in project_store.load().world.rules]
    assert "사념은 거울에 비치지 않는다." in statements
    assert len(statements) == 3


def test_an_unwritten_episode_line_is_updated(client, committed, project_store):
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["episodes"][1]["line"] = "천천히 정체를 숨긴다."

    _changed(client, chosen)

    assert project_store.load().episodes[1].author_storyline == "천천히 정체를 숨긴다."


def test_a_written_episode_is_left_alone(client, committed, project_store):
    project = project_store.load()
    project.episodes[0] = project.episodes[0].model_copy(
        update={"status": "completed", "final_text": "본문."}
    )
    project_store.save(project)
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["episodes"][0]["line"] = "고쳐 쓴 1화."

    changed = _changed(client, chosen)

    assert project_store.load().episodes[0].author_storyline == "시월이 학교로 찾아온다."
    assert any("1화" in line and "이미 쓴" in line for line in changed)


def test_the_same_change_is_not_applied_twice(client, committed, project_store):
    chosen = client.get("/api/concept").json()["session"]["chosen"]
    chosen["rules"].append("새 규칙.")
    _changed(client, chosen)

    # Saved again, with something else changed: the rule is not added again.
    chosen["tone"] = "서늘한"
    _changed(client, chosen)

    assert client.post("/api/concept/sync").json()["applied"] == []
    assert len(project_store.load().world.rules) == 3


def test_an_ai_refinement_after_commit_reaches_the_work(client, committed, project_store, monkeypatch):
    from storyweaver.agents import concept as agent

    def refine(concept, instruction, llm=None):
        return concept.model_copy(update={"tone": "비장한"}), ["분위기를 바꿨습니다"]

    monkeypatch.setattr(agent, "refine", refine)

    view = client.post("/api/concept/refine", json={"instruction": "더 비장하게"}).json()

    assert project_store.load().world.tone == "비장한"
    assert view["changed"][0] == "분위기를 바꿨습니다"


def test_a_session_committed_before_baselines_existed_still_syncs(client, concepts, project_store):
    """The author's current session was committed before this was built."""
    concepts.save(ConceptSession(chosen=_concept(), status="refining"))
    client.post("/api/concept/commit")
    session = concepts.load()
    session.committed_concept = None  # as an old session would be
    concepts.save(session)

    _edit(client, tone="따뜻하고 느린")

    assert project_store.load().world.tone == "따뜻하고 느린"


def test_syncing_before_commit_is_refused(client, refining):
    assert client.post("/api/concept/sync").status_code == 409
