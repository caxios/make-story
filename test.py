"""
Director Agent (감독 에이전트) 동작 관찰 및 디버깅 테스트
=====================================================
backend/storyweaver/agents/director.py 의 핵심 로직을 단계별로 검증합니다.

검증 항목:
  Part 1. build_prompt()  : 세계관/인물/줄거리가 프롬프트로 어떻게 조립되는지
  Part 2. _to_scenes()    : LLM의 환각(없는 인물/장소) 방어 및 씬 번호 자동 정렬
  Part 3. direct_episode(): 실제 LLM(Gemini)을 호출하여 줄거리를 씬(Scene)들로 분할

실행 방법:
  $env:PYTHONIOENCODING="utf-8"; .venv\\Scripts\\python test.py

디버깅 팁:
  - Part 2의 _to_scenes() 호출 지점에 브레이크포인트를 걸고 'Step Into(F11)'를 누르면,
    director.py 내부에서 환각된 id를 어떻게 걸러내는지 직접 관찰할 수 있습니다.
"""

import sys
import os
import json
from pathlib import Path

# Windows 터미널 한글/특수문자 인코딩 설정
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# backend 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from storyweaver.models import (
    CharacterProfile,
    WorldLore,
    Location,
    Rule,
    Episode,
    StoryBeat,
)
from storyweaver.models.character import Trait, Relationship
from storyweaver.agents import director
from storyweaver.agents.director import DraftScene, DirectorOutput

# ─────────────────────────────────────────────
# 0. 테스트용 기본 데이터 (세계관, 인물, 에피소드)
# ─────────────────────────────────────────────

world = WorldLore(
    title="호그와트 마법학교",
    genre="fantasy",
    tone="mysterious and adventurous",
    era="1990s",
    overview="머글 세계 뒤편에 숨겨진 마법 세계. 호그와트 성에서 학생들이 마법을 배운다.",
    rules=[
        Rule(id="secrecy", category="magic", statement="머글 앞에서 마법을 사용해선 안 된다."),
        Rule(id="wand_rule", category="magic", statement="마법을 쓰려면 지팡이가 필요하다."),
    ],
    locations=[
        Location(id="great_hall", name="연회장", description="수천 개의 촛불이 떠 있는 대강당"),
        Location(id="potions_dungeon", name="마법약 지하교실", description="어둡고 서늘한 지하 교실"),
    ],
)

harry = CharacterProfile(
    id="harry",
    name="해리 포터",
    role="주인공",
    age=11,
    gender="남",
    appearance="검은 헝클어진 머리, 둥근 안경, 이마의 번개 흉터",
    speech_style="차분하지만 감정이 격해지면 직설적으로 말함. 친구에겐 반말.",
    personality_summary="용감하고 정의롭지만 규칙을 어기는 데 주저함이 없다.",
    traits=[Trait(name="용기", intensity=0.9)],
    goals=["부모님에 대해 더 알기", "호그와트에서 살아남기"],
)

ron = CharacterProfile(
    id="ron",
    name="론 위즐리",
    role="친구",
    age=11,
    gender="남",
    appearance="빨간 머리와 주근깨, 키가 크고 마른 체형",
    speech_style="구어체, 농담을 자주 던지고 당황하면 말이 빨라짐.",
    personality_summary="유쾌하고 충성스럽지만 열등감을 느낀다.",
    traits=[Trait(name="충성심", intensity=0.95)],
    goals=["형들에게 뒤처지지 않기"],
)

hermione = CharacterProfile(
    id="hermione",
    name="헤르미온느 그레인저",
    role="친구",
    age=11,
    gender="여",
    appearance="풍성하고 덥수룩한 갈색 머리, 단정한 교복 차림",
    speech_style="정확하고 논리적인 표준어, 교과서적인 어휘 구사.",
    personality_summary="원칙주의자이며 책에서 배운 지식을 맹신한다.",
    traits=[Trait(name="학구열", intensity=1.0)],
    goals=["모든 수업에서 최고 점수 받기"],
)

characters = [harry, ron, hermione]
char_map = {c.id: c for c in characters}

