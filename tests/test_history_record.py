"""What the story has done to each element, as the planners are told it.

The author's rule, in two halves:

- **author edits: the latest version only.** Nobody planning episode 120 needs
  to know what a setting used to say before the author rewrote it;
- **story history: per element, the last forty episodes it appeared in**, in
  full, and a summary of everything older. A character offstage for a hundred
  episodes keeps their own forty, not the story's last forty.

And a faction is more than its name: its description and its deeds travel too.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.agents import history, next_episode
from storyweaver.api import deps
from storyweaver.memory.chronicle_store import ChronicleStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models import Episode
from storyweaver.models.chronicle import SectionSpec
from storyweaver.ui.project import Project, ProjectStore, project_from_sample


@pytest.fixture
def store(tmp_path) -> ChronicleStore:
    return ChronicleStore(tmp_path / "state")


@pytest.fixture
def project(sample_data) -> Project:
    return project_from_sample(sample_data)


def _deed(store, character_id: str, episode: int, text: str | None = None) -> None:
    store.record(
        "character", character_id, "deeds", text or f"{episode}화의 일",
        source="episode", episode_number=episode,
    )


class Digester:
    """Stands in for the model: records what it was asked, answers per key."""

    def __init__(self, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    def __call__(self, jobs):
        self.calls.append(list(jobs))
        if self.fail:
            raise RuntimeError("quota exhausted")
        return {
            job.key: f"요약({job.new[0][0]}~{job.new[-1][0]}화, 이전: {job.existing or '없음'})"
            for job in jobs
        }


# ==========================================================================
# The window is each element's own
# ==========================================================================


def test_the_last_forty_appearances_are_given_in_full(store, project):
    for n in range(1, 51):
        _deed(store, "harry-potter", n)

    (harry,) = [r for r in history.gather(store, project, before=51) if r.subject_id == "harry-potter"]

    assert [n for n, _ in harry.recent] == list(range(11, 51))
    assert [n for n, _ in harry.older] == list(range(1, 11))


def test_the_window_counts_appearances_not_the_storys_episodes(store, project):
    """Ron appears in episodes 1-5 and not again; planning 200 still shows them."""
    for n in range(1, 6):
        _deed(store, "ron-weasley", n)
    for n in range(6, 200):
        _deed(store, "harry-potter", n)

    records = {r.subject_id: r for r in history.gather(store, project, before=200)}

    assert [n for n, _ in records["ron-weasley"].recent] == [1, 2, 3, 4, 5]
    assert records["ron-weasley"].older == []


def test_nothing_from_the_episode_being_planned_or_after_it(store, project):
    _deed(store, "harry-potter", 3)
    _deed(store, "harry-potter", 7, "미래의 일")

    text = history.story_record(store, project, before=5)

    assert "3화의 일" in text
    assert "미래의 일" not in text


def test_a_change_names_its_section_and_a_relationship_names_the_other(store, project):
    store.record(
        "character", "harry-potter", "goals", "복수한다",
        source="episode", episode_number=4, reason="가족이 죽었다",
    )
    store.record(
        "character", "harry-potter", "relationship:ron-weasley", "절친 — 목숨을 빚졌다",
        source="episode", episode_number=6, reason="6화에서 관계가 달라짐",
    )
    ron = project.get_character("ron-weasley").name

    text = history.story_record(store, project, before=10)

    assert "4화: 목표: 복수한다 — 가족이 죽었다" in text
    assert f"6화: 관계 → {ron}: 절친 — 목숨을 빚졌다" in text
    assert "관계가 달라짐" not in text


def test_a_record_the_author_has_not_accepted_is_left_out(store, project):
    entry = store.record("character", "harry-potter", "deeds", "검토 전의 일",
                         source="episode", episode_number=2)
    store._replace(entry.entry_id, {"pending": True})

    assert "검토 전의 일" not in history.story_record(store, project, before=5)


# ==========================================================================
# Author edits: the latest version only
# ==========================================================================


def test_an_author_section_shows_only_its_latest_text(store, project):
    page = store.get_wiki_subject("character", "harry-potter")
    page.free_sections.append(SectionSpec(key="ability", title="능력", author_made=True))
    store.save_wiki_subject(page)
    store.record("character", "harry-potter", "ability", "불을 다룬다", source="author")
    store.record("character", "harry-potter", "ability", "얼음을 다룬다", source="author")

    text = history.story_record(store, project, before=1)

    assert "설정 — 능력: 얼음을 다룬다" in text
    assert "불을 다룬다" not in text


def test_an_author_edit_of_a_bound_setting_is_not_shown_as_history(store, project):
    store.record("character", "harry-potter", "speech", "옛 말투", source="author")
    store.record("character", "harry-potter", "speech", "새 말투", source="author")

    text = history.story_record(store, project, before=10)

    assert "옛 말투" not in text


# ==========================================================================
# Factions
# ==========================================================================


def test_a_faction_brings_its_description_summary_and_deeds(store, project):
    store.record("faction", "order", "description", "옛 설명", source="author")
    store.record("faction", "order", "description", "비밀 결사. 왕가를 노린다.", source="author")
    page = store.get_wiki_subject("faction", "order")
    page.title = "불사조 기사단"
    page.summary = "덤블도어가 세운 결사"
    store.save_wiki_subject(page)
    store.record("faction", "order", "events", "본부를 옮겼다", source="episode", episode_number=8)

    text = history.story_record(store, project, before=10)

    assert "### 불사조 기사단 (세력)" in text
    assert "설정 — 설명: 비밀 결사. 왕가를 노린다." in text
    assert "옛 설명" not in text
    assert "설정 — 개요: 덤블도어가 세운 결사" in text
    assert "8화: 본부를 옮겼다" in text


# ==========================================================================
# Older than the window: a summary, made once
# ==========================================================================


def test_what_aged_out_is_summarised(store, project):
    for n in range(1, 46):
        _deed(store, "harry-potter", n)
    digester = Digester()

    text = history.story_record(store, project, before=46, digester=digester)

    (job,) = digester.calls[0]
    assert [n for n, _ in job.new] == [1, 2, 3, 4, 5]
    assert "그 이전 기록 요약 (1~5화 중 5개 회차)" in text
    assert "요약(1~5화, 이전: 없음)" in text
    assert "- 1화: 1화의 일" not in text


def test_the_summary_is_not_made_again_while_nothing_moved(store, project):
    for n in range(1, 46):
        _deed(store, "harry-potter", n)
    digester = Digester()

    history.story_record(store, project, before=46, digester=digester)
    history.story_record(store, project, before=46, digester=digester)

    assert len(digester.calls) == 1


def test_one_more_episode_extends_the_summary_rather_than_rereading(store, project):
    for n in range(1, 46):
        _deed(store, "harry-potter", n)
    digester = Digester()
    history.story_record(store, project, before=46, digester=digester)

    _deed(store, "harry-potter", 46)
    text = history.story_record(store, project, before=47, digester=digester)

    (job,) = digester.calls[1]
    assert [n for n, _ in job.new] == [6]
    assert job.existing == "요약(1~5화, 이전: 없음)"
    assert "요약(6~6화, 이전: 요약(1~5화, 이전: 없음))" in text


def test_an_edited_old_record_rebuilds_the_summary(store, project):
    for n in range(1, 46):
        _deed(store, "harry-potter", n)
    digester = Digester()
    history.story_record(store, project, before=46, digester=digester)

    first = store.chain("character", "harry-potter", "deeds")[0]
    store.edit(first.entry_id, value="고쳐 적은 1화의 일")
    history.story_record(store, project, before=46, digester=digester)

    (job,) = digester.calls[1]
    assert job.existing == ""
    assert job.new[0] == (1, ["고쳐 적은 1화의 일"])


def test_a_failed_summary_still_plans_and_is_tried_again(store, project):
    for n in range(1, 46):
        _deed(store, "harry-potter", n)

    text = history.story_record(store, project, before=46, digester=Digester(fail=True))
    assert "1화: 1화의 일" in text  # the raw record, kept rather than lost

    retry = Digester()
    history.story_record(store, project, before=46, digester=retry)
    assert len(retry.calls) == 1


def test_no_model_is_called_while_everything_fits(store, project):
    for n in range(1, 41):
        _deed(store, "harry-potter", n)
    digester = Digester()

    history.story_record(store, project, before=41, digester=digester)

    assert digester.calls == []


def test_nothing_to_say_is_nothing(store, project):
    assert history.story_record(store, project, before=1) == ""
    assert history.story_record(None, project, before=1) == ""


# ==========================================================================
# It reaches the planners
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

    project = project_from_sample(sample_data)
    project.episodes = [
        Episode(episode_number=n, title=f"{n}화", author_storyline=f"{n}화 줄거리")
        for n in range(1, 4)
    ]
    project_store.save(project)
    memory.chronicle.record(
        "character", "ron-weasley", "deeds", "해리를 구하려 뛰어들었다",
        source="episode", episode_number=2,
    )
    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


def test_twenty_at_once_is_planned_from_the_record(client, monkeypatch):
    seen = {}

    def draft_batch(project, count, **kwargs):
        seen.update(kwargs)
        return [(4, "4화 개요")]

    monkeypatch.setattr(next_episode, "draft_batch", draft_batch)
    client.post("/api/episodes/draft-batch", json={})

    assert "2화: 해리를 구하려 뛰어들었다" in seen["record"]


def test_the_record_has_a_place_in_the_outline_prompt(project):
    prompt = next_episode.build_batch_prompt(project, 5, record="- 2화: 해리를 구하려 뛰어들었다")

    assert "What has happened to each of them" in prompt
    assert "해리를 구하려 뛰어들었다" in prompt


def test_the_directors_plan_is_drawn_from_the_record(client, monkeypatch):
    from storyweaver.agents import director

    seen = {}

    def decompose(episode, world, characters, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(director, "decompose_episode", decompose)
    client.post("/api/episodes/3/plan")

    assert "작중 기록" in seen["story_brief"]
    assert "해리를 구하려 뛰어들었다" in seen["story_brief"]


def test_the_structure_is_laid_out_from_the_record(client, monkeypatch):
    from storyweaver.agents import structure as layout
    from storyweaver.models.structure import StoryPart, StoryStructure

    seen = {}

    def lay_out(target, work, **kwargs):
        seen["work"] = work
        return StoryStructure(
            target_episodes=target, parts=[StoryPart(title="1부", start=1, end=target)]
        )

    monkeypatch.setattr(layout, "lay_out", lay_out)
    client.post("/api/structure/draft", json={"target_episodes": 100, "rewrite_upcoming": False})

    assert "해리를 구하려 뛰어들었다" in seen["work"]


def test_the_digest_prompt_and_answer(store, project):
    """The real `digest`, with a stand-in model: the prompt names each key and
    carries the records, and the answer is read back per key."""
    asked = []

    class Structured:
        def invoke(self, prompt):
            asked.append(prompt)
            return history.DigestBatch(digests=[
                history.ElementDigest(key="character:harry-potter", summary="1화에 떠났다."),
            ])

    class Model:
        def with_structured_output(self, schema):
            return Structured()

    job = history.DigestJob("character:harry-potter", "해리", "", [(1, ["떠났다"])])
    made = history.digest([job], llm=Model())

    assert made == {"character:harry-potter": "1화에 떠났다."}
    assert "key: character:harry-potter" in asked[0]
    assert "- 1화: 떠났다" in asked[0]
