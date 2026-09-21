"""
저장소 동작 관찰 테스트
=====================================================
project.json, state/ 폴더에 데이터가 어떻게 저장/불러와지는지
직접 실험할 수 있습니다.

실행 방법:
    $env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python test.py

주의: 실제 data/ 폴더는 건드리지 않습니다.
      data_test/ 라는 임시 폴더를 사용합니다.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from storyweaver.ui.project import Project, ProjectStore
from storyweaver.memory.structured_store import StructuredStore
from storyweaver.models import CharacterProfile, WorldLore, Location, Rule
from storyweaver.models.character import Relationship, Trait

# ─────────────────────────────────────────────
# 테스트용 임시 폴더 (실제 data/ 와 분리)
# ─────────────────────────────────────────────
TEST_DATA_DIR = Path(__file__).parent / "data_test"
TEST_STATE_DIR = TEST_DATA_DIR / "state"
TEST_DATA_DIR.mkdir(exist_ok=True)
TEST_STATE_DIR.mkdir(exist_ok=True)

# 이전 테스트 잔여물 제거
for f in TEST_DATA_DIR.glob("*.json"):
    f.unlink()
for f in TEST_STATE_DIR.glob("*.json"):
    f.unlink()


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def show_file(path: Path, label: str = "") -> None:
    """파일 내용을 JSON으로 출력"""
    if not path.exists():
        print(f"  [파일 없음: {path}]")
        return
    label = label or path.name
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n--- {label} ---")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
# 샘플 캐릭터 / 세계관 데이터
# ─────────────────────────────────────────────

harry = CharacterProfile(
    id="harry",
    name="해리",
    age=17,
    gender="남",
    appearance="검은 머리, 둥근 안경",
    personality_summary="용감하고 직관적이다.",
    speech_style="친구에게는 반말, 어른에게는 존댓말.",
    traits=[Trait(name="용기", intensity=0.9)],
    values=["우정", "정의"],
    goals=["볼드모트를 물리치기"],
    secrets=["호크룩스 중 하나가 자신 안에 있다"],
    relationships=[
        Relationship(target_character_id="ron", type="절친한 친구",
                     sentiment=+0.9, description="서로를 형제처럼 여긴다"),
        Relationship(target_character_id="dumbledore", type="스승",
                     sentiment=+0.7, description="존경하지만 비밀도 의심한다"),
    ],
)

ron = CharacterProfile(
    id="ron",
    name="론",
    age=17,
    gender="남",
    appearance="빨간 머리, 키가 크고 말랐음",
    personality_summary="충성스럽고 유머 감각이 있다.",
    speech_style="구어적이고 자연스럽다.",
    traits=[Trait(name="충성심", intensity=0.95)],
    values=["가족", "우정"],
    goals=["해리 곁에 있기"],
    secrets=[],
    relationships=[
        Relationship(target_character_id="harry", type="절친한 친구", sentiment=+0.9),
    ],
)

dumbledore = CharacterProfile(
    id="dumbledore",
    name="덤블도어",
    age=115,
    gender="남",
    appearance="긴 은빛 수염",
    personality_summary="지혜롭고 온화하지만 많은 것을 혼자 짊어진다.",
    speech_style="품위 있고 신중하다.",
    traits=[Trait(name="지혜", intensity=1.0)],
    values=["사랑의 힘"],
    goals=["해리가 운명을 받아들이도록 준비시키기"],
    secrets=["해리가 죽어야 한다는 진실"],
    relationships=[
        Relationship(target_character_id="harry", type="제자",
                     sentiment=+0.8, description="깊이 아끼지만 진실을 숨긴다"),
    ],
)

world = WorldLore(
    title="마법사의 세계",
    genre="fantasy",
    tone="dark but hopeful",
    era="1990년대",
    overview="마법사와 머글이 공존하는 세계. 호그와트는 마법 학교다.",
    rules=[
        Rule(id="secrecy", category="society",
             statement="마법사의 존재는 머글에게 비밀이다",
             exceptions=["머글 출신 마법사의 가족"]),
    ],
    locations=[
        Location(id="hogwarts", name="호그와트",
                 description="스코틀랜드 산중의 마법학교",
                 notable_features=["움직이는 계단"]),
    ],
)


# ═══════════════════════════════════════════════════════════
# Part 1. ProjectStore — project.json
# ═══════════════════════════════════════════════════════════

section("Part 1-A. ProjectStore 초기화 + 빈 프로젝트 저장")
store = ProjectStore(data_dir=TEST_DATA_DIR)

print(f"project.json 경로: {store.path}")
print(f"state/ 폴더 경로:  {store.state_dir}")
print(f"파일 존재 여부: {store.exists()}")

store.save(Project())
print(f"저장 후 존재: {store.exists()}")
show_file(store.path, "빈 project.json")


section("Part 1-B. 세계관 + 캐릭터 3명 추가 → 저장")
project = store.load()
project.world = world
project.upsert_character(harry)
project.upsert_character(ron)
project.upsert_character(dumbledore)
store.save(project)

show_file(store.path, "캐릭터+세계관 저장된 project.json")
print(f"\n캐릭터 ID 목록: {[c.id for c in project.characters]}")


section("Part 1-C. 에피소드 2개 추가 → 저장")
project.add_episode("해리가 호그와트에 도착하고 론을 만난다.", title="1화 - 마법사의 세계로")
project.add_episode("첫 비행 수업. 해리의 빗자루 재능이 드러난다.", title="2화 - 첫 수업")
store.save(project)

show_file(store.path, "에피소드 추가된 project.json")
for ep in project.episodes:
    print(f"  {ep.episode_number}화 [{ep.status}]: {ep.title}")


section("Part 1-D. load() — 디스크에서 다시 불러오기")
reloaded = store.load()
print(f"캐릭터 수: {len(reloaded.characters)}")
print(f"에피소드 수: {len(reloaded.episodes)}")
print(f"세계관 제목: {reloaded.world.title}")

harry_loaded = reloaded.get_character("harry")
print(f"\n해리의 관계 (project.json에서 불러온 초기 설정):")
for r in harry_loaded.relationships:
    other = reloaded.get_character(r.target_character_id)
    name = other.name if other else r.target_character_id
    print(f"  → {name} ({r.type}) sentiment={r.sentiment:+.1f}")


section("Part 1-E. upsert_character() — 관계 sentiment 변경")
# 해리 → 론 감정이 +0.9 → +0.95 로 올라감 (트롤 사건 이후)
harry_copy = harry_loaded.model_copy(deep=True)
harry_copy.relationships[0] = Relationship(
    target_character_id="ron",
    type="절친한 친구",
    sentiment=+0.95,
    description="트롤 사건 이후 더욱 깊어진 우정",
)
project.upsert_character(harry_copy)
store.save(project)

updated = store.load().get_character("harry")
print(f"해리 → 론 sentiment: {updated.relationships[0].sentiment:+.1f}  (기존 +0.9 → 업데이트)")
print(f"설명: {updated.relationships[0].description}")


section("Part 1-F. remove_character() — ron 삭제 시 dangling 관계도 제거됨")
print(f"삭제 전 캐릭터 수: {len(project.characters)}")
print(f"삭제 전 해리 관계 수: {len(project.get_character('harry').relationships)}")

project.remove_character("ron")
store.save(project)

after = store.load()
print(f"삭제 후 캐릭터 수: {len(after.characters)}")
harry_after = after.get_character("harry")
print(f"해리의 남은 관계: {[r.target_character_id for r in harry_after.relationships]}")
print("  ↑ ron 관계가 자동으로 사라졌는지 확인")


# ═══════════════════════════════════════════════════════════
# Part 2. StructuredStore — data/state/ 폴더 (동적 기억)
# ═══════════════════════════════════════════════════════════

section("Part 2-A. StructuredStore 초기화 — 빈 상태 조회")
sstore = StructuredStore(data_dir=TEST_STATE_DIR)

print(f"state/ 경로: {sstore.data_dir}")
print(f"알려진 캐릭터 IDs (초기): {sstore.known_character_ids()}")

# 아직 아무것도 없어도 빈 CharacterMemory 객체 반환
memory = sstore.get_character("harry")
print(f"\n해리 기억 (초기):")
print(f"  character_id: {memory.character_id}")
print(f"  internal_state: '{memory.internal_state}'")
print(f"  relationship_updates: {memory.relationship_updates}")
print(f"  last_updated_episode: {memory.last_updated_episode}")


section("Part 2-B. 1화 이후 — 캐릭터 내면 상태 + 관계 기록")
sstore.update_character(
    character_id="harry",
    internal_state="호그와트에 도착해 설레면서도 불안하다. 아직 실감이 안 난다.",
    current_goals=["호그와트에 적응하기", "볼드모트 꿈 떨쳐내기"],
    relationship_updates=[
        Relationship(
            target_character_id="ron",
            type="친구",
            sentiment=+0.6,
            description="기차에서 처음 만남. 서먹하지만 호감이 간다.",
        ),
    ],
    episode=1,
)

show_file(sstore.character_path("harry"), "state/character_harry.json (1화 후)")


section("Part 2-C. 2화 이후 — 같은 target_id 관계는 덮어써짐")
# 주목: target_character_id="ron"이 이미 있으므로 replace됨 (append 아님)
sstore.update_character(
    character_id="harry",
    internal_state="트롤 사건으로 론과 헤르미온느가 진짜 친구가 됐다는 걸 느꼈다.",
    relationship_updates=[
        Relationship(
            target_character_id="ron",
            type="절친한 친구",
            sentiment=+0.85,
            description="트롤 사건 이후 진짜 친구. 론의 충성심을 직접 확인했다.",
        ),
    ],
    episode=2,
)

harry_mem = sstore.get_character("harry")
print(f"해리 내면 상태: {harry_mem.internal_state}")
print(f"last_updated_episode: {harry_mem.last_updated_episode}")
print(f"\n해리 → 론 관계 (2화 후, replace 확인):")
for r in harry_mem.relationship_updates:
    print(f"  {r.target_character_id}: [{r.type}] sentiment={r.sentiment:+.1f}")
    print(f"  설명: {r.description}")
print(f"\n★ sentiment +0.6 → +0.85 로 교체됨 (2개로 누적되지 않음)")

show_file(sstore.character_path("harry"), "state/character_harry.json (2화 후)")


section("Part 2-D. 전역 스토리 기억 — 에피소드 요약 + 플롯 실")
sstore.record_episode_summary(
    episode_number=1,
    summary="해리가 호그와트에 도착하고 론을 만났다. 기숙사 배정에서 그리핀도르가 됨.",
    opened_threads=["볼드모트 귀환 가능성", "해리 이마 흉터의 비밀"],
    closing="해리는 처음으로 진짜 집이 생긴 것 같은 따뜻함을 느끼며 잠들었다.",
)
sstore.record_episode_summary(
    episode_number=2,
    summary="첫 비행 수업에서 재능이 드러남. 퀴디치 팀 합류.",
    opened_threads=["스네이프 교수의 의심스러운 행동"],
    closing="해리는 퀴디치 연습장을 바라보며 자신이 특별한 존재임을 직감했다.",
)

show_file(sstore.story_path, "state/story_memory.json")


section("Part 2-E. 최근 에피소드 요약 조회")
recent = sstore.recent_episode_summaries(n_episodes=2)
for ep_num, summary in recent:
    print(f"  {ep_num}화: {summary}")


section("Part 2-F. state/ 폴더에 생성된 파일 목록")
print(f"알려진 캐릭터 IDs: {sstore.known_character_ids()}")
print(f"\nstate/ 폴더 파일:")
for f in sorted(TEST_STATE_DIR.glob("*.json")):
    print(f"  {f.name}  ({f.stat().st_size} bytes)")


# ═══════════════════════════════════════════════════════════
# Part 3. project.json vs state/ 비교 요약
# ═══════════════════════════════════════════════════════════

section("Part 3. project.json vs state/ — 어디에 무엇이 있나")
print("""
[project.json] — 작가가 설정한 것들 (정적 / 작가가 직접 편집)
  world.characters[].relationships  ← 초기 설정 관계 (작가가 입력)
  world.rules / locations           ← 세계관 규칙, 장소
  episodes[].author_storyline       ← 작가가 쓴 줄거리
  episodes[].final_text             ← 생성 완료된 소설 본문

