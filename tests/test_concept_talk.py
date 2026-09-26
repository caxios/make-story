"""Working the concept out by talking, rather than picking one of three.

An author who can answer "what do you want to write?" is served by the spread
of proposals. This is for the one who cannot — the book is found in the
conversation, and the conversation is what carries the state.

That makes it the one place in the concept stage that replays a transcript, and
the one place whose cost grows with use. Both the cap on how far back it
replays and the shortness of the replies are load-bearing, so both are tested.

Where the two ways in meet is `chosen`: once the conversation is written down,
everything after it — refining, the outline, committing — is the same code the
proposal path uses, and is tested there.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver import config
from storyweaver.agents import concept as agent
from storyweaver.api import concept as route
from storyweaver.concept_store import ConceptStore
from storyweaver.memory.manager import MemoryManager
from storyweaver.models.concept import (
    ConceptCharacter,
    ConceptEpisode,
    ConceptMessage,
    StoryConcept,
)
from storyweaver.ui.project import Project, ProjectStore


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


def _concept() -> StoryConcept:
    return StoryConcept(
        title="거짓말쟁이의 계절",
        logline="거짓말로 살아온 소년이 진실만 말하는 아이를 만난다.",
        genre="드라마",
        tone="건조하고 서늘한",
        premise="거짓말이 화폐인 도시.",
        arc="1부 만남, 2부 들통, 3부 선택.",
        ending="소년이 마지막 거짓말을 한다.",
        characters=[ConceptCharacter(name="한서")],
    )


@pytest.fixture
def stubbed(monkeypatch):
    """The agent, without a model behind it."""
    calls: dict = {"talk": 0, "distill": 0, "outline": 0, "seen": []}

    def talk(messages, llm=None):
        calls["talk"] += 1
        calls["seen"] = list(messages)
        return f"{len(messages)}번째 답."

    def distill(messages, llm=None):
        calls["distill"] += 1
        calls["distilled"] = list(messages)
        return _concept()

    def outline(concept, count=12, llm=None):
        calls["outline"] += 1
        return concept.model_copy(
            update={
                "episodes": [
                    ConceptEpisode(number=n, line=f"{n}화 구상") for n in range(1, count + 1)
                ]
            }
        )

    monkeypatch.setattr(route.agent, "talk", talk)
    monkeypatch.setattr(route.agent, "distill", distill)
    monkeypatch.setattr(route.agent, "outline", outline)
    return calls


def _say(client, text: str) -> dict:
    response = client.post("/api/concept/talk", json={"message": text})
    assert response.status_code == 200, response.text
    return response.json()["session"]


# ==========================================================================
# The transcript the model is shown
# ==========================================================================


def test_an_empty_conversation_tells_the_model_to_open_it(client):
    """A blank transcript reads as a section the model should fill in."""
    assert agent.format_transcript([]) == agent.OPENING


def test_the_transcript_says_who_said_what(client):
    text = agent.format_transcript(
        [
            ConceptMessage(role="author", text="복수극을 쓰고 싶어"),
            ConceptMessage(role="ai", text="누구에게 복수하나요?"),
        ]
    )

    assert text == "작가: 복수극을 쓰고 싶어\n\nAI: 누구에게 복수하나요?"


def test_a_long_conversation_is_cut_from_the_front(client):
    """Replaying everything is what makes this the one stage that gets dearer."""
    messages = [ConceptMessage(role="author", text="맨 처음 한 말")]
    messages += [ConceptMessage(role="author", text=f"{n}번") for n in range(59)]

    text = agent.format_transcript(messages)

    assert "58번" in text
    assert "맨 처음 한 말" not in text
    assert text.count("작가:") == agent.TRANSCRIPT_WINDOW


def test_the_author_is_told_when_the_front_was_cut(client):
    """Silently forgetting is how a model contradicts something already agreed."""
    messages = [ConceptMessage(role="author", text=f"{n}") for n in range(50)]

    assert "앞의 10개 대화는 생략되었습니다" in agent.format_transcript(messages)


def test_writing_it_down_uses_the_whole_conversation(client):
    """This call happens once, and the opening of a conversation is the premise."""
    messages = [ConceptMessage(role="author", text="맨 처음 한 말")]
    messages += [ConceptMessage(role="author", text=f"{n}번") for n in range(59)]

    assert "맨 처음 한 말" in agent.build_distill_prompt(messages)


def test_the_reply_is_asked_for_as_prose(client):
    """A schema would have the model fill every field, which is the opposite of
    the half-formed thought the author is meant to push back on."""
    prompt = agent.build_talk_prompt([ConceptMessage(role="author", text="음")])

    assert "Plain" in prompt and "No headings" in prompt


def test_the_reply_length_is_not_capped():
    """The author asked for replies as long as the answer needs: no sentence
    count in the prompt, and not the shared token cap either."""
    prompt = agent.build_talk_prompt([ConceptMessage(role="author", text="음")])

    assert "sentences" not in prompt.split("## How to answer")[1].split("**One question")[0]
    assert "Three or four" not in prompt
    assert agent.TALK_MAX_OUTPUT_TOKENS > config.MAX_OUTPUT_TOKENS


# ==========================================================================
# Talking
# ==========================================================================


def test_the_first_message_opens_a_session(client, stubbed, store):
    session = _say(client, "뭘 쓰고 싶은지 모르겠어")

    assert session["status"] == "talking"
    assert [m["role"] for m in session["messages"]] == ["author", "ai"]
    assert store.load() is not None


def test_the_conversation_survives_a_browser_restart(client, stubbed):
    _say(client, "복수극")
    _say(client, "주인공은 여자로")

    session = client.get("/api/concept").json()["session"]

    assert [m["text"] for m in session["messages"] if m["role"] == "author"] == [
        "복수극",
        "주인공은 여자로",
    ]


def test_the_model_is_shown_everything_said_before(client, stubbed):
    _say(client, "복수극")
    _say(client, "주인공은 여자로")

    assert [m.text for m in stubbed["seen"]] == ["복수극", "1번째 답.", "주인공은 여자로"]


def test_what_the_author_typed_survives_a_failed_reply(client, monkeypatch, store):
    """It is saved before the model is called, so a 502 does not eat it."""
    def explode(messages, llm=None):
        raise RuntimeError("the model is down")

    monkeypatch.setattr(route.agent, "talk", explode)

    assert client.post("/api/concept/talk", json={"message": "아까운 생각"}).status_code == 502
    session = store.load()
    assert [m.text for m in session.messages] == ["아까운 생각"]


def test_an_empty_message_is_refused(client, stubbed):
    assert client.post("/api/concept/talk", json={"message": "   "}).status_code == 422


def test_the_conversation_can_be_thrown_away(client, stubbed):
    _say(client, "역시 아니다")

    session = client.delete("/api/concept/talk").json()["session"]

    assert session["messages"] == []


# ==========================================================================
# Writing it down
# ==========================================================================


def test_the_conversation_becomes_a_concept_to_refine(client, stubbed):
    _say(client, "거짓말쟁이 이야기")

    session = client.post("/api/concept/talk/build", json={}).json()["session"]

    assert session["status"] == "refining"
    assert session["chosen"]["title"] == "거짓말쟁이의 계절"


def test_writing_it_down_draws_no_outline_by_default(client, stubbed):
    """A second model call the author may want to spend after reshaping it."""
    _say(client, "거짓말쟁이 이야기")

    session = client.post("/api/concept/talk/build", json={}).json()["session"]

    assert stubbed["outline"] == 0
    assert session["chosen"]["episodes"] == []


def test_the_outline_is_drawn_when_it_is_asked_for(client, stubbed):
    _say(client, "거짓말쟁이 이야기")

    session = client.post(
        "/api/concept/talk/build", json={"episodes": 8}
    ).json()["session"]

    assert len(session["chosen"]["episodes"]) == 8


def test_the_conversation_is_kept_after_it_becomes_a_concept(client, stubbed):
    """How a book was arrived at is worth as much as what was arrived at."""
    _say(client, "거짓말쟁이 이야기")

    session = client.post("/api/concept/talk/build", json={}).json()["session"]

    assert len(session["messages"]) == 2


def test_what_the_conversation_never_settled_is_said_out_loud(client, monkeypatch, stubbed):
    """Otherwise the author meets the gap at commit, with no way back to it."""
    monkeypatch.setattr(
        route.agent,
        "distill",
        lambda messages, llm=None: _concept().model_copy(update={"ending": ""}),
    )
    _say(client, "거짓말쟁이 이야기")

    changed = client.post("/api/concept/talk/build", json={}).json()["changed"]

    assert any("계획된 결말" in line for line in changed)


def test_the_concept_is_written_into_the_history_as_its_own_round(client, stubbed):
    _say(client, "거짓말쟁이 이야기")

    session = client.post("/api/concept/talk/build", json={}).json()["session"]

    assert session["turns"][-1]["instruction"] == "대화한 내용으로 정리"


def test_there_is_nothing_to_write_down_before_anyone_has_spoken(client, stubbed, store):
    from storyweaver.models.concept import ConceptSession

    store.save(ConceptSession(status="talking"))

    response = client.post("/api/concept/talk/build", json={})

    assert response.status_code == 409
    assert "대화가 없습니다" in response.json()["detail"]


def test_writing_down_a_session_that_does_not_exist_is_a_404(client, stubbed):
    assert client.post("/api/concept/talk/build", json={}).status_code == 404


def test_a_concept_from_a_conversation_refines_like_any_other(client, stubbed, monkeypatch):
    """The two ways in meet at `chosen`, and nothing after it knows which."""
    monkeypatch.setattr(
        route.agent,
        "refine",
        lambda concept, instruction, llm=None: (
            concept.model_copy(update={"tone": "따뜻한"}),
            ["분위기: 건조하고 서늘한 → 따뜻한"],
        ),
    )
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/talk/build", json={})

    session = client.post(
        "/api/concept/refine", json={"instruction": "더 따뜻하게"}
    ).json()["session"]

    assert session["chosen"]["tone"] == "따뜻한"


def test_a_concept_from_a_conversation_commits_like_any_other(client, stubbed):
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/talk/build", json={})

    report = client.post("/api/concept/commit").json()

    assert report["characters"] == ["한서"]
    assert client.get("/api/world").json()["title"] == "거짓말쟁이의 계절"


# ==========================================================================
# The agent, with a fake model
# ==========================================================================


def test_a_reply_is_taken_as_prose(scripted_llm):
    llm = scripted_llm(str=lambda prompt, index: "그 주인공은 무엇을 두려워하나요?")

    reply = agent.talk([ConceptMessage(role="author", text="음")], llm=llm)

    assert reply == "그 주인공은 무엇을 두려워하나요?"


def test_an_empty_reply_is_an_error_rather_than_a_blank_turn(scripted_llm):
    llm = scripted_llm(str=lambda prompt, index: "   ")

    with pytest.raises(ValueError):
        agent.talk([ConceptMessage(role="author", text="음")], llm=llm)


def test_nothing_can_be_distilled_from_a_conversation_nobody_started():
    with pytest.raises(ValueError):
        agent.distill([ConceptMessage(role="ai", text="먼저 말을 걸었습니다")])


def test_the_conversation_is_written_into_the_wiki_at_commit(client, stubbed, memory):
    """For a concept worked out by talking, the reasoning *is* the conversation."""
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/talk/build", json={})
    client.post("/api/concept/commit")

    decisions = [
        entry.value
        for entry in memory.chronicle.chain("story", "story", "decisions")
    ]
    assert "[대화] 작가: 거짓말쟁이 이야기" in decisions
    assert any(line.startswith("[대화] AI:") for line in decisions)


def test_the_conversation_is_recorded_before_the_refinements(client, stubbed, memory):
    """It came first, and the refinements are footnotes to it."""
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/talk/build", json={})
    client.post("/api/concept/commit")

    decisions = [e.value for e in memory.chronicle.chain("story", "story", "decisions")]

    assert decisions[0].startswith("[대화]")
    assert decisions[-1].startswith("대화한 내용으로 정리")


# ==========================================================================
# The two ways in do not displace each other
# ==========================================================================


def test_asking_for_proposals_does_not_throw_away_the_conversation(
    client, stubbed, monkeypatch
):
    """They are tabs on one screen. Glancing at three proposals must not cost
    an author the afternoon they spent talking."""
    monkeypatch.setattr(
        route.agent, "propose", lambda seed="", count=3, llm=None: [_concept()]
    )
    _say(client, "거짓말쟁이 이야기")

    session = client.post("/api/concept/propose", json={}).json()["session"]

    assert len(session["messages"]) == 2
    assert len(session["proposals"]) == 1


def test_the_conversation_can_carry_on_after_proposals_arrive(client, stubbed, monkeypatch):
    monkeypatch.setattr(
        route.agent, "propose", lambda seed="", count=3, llm=None: [_concept()]
    )
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/propose", json={})

    session = _say(client, "역시 좀 더 얘기해보자")

    assert [m["text"] for m in session["messages"] if m["role"] == "author"] == [
        "거짓말쟁이 이야기",
        "역시 좀 더 얘기해보자",
    ]


def test_clearing_the_conversation_leaves_the_proposals(client, stubbed, monkeypatch):
    monkeypatch.setattr(
        route.agent, "propose", lambda seed="", count=3, llm=None: [_concept()]
    )
    _say(client, "거짓말쟁이 이야기")
    client.post("/api/concept/propose", json={})

    session = client.delete("/api/concept/talk").json()["session"]

    assert session["messages"] == []
    assert len(session["proposals"]) == 1


# ==========================================================================
# The shape a reply actually arrives in
# ==========================================================================


class _Message:
    def __init__(self, content):
        self.content = content


def test_a_content_block_reply_reaches_the_author_as_words():
    """Gemini answers with a list of blocks, not a string. `str()` on that list
    put `[{'type': 'text', …}]` and a signature blob in front of the author —
    which is exactly what the real model did the first time this ran."""
    result = agent.reply_text(
        _Message([{"type": "text", "text": "좋아, 천천히 가보자.", "extras": {"signature": "EpcU…"}}])
    )

    assert result == "좋아, 천천히 가보자."


def test_a_stringified_block_list_is_unwrapped_too():
    """The same leak, one layer later — the Writer's repair, reused."""
    result = agent.reply_text(_Message("[{'type': 'text', 'text': '좋아,\n천천히.'}]"))

    assert result == "좋아,\n천천히."


def test_an_ordinary_string_reply_is_left_alone():
    assert agent.reply_text(_Message("평범한 답")) == "평범한 답"


def test_several_blocks_are_joined_rather_than_one_dropped():
    result = agent.reply_text(
        _Message([{"type": "text", "text": "앞부분."}, {"type": "text", "text": "뒷부분."}])
    )

    assert result == "앞부분.\n\n뒷부분."
