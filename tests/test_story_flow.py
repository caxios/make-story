"""Every agent that writes an episode knows the episodes around it.

Before, each saw what had already happened and nothing of what was planned
next — so a Director could stage in episode 13 the confrontation planned for 14.
These tests pin three things:

- the flow itself: before as what happened, after as plans, labelled so;
- that it reaches every writing agent's prompt through a real pipeline run —
  Director, characters, continuity checker, Writer, transitions;
- that the planned ending still reaches the Director only.

Along with the planning view of the cast and world, and planned relationships.
"""

from __future__ import annotations

import pytest

from storyweaver.agents import context as ctx
from storyweaver.agents import director, episode_runner
from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.agents.episode_runner import EpisodeTitle, PipelineModels
from storyweaver.agents.flow import FLOW_RULES, episode_flow, flow_block
from storyweaver.agents.lore_checker import ValidationResult
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import Episode, Relationship, StoryBeat
from storyweaver.models.structure import (
    PlannedRelationship,
    RelationshipTurn,
    StoryPart,
    StoryStructure,
    describe_position,
    describe_range,
    describe_structure,
    tidy_structure,
)


def _queue() -> list[Episode]:
    episodes = []
    for n in range(1, 7):
        episodes.append(
            Episode(episode_number=n, title=f"{n}화", author_storyline=f"{n}화 계획된 줄거리")
        )
    episodes[0] = episodes[0].model_copy(
        update={"status": "completed", "final_text": "본문.", "summary": "1화에 실제로 일어난 일"}
    )
    return episodes


# ==========================================================================
# The flow
# ==========================================================================


def test_before_is_what_happened_and_after_is_a_plan():
    flow = episode_flow(_queue(), 3)

    assert "1화 (이미 쓴 회차 — 실제로 일어난 일): 1화에 실제로 일어난 일" in flow
    assert "2화 (계획): 2화 계획된 줄거리" in flow
    assert "이번 회차 — 3화: 3화 계획된 줄거리" in flow
    assert "다음 회차 (아직 일어나지 않은 계획)" in flow
    assert "4화" in flow and "6화" in flow


def test_the_window_is_two_before_and_three_after():
    flow = episode_flow(_queue(), 4)

    assert "1화" not in flow.split("이번 회차")[0]
    assert "2화" in flow and "3화" in flow


def test_an_episode_alone_has_no_flow():
    assert episode_flow(_queue()[:1], 1) == ""


def test_the_rules_travel_with_the_flow():
    assert FLOW_RULES in flow_block("무언가")
    assert FLOW_RULES not in flow_block("")


# ==========================================================================
# It reaches every writing agent, through a real run
# ==========================================================================


def _scenes() -> DirectorOutput:
    return DirectorOutput(
        scenes=[
            DraftScene(
                title="만남", objective="두 사람이 만난다.",
                participating_character_ids=["harry-potter", "ron-weasley"],
                beats=[StoryBeat(description="론이 앉아도 되냐고 묻는다.")],
            ),
            DraftScene(
                title="배정", objective="모자가 망설인다.",
                participating_character_ids=["harry-potter", "hermione-granger"],
            ),
        ]
    )


def test_every_writing_agent_sees_the_flow_and_only_the_director_sees_the_ending(
    episode, world, characters, scripted_llm
):
    seen: dict[str, list[str]] = {}

    def record(stage, answer):
        def handler(prompt, index):
            seen.setdefault(stage, []).append(prompt)
            return answer(index)
        return handler

    models = PipelineModels(
        director=scripted_llm(DirectorOutput=record("director", lambda i: _scenes())),
        character=scripted_llm(CharacterTurn=record(
            "character", lambda i: CharacterTurn(type="dialogue", content=f"대사 {i}"))),
        supervisor=scripted_llm(
            SupervisorVerdict=lambda p, i: SupervisorVerdict(objective_met=False)),
        lore=scripted_llm(ValidationResult=record(
            "lore", lambda i: ValidationResult(passed=True, violations=[]))),
        writer=scripted_llm(str=record("writer", lambda i: f"본문 {i}")),
        titler=scripted_llm(EpisodeTitle=lambda p, i: EpisodeTitle(title="제목")),
        transition=scripted_llm(str=record("transition", lambda i: "그날 오후,")),
    )

    episode_runner.run_episode(
        episode, world, characters, models=models, max_turns_per_scene=3,
        story_flow="다음 회차 (아직 일어나지 않은 계획):\n- 2화 (계획): 트롤과의 결투",
        story_brief="계획된 결말: 해리가 이긴다.",
    )

    for stage in ("director", "character", "lore", "writer", "transition"):
        assert seen.get(stage), f"{stage} was never called"
        assert all("트롤과의 결투" in prompt for prompt in seen[stage]), stage
    assert "해리가 이긴다" in seen["director"][0]
    for stage in ("character", "lore", "writer", "transition"):
        assert not any("해리가 이긴다" in prompt for prompt in seen[stage]), stage