# 작가가 작성한 에피소드 줄거리
episode = Episode(
    episode_number=1,
    title="마법약 수업의 첫날",
    author_storyline=(
        "해리와 론은 첫 마법약 수업에 지각할 뻔하며 간신히 지하교실에 도착한다. "
        "스네이프 교수는 해리를 지목하며 교과서에도 없는 까다로운 질문들을 연달아 던진다. "
        "헤르미온느가 손을 높이 들지만 스네이프는 무시하고 해리를 모욕하며 감점을 준다. "
        "수업 후 해리는 스네이프가 자신을 왜 증오하는지 혼란스러워한다."
    ),
)


def section(title: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


# ═══════════════════════════════════════════════════════════
# Part 1. build_prompt() — 프롬프트 조립 로직 검증
# ═══════════════════════════════════════════════════════════
section("Part 1. build_prompt() — 감독 프롬프트 렌더링 확인")

# director.py의 build_prompt 호출
prompt = director.build_prompt(
    episode=episode,
    world=world,
    characters=characters,
    min_scenes=3,
    max_scenes=4,
    memory_context="(이전 회차 없음: 1화 시작)",
)

print(f"생성된 프롬프트 총 글자 수: {len(prompt)}자")
print(f"줄거리 포함 여부: {'첫 마법약 수업' in prompt}")
print(f"세계관 규칙 포함 여부: {'머글 앞에서 마법을' in prompt}")
print(f"장소 ID 포함 여부: {'great_hall' in prompt and 'potions_dungeon' in prompt}")
print(f"인물 ID 포함 여부: {'harry' in prompt and 'ron' in prompt and 'hermione' in prompt}")

print("\n--- [프롬프트 일부분 미리보기 (상위 800자)] ---")
print(prompt[:800] + "\n... (생략) ...")


# ═══════════════════════════════════════════════════════════
# Part 2. _to_scenes() — LLM 환각(Hallucination) 방어 검증
# ═══════════════════════════════════════════════════════════
section("Part 2. _to_scenes() — 모델의 환각 ID 제거 및 씬 번호 재정렬")

print("""
[테스트 시나리오]
LLM이 감독 역할을 수행하면서 4개의 씬(DraftScene)을 제안했다고 가정합니다.
일부러 다음과 같은 환각(오류) 데이터를 섞어 넣었습니다:
  - 씬 1: 정상 (해리, 론 참여 / 지하교실)
  - 씬 2: [환각] 존재하지 않는 캐릭터('voldemort')와 미등록 장소('moon_base') 포함
  - 씬 3: [치명적 오류] 등록된 캐릭터가 0명 ('ghost_unknown'만 참여) → 통째로 탈락되어야 함!
  - 씬 4: 정상 (해리, 헤르미온느 참여)
""")

# 가상의 LLM 제안 결과물 (DraftScene 리스트)
mock_drafts = [
    DraftScene(
        title="지하 교실로의 질주",
        objective="해리와 론이 수업에 늦지 않기 위해 뛰어간다.",
        participating_character_ids=["harry", "ron"],
        location_id="potions_dungeon",
        beats=[StoryBeat(description="복도를 뛰어가며 시간을 확인한다.", mood="hurried")],
    ),
    DraftScene(
        title="기괴한 환상",
        objective="볼드모트의 그림자가 스쳐 지나간다.",
        # 'voldemort'는 캐릭터 목록에 없음! 'moon_base'는 장소 목록에 없음!
        participating_character_ids=["harry", "voldemort"],
        location_id="moon_base",
        beats=[
            StoryBeat(
                description="달 기지에서 속삭임이 들린다.",
                involved_character_ids=["voldemort"],
                location_id="moon_base",
            )
        ],
    ),
    DraftScene(
        title="유령들의 귓속말",
        objective="알 수 없는 유령이 잡담을 나눈다.",
        # 아는 캐릭터가 아무도 없음! -> 이 씬은 통째로 삭제(skip)되어야 함!
        participating_character_ids=["ghost_unknown"],
        location_id="great_hall",
    ),
    DraftScene(
        title="스네이프의 질책과 감점",
        objective="스네이프가 해리를 질책하고 그리핀도르 점수를 깎는다.",
        participating_character_ids=["harry", "hermione"],
        location_id="potions_dungeon",
        beats=[StoryBeat(description="스네이프의 날카로운 질문 공세", mood="tense")],
    ),
]

# ★ 디버깅 포인트: 이 라인에 Breakpoint 걸고 F11(Step Into) 누르면
# director.py의 _to_scenes 함수 내부 필터링 로직을 단계별로 볼 수 있습니다!
clean_scenes = director._to_scenes(mock_drafts, world, char_map)

print(f"\n입력된 초안 씬 수: {len(mock_drafts)}개")
print(f"필터링 후 살아남은 씬 수: {len(clean_scenes)}개  (씬 3이 정상 탈락되었는지 확인)")

print("\n정제된 씬 목록:")
for s in clean_scenes:
    print(f"\n[Scene {s.scene_number}] {s.title}")
    print(f"  - 목표: {s.objective}")
    print(f"  - 참여 캐릭터: {s.participating_character_ids}  (알려진 인물만 남음)")
    print(f"  - 장소 ID: {s.location_id}  (등록되지 않은 장소는 None 처리됨)")
    for b in s.beats:
        print(f"    * 비트: {b.description} (참여: {b.involved_character_ids}, 장소: {b.location_id})")

# 검증 단언
assert len(clean_scenes) == 3, "유효하지 않은 씬 1개가 제외되어 3개여야 합니다."
assert [s.scene_number for s in clean_scenes] == [1, 2, 3], "씬 번호는 1, 2, 3으로 연속되어야 합니다."
assert "voldemort" not in clean_scenes[1].participating_character_ids, "voldemort는 제거되어야 합니다."
assert clean_scenes[1].location_id is None, "moon_base는 None으로 정제되어야 합니다."
print("\n✅ Part 2 검증 통과: 환각 ID가 안전하게 제거되고 씬 번호가 연속으로 재배열되었습니다!")


# ═══════════════════════════════════════════════════════════
# Part 3. direct_episode() — 실제 LLM (Gemini) 호출 검증
# ═══════════════════════════════════════════════════════════
section("Part 3. direct_episode() — 실제 LLM 호출을 통한 자동 장면 분할")

# 실제 API 호출 여부 (원치 않으면 False로 변경 가능)
RUN_REAL_LLM = True

if RUN_REAL_LLM:
    print("Gemini 모델에 작가의 줄거리를 전달하여 씬(Scene) 단위로 분할 중입니다...")
    print(f"입력 줄거리:\n\"{episode.author_storyline}\"\n")

    try:
        # director.direct_episode 호출
        # (내부적으로 decompose_episode -> build_prompt -> Gemini 호출 -> _to_scenes 수행)
        directed_episode = director.direct_episode(
            episode=episode,
            world=world,
            characters=characters,
            min_scenes=3,
            max_scenes=4,
        )

        print(f"상태 변경: {episode.status} → {directed_episode.status}")
        print(f"생성된 씬 수: {len(directed_episode.scenes)}개\n")

        for scene in directed_episode.scenes:
            print(f"--------------------------------------------------")
            print(f"🎬 [Scene {scene.scene_number}] {scene.title}")
            print(f"   장소: {scene.location_id}")
            print(f"   등장인물: {scene.participating_character_ids}")
            print(f"   목표: {scene.objective}")
            if scene.beats:
                print(f"   세부 비트({len(scene.beats)}개):")
                for beat in scene.beats:
                    print(f"     - [{beat.mood or 'normal'}] {beat.description}")

        print("\n✅ Part 3 완료: 감독 에이전트가 줄거리를 성공적으로 씬으로 분할했습니다!")

    except Exception as e:
        print(f"\n⚠️ LLM 호출 중 오류 발생: {e}")
        print("API 키 또는 네트워크 상태를 확인해주세요.")
else:
    print("RUN_REAL_LLM = False 로 설정되어 있어 실제 LLM 호출을 건너뜁니다.")


print(f"\n{'=' * 65}")
print("  모든 테스트가 완료되었습니다. VS Code에서 디버깅해보세요!")
print(f"{'=' * 65}\n")