[state/character_*.json] — 스토리 진행 후 진화되는 것들 (동적 / 시스템이 기록)
  internal_state        ← 현재 에피소드에서의 캐릭터 내면 상태
  relationship_updates  ← 에피소드별로 진화된 관계 (초기 설정 위에 덮어씀)
  current_goals         ← 에피소드 진행 후 변화한 목표
  interaction_history   ← 에피소드별 상호작용 기록

[state/story_memory.json] — 전체 스토리 맥락 (동적)
  episode_summaries     ← 각 회차 요약 (다음 회차 프롬프트에 주입됨)
  active_plot_threads   ← 아직 해결 안 된 떡밥 목록
  resolved_plot_threads ← 해결된 떡밥 목록
  episode_closings      ← 각 회차 마지막 문장 (다음 회차 연결용)
""")

p = store.load()
h = p.get_character("harry")
hm = sstore.get_character("harry")

if h:
    print(f"project.json의 해리 관계 (작가 초기 설정):")
    for r in h.relationships:
        print(f"  → {r.target_character_id}: {r.type} (sentiment={r.sentiment:+.1f})")

print(f"\nstate/의 해리 관계 (에피소드 2화까지 진행 후 진화):")
for r in hm.relationship_updates:
    print(f"  → {r.target_character_id}: {r.type} (sentiment={r.sentiment:+.1f})")

story = sstore.get_story()
print(f"\n현재 열린 떡밥(plot threads): {story.active_plot_threads}")
print(f"지금까지 요약된 에피소드: {list(story.episode_summaries.keys())}")


print("\n\n✅ 모든 관찰 완료!")
print(f"\n생성된 테스트 파일:")
print(f"  {TEST_DATA_DIR / 'project.json'}")
for f in sorted(TEST_STATE_DIR.glob("*.json")):
    print(f"  {f}")
