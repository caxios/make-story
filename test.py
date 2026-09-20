"""
context.py 동작 관찰 테스트
=====================================================
이 파일을 실행하면 context.py의 각 함수가 실제로 어떤 텍스트를
만들어내는지 확인할 수 있습니다.

실행 방법:
    .venv\Scripts\python test.py
"""

import sys
from pathlib import Path

# backend 패키지를 import할 수 있도록 경로 추가
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from storyweaver.agents import context
from storyweaver.models import (
    CharacterProfile,
    InteractionEntry,
    Location,
    Rule,
    Scene,
    StoryBeat,
    WorldLore,
)
from storyweaver.models.character import Relationship, Trait


# ─────────────────────────────────────────────
# 테스트용 샘플 데이터 정의
# ─────────────────────────────────────────────

# 캐릭터 A: 주인공
harry = CharacterProfile(
    id="harry",
    name="해리",
    age=17,
    appearance="검은 머리, 둥근 안경, 이마에 번개 모양 흉터",
    personality_summary="용감하고 직관적이지만 충동적인 면이 있다. 불의를 참지 못한다.",
    speech_style="직접적이고 솔직하다. 친구에게는 반말, 어른에게는 존댓말.",
    traits=[
        Trait(name="용기", intensity=0.9, description="위험에도 주저하지 않고 나선다"),
        Trait(name="충동성", intensity=0.7, description="먼저 행동하고 나중에 생각하는 경향"),
    ],
    values=["우정", "정의", "희생"],
    goals=["볼드모트를 물리치기", "친구들 지키기"],
    secrets=["호크룩스 중 하나가 자신 안에 있다"],
    relationships=[
        Relationship(
            target_character_id="ron",
            type="절친한 친구",
            sentiment=+0.9,
            description="서로를 형제처럼 여긴다",
        ),
        Relationship(
            target_character_id="dumbledore",
            type="스승",
            sentiment=+0.7,
            description="존경하지만 비밀을 감춘다는 의심도 품는다",
        ),
    ],
)

# 캐릭터 B: 조력자
ron = CharacterProfile(
    id="ron",
    name="론",
    age=17,
    appearance="빨간 머리, 키가 크고 말랐음",
    personality_summary="충성스럽고 유머 감각이 있지만 질투심도 강하다.",
    speech_style="구어적이고 자연스럽다. 때로 말보다 행동이 앞선다.",
    traits=[
        Trait(name="충성심", intensity=0.95),
        Trait(name="질투심", intensity=0.5, description="친구의 명성을 가끔 부러워한다"),
    ],
    values=["가족", "우정"],
    goals=["해리 곁에 있기"],
    secrets=[],
    relationships=[
        Relationship(target_character_id="harry", type="절친한 친구", sentiment=+0.9),
    ],
)

# 캐릭터 C: 나이 많은 스승
dumbledore = CharacterProfile(
    id="dumbledore",
    name="덤블도어",
    age=115,
    appearance="긴 은빛 수염, 반달 모양 안경",
    personality_summary="지혜롭고 온화하지만 많은 것을 혼자 짊어진다.",
    speech_style="품위 있고 신중하다. 직접 말하기보다 돌려 말하는 경우가 많다.",
    traits=[Trait(name="지혜", intensity=1.0)],
    values=["사랑의 힘", "더 큰 선"],
    goals=["해리가 자신의 운명을 받아들이도록 준비시키기"],
    secrets=["해리가 죽어야 한다는 진실을 알고 있다"],
    relationships=[
        Relationship(
            target_character_id="harry",
            type="제자",
            sentiment=+0.8,
            description="깊이 아끼지만, 더 큰 목적을 위해 진실을 숨긴다",
        ),
    ],
)

characters = {"harry": harry, "ron": ron, "dumbledore": dumbledore}

# 세계관
world = WorldLore(
    title="마법사의 세계",
    genre="fantasy",
    tone="dark but hopeful",
    era="1990년대",
    overview="마법사와 머글이 공존하는 세계. 호그와트는 마법 학교이며, 어둠의 마법사 볼드모트의 위협이 도사린다.",
    rules=[
        Rule(
            id="secrecy",
            category="사회 규칙",
            statement="마법사의 존재는 머글에게 비밀이다",
            exceptions=["머글 출신 마법사의 가족"],
        ),
        Rule(
            id="unforgivable",
            category="마법 규칙",
            statement="용서받지 못할 3개의 저주는 사용이 금지된다",
        ),
    ],
    locations=[
        Location(
            id="hogwarts",
            name="호그와트",
            description="스코틀랜드 산중에 위치한 마법학교",
            notable_features=["움직이는 계단", "말하는 초상화"],
        ),
        Location(
            id="great-hall",
            name="대강당",
            description="식사와 중요 행사가 열리는 대형 홀",
            parent_location_id="hogwarts",
            notable_features=["마법으로 하늘이 보이는 천장"],
        ),
    ],
)

