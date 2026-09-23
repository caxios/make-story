"""The only stage whose job is to originate rather than to transform.

Two properties decide whether unlimited refinement is usable. The model is sent
the current concept and one instruction, never the transcript — so the
fiftieth round costs what the first one did. And what changed is worked out by
comparing, not asked of the model, because a model asked what it changed
reports what it meant to do.
"""

from __future__ import annotations

import pytest

from storyweaver.agents import concept as agent
from storyweaver.models.concept import (
    ConceptCharacter,
    ConceptEpisode,
    ConceptProposals,
    StoryConcept,
)


def _character(name: str, **overrides) -> ConceptCharacter:
    base = {
        "name": name,
        "role": "조연",
        "age": 17,
        "personality": "평범하다.",
        "speech": "담담한 평서체.",
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
        "rules": ["사념세계의 존재는 비밀이다."],
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


def _model(result, calls: dict | None = None):
    """A stub that records the prompt it was handed."""
    record = calls if calls is not None else {}

    class Structured:
        def invoke(self, prompt):
            record["prompt"] = prompt
            record["calls"] = record.get("calls", 0) + 1
            return result

    class Model:
        def with_structured_output(self, schema):
            record["schema"] = schema
            return Structured()

    return Model()


# ==========================================================================
# Proposing
# ==========================================================================


def test_a_spread_comes_back_from_one_call():
    """Concepts proposed in separate calls cannot be made to differ."""
    calls: dict = {}
    proposals = ConceptProposals(
        concepts=[_concept(title="첫째"), _concept(title="둘째"), _concept(title="셋째")]
    )

    result = agent.propose(llm=_model(proposals, calls))

    assert [c.title for c in result] == ["첫째", "둘째", "셋째"]
    assert calls["calls"] == 1


def test_with_no_seed_the_spread_is_told_to_range_widely(monkeypatch):
    prompt = agent.build_propose_prompt("", 3)

    assert "Range widely" in prompt
    assert "should not share a genre" in prompt


def test_a_seed_reaches_the_prompt_and_binds_all_of_them():
    prompt = agent.build_propose_prompt("학원물인데 오컬트가 섞였으면", 3)

    assert "학원물인데 오컬트가 섞였으면" in prompt
    assert "must honour it" in prompt


def test_the_prompt_asks_for_concepts_that_differ_in_kind():
    """Three variations on one premise hide the decision instead of posing it."""
    prompt = agent.build_propose_prompt()

    assert "different **in kind**" in prompt


def test_the_outline_prompt_says_the_lines_are_not_plans():
    """Each chapter is planned in detail later, and the author approves that,
    so a line here only says what the episode is for."""
    prompt = agent.build_outline_prompt(_concept())

    assert "These are not plans" in prompt
    assert "too fine" in prompt


def test_asking_for_nothing_is_refused():
    with pytest.raises(ValueError):
        agent.propose(count=0, llm=_model(ConceptProposals(concepts=[])))


def test_an_empty_spread_is_an_error_not_an_empty_list():
    """Silently returning nothing would look like a quiet success."""
    with pytest.raises(ValueError, match="no usable proposals"):
        agent.propose(llm=_model(ConceptProposals(concepts=[])))


# ==========================================================================
# A proposal has to arrive whole
# ==========================================================================


def test_a_skeleton_proposal_is_dropped_from_the_spread():
    """Found on a real run: the third concept came back as a title and a
    logline and nothing else — no cast, no arc, no ending.

    That is not a third option for the author to weigh. It is a gap dressed as
    one, and showing it would make the spread look like a choice between three
    things when it is a choice between two.
    """
    skeleton = StoryConcept(
        title="제목만", logline="한 줄만", genre="fantasy", tone="어두운"
    )
    proposals = ConceptProposals(concepts=[_concept(title="온전한"), skeleton])

    result = agent.propose(llm=_model(proposals))

    assert [c.title for c in result] == ["온전한"]


def test_what_a_proposal_is_missing_is_named():
    skeleton = StoryConcept(title="t", logline="l", genre="g", tone="tone")

    missing = agent.missing_parts(skeleton)

    assert "기획 의도" in missing
    assert "전체 아크" in missing
    assert "계획된 결말" in missing
    assert "인물" in missing


def test_a_cast_of_nobody_is_not_a_concept():
    assert agent.is_whole(_concept(characters=[])) is False


def test_a_whole_concept_needs_no_episodes():
    """The outline is drawn for the one the author keeps, not for the spread."""
    assert agent.is_whole(_concept(episodes=[])) is True


def test_a_spread_of_nothing_but_skeletons_is_an_error():
    skeleton = StoryConcept(title="t", logline="l", genre="g", tone="tone")

    with pytest.raises(ValueError, match="no usable proposals"):
        agent.propose(llm=_model(ConceptProposals(concepts=[skeleton])))


def test_the_prompt_no_longer_asks_for_episodes_in_the_spread():
    """Twelve lines across three concepts is twenty-four written to be thrown
    away — and asking for all of it is what starved the third one."""
    prompt = agent.build_propose_prompt()

    assert "Leave `episodes` empty" in prompt
    assert "Do not make the last one thinner" in prompt


# ==========================================================================
# The chapter outline
# ==========================================================================


def test_the_outline_is_drawn_for_one_concept(monkeypatch):
    from storyweaver.models.concept import ConceptOutline

    bare = _concept(episodes=[])
    drawn = ConceptOutline(
        episodes=[
            ConceptEpisode(number=1, line="첫 화"),
            ConceptEpisode(number=2, line="둘째 화"),
        ]
    )

    result = agent.outline(bare, count=2, llm=_model(drawn))

    assert [e.line for e in result.episodes] == ["첫 화", "둘째 화"]
    assert result.title == bare.title  # nothing else moved


def test_the_outline_prompt_carries_the_arc_to_land_on():
    """An outline whose last episode is not the ending has changed the book."""
    prompt = agent.build_outline_prompt(_concept(), count=12)

    assert "동혁이 사념세계에 남는다" in prompt  # the ending
    assert "at chapter resolution" in prompt


def test_an_empty_outline_is_an_error():
    from storyweaver.models.concept import ConceptOutline

    with pytest.raises(ValueError, match="empty outline"):
        agent.outline(_concept(), llm=_model(ConceptOutline(episodes=[])))


def test_an_outline_of_no_episodes_is_refused_before_the_call():
    from storyweaver.models.concept import ConceptOutline

    calls: dict = {}
    with pytest.raises(ValueError):
        agent.outline(_concept(), count=0, llm=_model(ConceptOutline(episodes=[]), calls))
    assert calls.get("calls", 0) == 0


# ==========================================================================
# Refining
# ==========================================================================


def test_refining_sends_the_concept_and_the_instruction():
    calls: dict = {}
    current = _concept()

    agent.refine(current, "주인공을 더 어리게", llm=_model(_concept(), calls))

    assert "주인공을 더 어리게" in calls["prompt"]
    assert "박동혁" in calls["prompt"]


def test_the_transcript_is_never_replayed():
    """The concept carries the state, so round fifty costs what round one did.

    The prompt is built from the concept alone; there is nowhere for a history
    to enter, which is what keeps unlimited refinement affordable.
    """
    current = _concept()

    first = agent.build_refine_prompt(current, "짧은 지시")
    fiftieth = agent.build_refine_prompt(current, "짧은 지시")

    assert first == fiftieth


def test_the_prompt_forbids_changing_what_was_not_asked_for():
    """A round that rewrites everything cannot be read, so it cannot be trusted."""
    prompt = agent.build_refine_prompt(_concept(), "좀 더 어둡게")

    assert "what genuinely must follow from it" in prompt
    assert "taking the book from them" in prompt
    assert "change the least that honestly" in prompt


def test_the_prompt_demands_the_whole_concept_back():
    """Anything the model leaves out is lost."""
    prompt = agent.build_refine_prompt(_concept(), "x")

    assert "including every part you did not change" in prompt


def test_an_empty_instruction_is_refused():
    """A refinement with nothing asked would spend a call to return the input."""
    with pytest.raises(ValueError, match="instruction"):
        agent.refine(_concept(), "   ", llm=_model(_concept()))


def test_refine_reports_what_moved():
    current = _concept()
    revised = _concept(
        characters=[
            _character("박동혁", role="주인공", age=14, relationships=["시월 — 경계하는 상대"]),
            _character("시월", role="연인 / 히로인", age=27),
        ]
    )

    _, changed = agent.refine(current, "주인공을 더 어리게", llm=_model(revised))

    assert "박동혁 · 나이: 17 → 14" in changed


# ==========================================================================
# What moved
# ==========================================================================


def test_a_short_value_is_reported_both_ways():
    changed = agent.describe_changes(_concept(), _concept(genre="thriller"))

    assert "장르: fantasy → thriller" in changed


def test_a_long_value_is_named_rather_than_quoted():
    """An arc is five paragraphs; a diff line nobody can read is not read."""
    long_arc = "가" * 200
    changed = agent.describe_changes(_concept(), _concept(arc=long_arc))

    assert "전체 아크이(가) 바뀌었습니다" in changed
    assert long_arc not in " ".join(changed)


def test_an_added_character_is_named():
    revised = _concept(
        characters=[*_concept().characters, _character("한창군", age=47)]
    )

    assert "인물 추가: 한창군" in agent.describe_changes(_concept(), revised)


def test_a_removed_character_is_named():
    revised = _concept(characters=[_concept().characters[0]])

    assert "인물 삭제: 시월" in agent.describe_changes(_concept(), revised)


def test_list_additions_and_removals_are_separated():
    revised = _concept(locations=["학교", "사념세계"])

    changed = agent.describe_changes(_concept(), revised)

    assert "장소 추가: 사념세계" in changed
    assert "장소 삭제: 차원게이트" in changed


def test_a_change_in_episode_count_is_reported():
    revised = _concept(episodes=[ConceptEpisode(number=1, line="하나뿐")])

    assert "회차 수: 2개 → 1개" in agent.describe_changes(_concept(), revised)


def test_rewritten_episode_lines_are_counted():
    revised = _concept(
        episodes=[
            ConceptEpisode(number=1, line="완전히 다른 1화"),
            ConceptEpisode(number=2, line="정체를 들킬 뻔한다."),
        ]
    )

    assert "회차 구상 1개가 바뀌었습니다" in agent.describe_changes(_concept(), revised)


def test_an_unchanged_concept_says_so_rather_than_nothing():
    """An empty list would read as "it worked" when nothing happened."""
    assert agent.describe_changes(_concept(), _concept()) == ["바뀐 것이 없습니다"]


def test_a_relationship_change_is_reported_without_quoting_it():
    revised = _concept(
        characters=[
            _character("박동혁", role="주인공", relationships=["시월 — 신뢰하는 동료"]),
            _character("시월", role="연인 / 히로인", age=27),
        ]
    )

    assert "박동혁 · 인간관계가 바뀌었습니다" in agent.describe_changes(_concept(), revised)


# ==========================================================================
# Tidying what a model routinely gets slightly wrong
# ==========================================================================


def test_episodes_are_renumbered_from_one(monkeypatch):
    messy = _concept(
        episodes=[
            ConceptEpisode(number=5, line="첫째"),
            ConceptEpisode(number=9, line="둘째"),
        ]
    )

    result, _ = agent.refine(_concept(), "x", llm=_model(messy))

    assert [e.number for e in result.episodes] == [1, 2]


def test_a_blank_episode_line_is_dropped():
    messy = _concept(
        episodes=[
            ConceptEpisode(number=1, line="진짜"),
            ConceptEpisode(number=2, line="   "),
        ]
    )

    result, _ = agent.refine(_concept(), "x", llm=_model(messy))

    assert [e.line for e in result.episodes] == ["진짜"]


def test_a_relationship_naming_nobody_is_dropped():
    """It would become a dangling id at commit, pointing at nobody."""
    messy = _concept(
        characters=[
            _character("박동혁", relationships=["없는사람 — 친구", "시월 — 동료"]),
            _character("시월"),
        ]
    )

    result, _ = agent.refine(_concept(), "x", llm=_model(messy))

    assert result.character("박동혁").relationships == ["시월 — 동료"]


def test_a_character_cannot_have_a_relationship_with_themselves():
    messy = _concept(
        characters=[_character("박동혁", relationships=["박동혁 — 나 자신"]), _character("시월")]
    )

    result, _ = agent.refine(_concept(), "x", llm=_model(messy))

    assert result.character("박동혁").relationships == []


def test_tidying_does_not_invent():
    """It fixes shape, never content."""
    clean = _concept()

    result, changed = agent.refine(clean, "x", llm=_model(clean.model_copy(deep=True)))

    assert result == clean
    assert changed == ["바뀐 것이 없습니다"]


# ==========================================================================
# Wiring
# ==========================================================================


def test_the_concept_stage_is_the_warmest_one():
    """It is the only stage asked to originate rather than to transform."""
    from storyweaver.llm import STAGE_TEMPERATURES

    assert STAGE_TEMPERATURES["concept"] == max(STAGE_TEMPERATURES.values())


def test_both_calls_run_on_the_concept_stage():
    calls: dict = {}

    def fake_get_llm(stage="unknown", **kwargs):
        calls["stage"] = stage
        return _model(ConceptProposals(concepts=[_concept()]))

    import storyweaver.agents.concept as module

    original = module.get_llm
    module.get_llm = fake_get_llm
    try:
        agent.propose()
        assert calls["stage"] == "concept"
    finally:
        module.get_llm = original