def test_the_character_is_told_they_do_not_know_the_plan(episode, world, characters):
    from storyweaver.agents import character as character_agent

    scene = director._to_scenes(_scenes().scenes, world, characters)[0]
    prompt = character_agent.build_system_prompt(
        characters["harry-potter"],
        scene,
        world,
        characters,
        story_flow="- 5화 (계획): 비밀이 드러난다",
    )

    assert "5화 (계획): 비밀이 드러난다" in prompt
    assert "you do not know it" in prompt


# ==========================================================================
# The planning view of the cast and world
# ==========================================================================


def test_planning_sees_role_secrets_and_relationships_by_name(characters):
    harry = characters["harry-potter"].model_copy(
        update={
            "secrets": ["볼드모트와 연결되어 있다"],
            "relationships": [
                Relationship(target_character_id="ron-weasley", type="절친", description="첫 친구")
            ],
        }
    )
    text = ctx.format_cast_for_planning([harry, characters["ron-weasley"]])

    assert "볼드모트와 연결되어 있다" in text
    assert f"관계 → {characters['ron-weasley'].name}: 절친 — 첫 친구" in text
    assert "(harry-potter)" in text  # ids stay, for casting


def test_the_protagonist_is_listed_first(characters):
    cast = list(characters.values())
    lead = cast[-1].model_copy(update={"role": "주인공"})
    others = [c.model_copy(update={"role": "조연"}) for c in cast[:-1]]

    text = ctx.format_cast_for_planning([*others, lead])

    assert text.index(lead.name) < min(text.index(c.name) for c in others)


def test_planning_sees_the_rules_and_places(world):
    text = ctx.format_world_for_planning(world)

    assert world.rules[0].statement in text
    assert world.locations[0].name in text


def test_the_director_sees_the_whole_planning_cast(episode, world, characters):
    harry = characters["harry-potter"].model_copy(update={"secrets": ["숨긴 상처"]})
    prompt = director.build_prompt(episode, world, {**characters, "harry-potter": harry})

    assert "숨긴 상처" in prompt


# ==========================================================================
# Planned relationships
# ==========================================================================


def _with_relationships() -> StoryStructure:
    return tidy_structure(
        StoryStructure(
            target_episodes=400,
            parts=[StoryPart(title="1부", start=1, end=100), StoryPart(title="2부", start=101, end=400)],
            relationships=[
                PlannedRelationship(
                    characters=["강진우", "이서윤"], start="서먹한 동창", arc="서로를 지키는 사이가 된다",
                    turns=[
                        RelationshipTurn(episode=30, change="처음으로 비밀을 털어놓는다"),
                        RelationshipTurn(episode=250, change="크게 엇갈린다"),
                        RelationshipTurn(episode=900, change="범위 밖"),
                    ],
                ),
                PlannedRelationship(characters=["혼자"], arc="짝이 없는 항목"),
            ],
        )
    )


def test_a_relationship_needs_two_people_and_turns_stay_inside_the_work():
    structure = _with_relationships()

    assert len(structure.relationships) == 1
    assert [t.episode for t in structure.relationships[0].turns] == [30, 250, 400]


def test_a_turn_due_now_is_named_and_a_later_one_is_held_back():
    text = describe_position(_with_relationships(), 30)

    assert "이 즈음의 관계 변화" in text and "처음으로 비밀을 털어놓는다" in text
    assert "아직 오지 않은 관계 변화" in text and "강진우·이서윤 (250화 즈음)" in text


def test_a_range_lists_the_turns_inside_it():
    text = describe_range(_with_relationships(), 21, 40)

    assert "21~40화" in text
    assert "30화 즈음 강진우·이서윤 — 처음으로 비밀을 털어놓는다" in text
    assert "1부 '1부'(1~100화) 중 21~40화" in text


def test_the_layout_description_carries_relationships():
    assert "관계 강진우·이서윤" in describe_structure(_with_relationships())