# 씬
scene = Scene(
    scene_number=1,
    title="대강당에서의 재회",
    location_id="great-hall",
    participating_character_ids=["harry", "ron", "dumbledore"],
    objective="해리가 론에게 새 학기 계획을 털어놓는다",
    beats=[
        StoryBeat(description="해리가 론을 찾아 대강당으로 들어선다", mood="cautious"),
        StoryBeat(description="덤블도어가 예상치 못하게 합류한다"),
    ],
)

# 대화 로그
interaction_log = [
    InteractionEntry(turn=1, character_id="harry", type="dialogue",
                     content="론, 방학 때 무슨 일 있었어?", directed_at="ron"),
    InteractionEntry(turn=2, character_id="ron", type="dialogue",
                     content="별거 없었어. 근데 너는? 또 뭔가 숨기고 있지?", directed_at="harry"),
    InteractionEntry(turn=3, character_id="harry", type="thought",
                     content="호크룩스 얘기를 꺼내야 할까... 아직은 아니야."),
    InteractionEntry(turn=4, character_id="dumbledore", type="action",
                     content="뒤에서 조용히 다가와 두 사람 곁에 자리를 잡는다"),
    InteractionEntry(turn=5, character_id="dumbledore", type="dialogue",
                     content="해리, 잠깐 얘기할 수 있겠나?", directed_at="harry"),
]


# ─────────────────────────────────────────────
# 헬퍼: 섹션 구분선 출력
# ─────────────────────────────────────────────
def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ─────────────────────────────────────────────
# 각 함수 동작 관찰
# ─────────────────────────────────────────────

section("1. format_bullets() — 문자열 목록을 불릿 텍스트로")
print(context.format_bullets(["우정", "정의", "희생"]))

print("\n--- 빈 목록이면? ---")
print(context.format_bullets([]))


section("2. format_world_summary() — 세계관 요약 텍스트")
print(context.format_world_summary(world))


section("3. format_rules() — 세계 규칙 텍스트")
# ★ 규칙에 examples가 있으면 괄호 안에 표시됩니다.
print(context.format_rules(world.rules))


section("4. format_locations() — 장소 목록 텍스트")
# ★ parent_location_id가 있으면 "(inside ...)"가 추가됩니다.
print(context.format_locations(world.locations))


section("5. format_character_summaries() — Director에게 보내는 캐릭터 요약")
# ★ 나이(age)가 포함되지 않는다는 점을 직접 확인하세요!
print(context.format_character_summaries(list(characters.values())))


section("6. format_traits() — 특정 캐릭터의 성격 특성")
print(f"해리의 특성:\n{context.format_traits(harry)}")


section("7. format_relationships() — 씬에서의 관계 텍스트")
# ★ present_ids에 있는 캐릭터와의 관계만 걸러서 보여줍니다.
# ★ 자기 자신(harry)은 자동으로 제외됩니다.
print("해리 시점 / 씬 참여자: harry, ron, dumbledore")
print(context.format_relationships(
    harry,
    present_ids=["harry", "ron", "dumbledore"],
    characters=characters,
))

print("\n--- 씬에 ron만 있다면? (dumbledore 관계는 안 나와야 함) ---")
print(context.format_relationships(
    harry,
    present_ids=["harry", "ron"],
    characters=characters,
))


section("8. format_beats() — 씬의 스토리 비트")
# ★ mood가 있는 비트는 끝에 "(mood: ...)"가 붙습니다.
print(context.format_beats(scene.beats))


section("9. present_character_names() — 씬 참여자 이름 나열")
print(context.present_character_names(
    scene.participating_character_ids, characters
))


section("10. format_interaction_log() — 대화 로그 렌더링")

print("── 기본 (character_id로 표시) ──")
print(context.format_interaction_log(interaction_log))

print("\n── 캐릭터 이름으로 표시 ──")
print(context.format_interaction_log(interaction_log, characters=characters))

print("\n── 턴 번호 포함 — show_turns=True (Lore Checker용) ──")
print(context.format_interaction_log(
    interaction_log, characters=characters, show_turns=True
))

print("\n── 마지막 3턴만 — limit=3 ──")
print(context.format_interaction_log(
    interaction_log, limit=3, characters=characters
))

print("\n── 빈 로그라면? ──")
print(context.format_interaction_log([]))


section("11. as_character_map() — 리스트 → {id: profile} dict 변환")
char_list = list(characters.values())
char_map = context.as_character_map(char_list)
print(f"변환된 키: {list(char_map.keys())}")
print(f"harry 이름 확인: {char_map['harry'].name}")

print("\n--- 이미 dict를 넘기면 그대로 반환 ---")
char_map2 = context.as_character_map(characters)
print(f"키 동일 여부: {list(char_map2.keys()) == list(characters.keys())}")


print("\n\n✅ 모든 관찰 완료!")
print("각 섹션 출력이 실제로 LLM 프롬프트에 삽입되는 텍스트 블록 형태입니다.")
