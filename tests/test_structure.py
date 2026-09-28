"""The work's planned length, and every outline paced by it.

A twelve-chapter outline used to reach the ending by chapter twelve, because
nothing told it the work was meant to run for hundreds. These tests pin the
fix at each place it has to hold:

- a structure always covers 1..target, whatever the model returned;
- an episode is told where it sits — its part, what is left, which threads are
  due around it and which are not;
- the concept's opening outline is paced as the opening of that length;
- after commit, the length can be changed and the unwritten outlines redrawn,
  without touching anything written;
- the stages that plan an episode actually receive its position.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import concept as concept_agent
from storyweaver.agents import next_episode
from storyweaver.agents import structure as layout
from storyweaver.api import deps
from storyweaver.api import episodes as episodes_api
from storyweaver.api import structure as structure_api
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Episode
from storyweaver.models.concept import ConceptEpisode, ConceptOutline
from storyweaver.models.structure import (
    PlannedThread,
    StoryPart,
    StoryStructure,
    StructureDraft,
    describe_position,
    tidy_structure,
)
from storyweaver.ui.project import Project, ProjectStore, project_from_sample
from storyweaver.wiki import STORY_SUBJECT_ID

from tests.test_concept_agent import _concept


def _four_hundred() -> StoryStructure:
    return tidy_structure(
        StoryStructure(
            target_episodes=400,
            parts=[
                StoryPart(title="귀환과 적응", start=1, end=60, purpose="돌아와 일상을 되찾는다."),
                StoryPart(title="각성", start=61, end=180, purpose="숨긴 힘이 드러난다."),
                StoryPart(title="전쟁", start=181, end=340, purpose="두 세계가 부딪친다."),
                StoryPart(title="결말", start=341, end=400, purpose="모든 것이 정리된다."),
            ],
            threads=[
                PlannedThread(name="이세계의 편지", description="누가 보냈나 — 동생이었다.",
                              plant=12, payoff=150),
                PlannedThread(name="아버지의 병", description="숨긴 병 — 회복된다.",
                              plant=5, payoff=40),
                PlannedThread(name="마왕의 정체", description="주인공 자신이었다.",
                              plant=30, payoff=380),
            ],
        )
    )


# ==========================================================================
# Keeping a structure whole
# ==========================================================================


def test_gaps_and_overlaps_are_closed_up():
    structure = tidy_structure(
        StoryStructure(
            target_episodes=100,
            parts=[
                StoryPart(title="1부", start=1, end=30),
                StoryPart(title="2부", start=40, end=70),  # a gap before it
                StoryPart(title="3부", start=60, end=90),  # overlapping, and short of 100
            ],
        )
    )

    assert [(p.start, p.end) for p in structure.parts] == [(1, 30), (31, 70), (71, 100)]


def test_every_episode_has_a_part():
    structure = _four_hundred()

    assert all(structure.part_for(n) is not None for n in range(1, 401))


def test_a_structure_with_no_parts_still_covers_the_work():
    structure = tidy_structure(StoryStructure(target_episodes=50))

    assert [(p.start, p.end) for p in structure.parts] == [(1, 50)]


def test_threads_are_kept_inside_the_work_and_paid_off_after_they_are_planted():
    structure = tidy_structure(
        StoryStructure(
            target_episodes=100,
            threads=[PlannedThread(name="x", plant=80, payoff=20),
                     PlannedThread(name="y", plant=0, payoff=500)],
        )
    )

    for thread in structure.threads:
        assert 1 <= thread.plant <= thread.payoff <= 100


# ==========================================================================
# Where one episode sits
# ==========================================================================


def test_an_early_episode_is_told_it_is_early():
    text = describe_position(_four_hundred(), 13)

    assert "전체 약 400화" in text and "13화" in text
    assert "1부 '귀환과 적응'(1~60화)" in text
    assert "결말까지 약 387화" in text
    assert "각성" in text  # the next part — named so it is not started


def test_threads_due_around_here_are_named_and_later_ones_held_back():
    text = describe_position(_four_hundred(), 12)

    assert "이 즈음 심을 떡밥" in text and "이세계의 편지" in text
    # Planted at 30, paid off at 380: nothing about it belongs in episode 12.
    assert "마왕의 정체" not in text


def test_a_thread_due_for_payoff_is_called_due():
    text = describe_position(_four_hundred(), 40)

    assert "이 즈음 회수할 떡밥" in text and "아버지의 병" in text


def test_a_planted_thread_not_yet_due_is_marked_as_not_to_be_answered():
    text = describe_position(_four_hundred(), 100)

    assert "아직 회수할 때가 아닌" in text
    assert "마왕의 정체" in text


def test_no_structure_means_no_position():
    assert describe_position(None, 13) == ""


def test_past_the_planned_length_says_so():
    assert "넘어섰습니다" in describe_position(_four_hundred(), 420)


# ==========================================================================
# The concept stage
# ==========================================================================


def test_without_a_length_the_outline_is_the_whole_book():
    prompt = concept_agent.build_outline_prompt(_concept(), 12)

    assert concept_agent.WHOLE_BOOK_PACING in prompt


def test_with_a_length_the_outline_is_only_the_opening():
    prompt = concept_agent.build_outline_prompt(_concept(), 12, _four_hundred())

    assert "about 400 episodes" in prompt
    assert "only the opening" in prompt
    assert "귀환과 적응" in prompt
    assert "Do not reach the ending" in prompt
    assert concept_agent.WHOLE_BOOK_PACING not in prompt


def test_the_layout_is_asked_for_the_whole_length():
    calls: dict = {}

    class Model:
        def with_structured_output(self, schema):
            class Structured:
                def invoke(self, prompt):
                    calls["prompt"] = prompt
                    return StructureDraft(
                        parts=[StoryPart(title="1부", start=1, end=200)],
                        threads=[PlannedThread(name="편지", plant=10, payoff=900)],
                    )
            return Structured()

    structure = layout.lay_out(400, "작품 설명", llm=Model())

    assert "400 episodes" in calls["prompt"]
    assert structure.parts[-1].end == 400  # tidied to cover the whole work
    assert structure.threads[0].payoff == 400


def test_the_layout_keeps_written_chapters_as_they_happened():
    prompt = layout.build_prompt(400, "작품", story_so_far="1화: 돌아왔다.", written_through=3)

    assert "Episodes 1 to 3 are already written" in prompt
    assert "1화: 돌아왔다." in prompt


# ==========================================================================
# The API
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
    """A story rushed at twelve episodes: two written, ten queued, one planned."""
    project = project_from_sample(sample_data)
    project.episodes = []
    for n in range(1, 13):
        project.add_episode(f"{n}화: 너무 빠른 전개")
    for n in (1, 2):
        project.episodes[n - 1] = project.episodes[n - 1].model_copy(
            update={"status": "completed", "final_text": "본문.", "summary": f"{n}화에 일어난 일."}
        )
    project.episodes[2] = project.episodes[2].model_copy(update={"status": "planned"})
    project_store.save(project)
    return project


@pytest.fixture
def drawing(monkeypatch):
    calls: dict = {"layout": [], "rewrite": []}

    def lay_out(target, work, **kwargs):
        calls["layout"].append({"target": target, **kwargs})
        return _four_hundred() if target == 400 else tidy_structure(
            StoryStructure(target_episodes=target)
        )

    def rewrite_upcoming(structure, current, **kwargs):
        calls["rewrite"].append(sorted(current))
        return {n: f"{n}화: 400화에 맞춘 느린 전개" for n in current}

    monkeypatch.setattr(structure_api.layout, "lay_out", lay_out)
    monkeypatch.setattr(structure_api.layout, "rewrite_upcoming", rewrite_upcoming)
    return calls


def test_a_committed_concept_brings_its_structure(client, project_store, monkeypatch):
    from storyweaver.api import concept as concept_api

    monkeypatch.setattr(concept_api.agent, "propose", lambda seed="", count=3, llm=None: [
        _concept(episodes=[]) for _ in range(count)
    ])
    seen: dict = {}

    def outline(concept, count=12, llm=None, structure=None):
        seen["structure"] = structure
        return concept.model_copy(update={"episodes": [
            ConceptEpisode(number=n, line=f"{n}화") for n in range(1, count + 1)
        ]})

    monkeypatch.setattr(concept_api.agent, "outline", outline)
    monkeypatch.setattr(concept_api.layout, "lay_out", lambda target, work, **k: _four_hundred())

    client.post("/api/concept/propose", json={})
    session = client.post(
        "/api/concept/choose", json={"index": 0, "episodes": 12, "target_episodes": 400}
    ).json()["session"]
    assert session["target_episodes"] == 400
    assert seen["structure"].target_episodes == 400  # the outline was paced by it

    client.post("/api/concept/commit")

    assert project_store.load().structure.target_episodes == 400


def test_the_opening_cannot_be_longer_than_the_work(client, monkeypatch):
    from storyweaver.api import concept as concept_api

    monkeypatch.setattr(concept_api.agent, "propose", lambda seed="", count=3, llm=None: [
        _concept(episodes=[]) for _ in range(count)
    ])
    client.post("/api/concept/propose", json={})

    response = client.post(
        "/api/concept/choose", json={"index": 0, "episodes": 30, "target_episodes": 20}
    )

    assert response.status_code == 422


def test_the_structure_can_be_read(client, loaded):
    view = client.get("/api/structure").json()

    assert view["structure"] is None
    assert view["next_episode"] == 13
    assert view["written_through"] == 2


def test_the_author_can_edit_it_and_it_stays_whole(client, loaded):
    view = client.put("/api/structure", json={
        "target_episodes": 100,
        "parts": [{"title": "1부", "start": 1, "end": 40}, {"title": "2부", "start": 50, "end": 80}],
        "threads": [],
    }).json()

    assert [(p["start"], p["end"]) for p in view["structure"]["parts"]] == [(1, 40), (41, 100)]
    assert "전체 약 100화" in view["position"]


def test_redrawing_proposes_without_saving(client, loaded, project_store, drawing):
    draft = client.post("/api/structure/draft", json={"target_episodes": 400}).json()

    assert draft["structure"]["target_episodes"] == 400
    assert [e["episode_number"] for e in draft["episodes"]] == list(range(3, 13))
    assert draft["episodes"][0]["before"] == "3화: 너무 빠른 전개"
    assert project_store.load().structure is None
    assert project_store.load().episodes[3].author_storyline == "4화: 너무 빠른 전개"


def test_redrawing_leaves_written_chapters_alone(client, loaded, drawing):
    client.post("/api/structure/draft", json={"target_episodes": 400})

    assert drawing["layout"][0]["written_through"] == 2
    assert 1 not in drawing["rewrite"][0] and 2 not in drawing["rewrite"][0]


def test_the_length_cannot_be_shorter_than_what_is_written(client, loaded, drawing):
    assert client.post("/api/structure/draft", json={"target_episodes": 2}).status_code == 422


def test_applying_saves_the_layout_and_the_new_outlines(client, loaded, project_store, drawing):
    draft = client.post("/api/structure/draft", json={"target_episodes": 400}).json()

    view = client.post("/api/structure/apply", json={
        "structure": draft["structure"],
        "episodes": [
            {"episode_number": e["episode_number"], "author_storyline": e["after"]}
            for e in draft["episodes"]
        ],
    }).json()

    project = project_store.load()
    assert view["structure"]["target_episodes"] == 400
    assert project.episodes[3].author_storyline == "4화: 400화에 맞춘 느린 전개"
    assert project.episodes[0].author_storyline == "1화: 너무 빠른 전개"  # written: untouched


def test_a_planned_episode_goes_back_to_the_queue_when_its_outline_changes(
    client, loaded, project_store, drawing
):
    client.post("/api/structure/apply", json={
        "structure": _four_hundred().model_dump(),
        "episodes": [{"episode_number": 3, "author_storyline": "3화: 새 개요"}],
    })

    assert project_store.load().episodes[2].status == "queued"


def test_a_written_chapter_cannot_be_re_outlined(client, loaded, project_store):
    response = client.post("/api/structure/apply", json={
        "structure": _four_hundred().model_dump(),
        "episodes": [{"episode_number": 1, "author_storyline": "고쳐 쓴 1화"}],
    })

    assert response.status_code == 409
    assert project_store.load().structure is None  # nothing half-applied


def test_the_new_outlines_are_kept_in_the_works_history(client, loaded, memory):
    client.post("/api/structure/apply", json={
        "structure": _four_hundred().model_dump(),
        "episodes": [{"episode_number": 5, "author_storyline": "5화: 새 개요"}],
    })

    log = memory.chronicle.chain("story", STORY_SUBJECT_ID, "episodes")
    assert any("5화 — 5화: 새 개요" in e.value and "400화" in e.value for e in log)


# ==========================================================================
# Every stage that plans an episode is told where it sits
# ==========================================================================


def _with_structure(project_store) -> None:
    project = project_store.load()
    project.structure = _four_hundred()
    project_store.save(project)


def test_drafting_the_next_episode_is_told_its_position(client, loaded, project_store, monkeypatch):
    _with_structure(project_store)
    prompts = []

    class Model:
        def invoke(self, prompt):
            prompts.append(prompt)

            class Reply:
                content = "13화 개요."
            return Reply()

    monkeypatch.setattr(next_episode, "get_llm", lambda **kwargs: Model())

    client.post("/api/episodes/draft-next", json={})

    assert "전체 약 400화" in prompts[0] and "이번은 13화" in prompts[0]
    assert "이세계의 편지" in prompts[0]  # due to be planted around 12


def test_the_story_planner_is_told_each_episodes_position(
    client, loaded, project_store, monkeypatch
):
    _with_structure(project_store)
    prompts = []

    class Model:
        def invoke(self, prompt):
            prompts.append(prompt)

            class Reply:
                content = "기획서."
            return Reply()

    monkeypatch.setattr(episodes_api, "get_llm", lambda **kwargs: Model())

    client.post("/api/episodes/plan-all", json={"summaries": ["한 줄", "두 줄"]})

    assert "이번은 13화" in prompts[0]
    assert "이번은 14화" in prompts[1]


def test_the_director_is_told_the_episodes_position(client, loaded, project_store, monkeypatch):
    _with_structure(project_store)
    seen = {}

    def plan_episode(episode, world, characters, **kwargs):
        seen["brief"] = kwargs.get("story_brief", "")
        raise RuntimeError("stop here")

    monkeypatch.setattr(episodes_api.director, "plan_episode", plan_episode)

    client.post("/api/episodes/4/plan")

    assert "이번은 4화" in seen["brief"]
    assert "1부 '귀환과 적응'" in seen["brief"]


# ==========================================================================
# Re-outlining the queue
# ==========================================================================


def test_a_skipped_episode_keeps_its_outline():
    class Model:
        def with_structured_output(self, schema):
            class Structured:
                def invoke(self, prompt):
                    return ConceptOutline(episodes=[ConceptEpisode(number=3, line="새 3화")])
            return Structured()

    drawn = layout.rewrite_upcoming(
        _four_hundred(), {3: "옛 3화", 4: "옛 4화"}, title="t", work="w", llm=Model()
    )

    assert drawn == {3: "새 3화", 4: "옛 4화"}


def test_the_rewrite_prompt_carries_the_layout_and_the_old_outlines():
    prompt = layout.build_rewrite_prompt(
        _four_hundred(), title="귀환자", work="작품", story_so_far="1화: 돌아왔다.",
        current={3: "옛 3화", 4: "옛 4화"},
    )

    assert "목표 분량: 약 400화" in prompt
    assert "3화: 옛 3화" in prompt and "episodes 3, 4" in prompt
