# 스토리위버 시스템 아키텍처 상세 설명

> **목적**: 이 문서는 현재 우리 프로젝트가 어떻게 동작하는지를 있는 그대로 설명하는 레퍼런스 문서입니다.
> 설정 관리, 스토리 반영 방식, 생성 파이프라인, 관계 변화까지 전 과정을 설명합니다.
> 시스템을 개선하거나 새로운 기능을 추가할 때 이 문서를 먼저 읽으세요.

---

## 목차
1. [전체 데이터 흐름 요약](#1-전체-데이터-흐름-요약)
2. [설정 데이터가 어떻게 관리되는가](#2-설정-데이터가-어떻게-관리되는가)
3. [작가 설정이 스토리 생성에 어떻게 반영되는가](#3-작가-설정이-스토리-생성에-어떻게-반영되는가)
4. [스토리 생성 파이프라인](#4-스토리-생성-파이프라인)
5. [캐릭터 관계의 기록과 동적 변화](#5-캐릭터-관계의-기록과-동적-변화)
6. [현재 구조의 한계점](#6-현재-구조의-한계점)

---

## 1. 전체 데이터 흐름 요약

```
[작가 입력]
 세계관 / 캐릭터 / 에피소드 줄거리
         │
         ▼
[project.json]  ←── 모든 설정의 단일 저장소
         │
         ▼
[에피소드 생성 파이프라인]
 Director → Character Simulation → Lore Checker → Writer
         │
         ▼
[완성된 소설 본문]  → project.json에 저장
         │
         ▼
[Episode Summarizer]
 "이번 회차에서 뭐가 바뀌었나?" 분석
         │
    ┌────┴────┐
    ▼         ▼
[StructuredStore]  [VectorStore]   [PlotTracker]
 JSON 파일     ChromaDB          JSON 파일
 (정확한 상태)  (의미 검색)      (떡밥 관리)
         │
         ▼
[다음 회차 생성 시 위 저장소에서 꺼내 에이전트에 주입]
```

---

## 2. 설정 데이터가 어떻게 관리되는가

### 2-1. 단일 파일 저장소: `project.json`

작가가 UI에서 입력하는 **모든 설정**은 단 하나의 파일에 저장됩니다.

- **위치**: `data/project.json`
- **담당 클래스**: `backend/storyweaver/ui/project.py` — `Project` 모델 + `ProjectStore`
- **저장 방식**: 원자적 쓰기(`write_text_atomic`) — 저장 중 크래시해도 파일이 깨지지 않음

`project.json`에 담기는 최상위 구조:

```json
{
  "name": "내 소설 제목",
  "world": { ... },        // 세계관 설정
  "characters": [ ... ],  // 캐릭터 목록
  "episodes": [ ... ],    // 회차 및 줄거리 목록
  "style": { ... }        // 문체 설정 (글쓰기 스타일)
}
```

---

### 2-2. 세계관(WorldLore) 데이터 구조

파일: `backend/storyweaver/models/world.py`

| 필드 | 설명 |
|---|---|
| `title` | 세계관 이름 (예: "마법사의 세계") |
| `genre` | 장르 (예: "fantasy", "sci-fi") |
| `tone` | 분위기 (예: "dark", "lighthearted") |
| `era` | 시대적 배경 (선택) |
| `overview` | 세계관 서술 (자유 텍스트) |
| `rules` | **세계의 규칙 목록** — 각 규칙에 `id`, `category`, `statement` 포함 |
| `locations` | **장소 목록** — 각 장소에 `id`, `name`, `description`, 부모 장소 포함 |
| `factions` | 세력/집단 목록 |
| `additional_lore` | 기타 설정 (자유 키-값 쌍) |

> **⚠️ 중요**: `rules`는 단순 메모가 아닙니다. 생성 중 **Lore Checker 에이전트가 이 규칙들을 기준으로 대사/행동의 위반을 검사**합니다.

---

### 2-3. 캐릭터(CharacterProfile) 데이터 구조

파일: `backend/storyweaver/models/character.py`

| 필드 | 설명 | LLM 프롬프트 전달 여부 |
|---|---|---|
| `id` | 고유 슬러그 (예: `kim-junho`) | ✅ (식별자로 사용) |
| `name` | 이름 | ✅ |
| `role` | 역할 (주인공, 조력자 등) | ❌ 현재 미전달 |
| `age` | 나이 | ❌ **현재 미전달** |
| `gender` | 성별 | ❌ **현재 미전달** |
| `appearance` | 외모 묘사 | ✅ (Writer에게만) |
| `personality_summary` | 성격 요약 | ✅ |
| `traits` | 성격 특성 목록 (강도 포함) | ✅ |
| `speech_style` | **말투 스타일** | ✅ |
| `values` | 가치관 목록 | ✅ |
| `goals` | 목표 목록 | ✅ |
| `backstory` | 과거사 | ❌ 현재 미전달 |
| `relationships` | **초기 관계 설정** | ✅ |
| `secrets` | 비밀 (다른 캐릭터들에게 숨김) | ✅ |
| `author_notes` | 작가 메모 (시스템만 봄) | ❌ |

> **⚠️ 알려진 문제**: `age`와 `gender`가 LLM에 전달되지 않아서, 나이 차이에 따른 경어/반말
> 구분이 자동으로 이루어지지 않습니다. `speech_style`에 직접 "연상의 인물에게는 존댓말을
> 쓴다"고 명시해야 임시 해결이 됩니다.

---

### 2-4. 글쓰기 스타일(WritingStyle) 데이터 구조

파일: `backend/storyweaver/models/style.py`

| 필드 | 기본값 | 설명 |
|---|---|---|
| `perspective` | `third_person_limited` | 시점 (3인칭 한정 / 전지적 / 1인칭) |
| `pov_character_id` | `null` | 시점 캐릭터 id (한정 시점 시 사용) |
| `tense` | `past` | 시제 (과거형 / 현재형) |
| `prose_density` | `moderate` | 묘사 밀도 (sparse / moderate / lush) |
| `dialogue_ratio` | `0.4` | 대화 비중 (0.0 ~ 1.0) |
| `target_word_count_per_scene` | `1400` | 씬당 목표 글자수 (한국어는 자 단위) |
| `language` | `ko` | 출력 언어 |
| `author_style_notes` | `""` | 자유 스타일 지시 (예: "김영하처럼 써라") |

---

### 2-5. 회차(Episode) 데이터 구조

파일: `backend/storyweaver/models/episode.py`

| 필드 | 언제 채워지는가 |
|---|---|
| `episode_number` | 작가가 회차 추가할 때 |
| `author_storyline` | **작가가 직접 입력하는 이번 회차의 줄거리 (핵심 입력값)** |
| `title` | 작가 또는 자동 생성 |
| `scenes` | Director 에이전트가 채움 |
| `final_text` | Writer 에이전트가 채움 |
| `summary` | Episode Summarizer가 채움 |
| `status` | queued → in_progress → completed |
| `pacing` | slow / normal / fast |

---

## 3. 작가 설정이 스토리 생성에 어떻게 반영되는가

작가의 설정이 LLM에게 전달되는 방식은 **텍스트 블록 주입(prompt injection)**입니다.
설정값을 포맷팅된 텍스트로 변환하는 역할은 `backend/storyweaver/agents/context.py`가 담당합니다.

### 에이전트별 주입 내용

#### Director 에이전트 (씬 구성 담당)

- 세계관 제목, 장르, 분위기, 시대
- 세계 규칙 전체
- **캐릭터 요약** (`id — 이름: 성격 요약. Goals: ...` 형식)
  - ⚠️ 나이, 성별, 외모 미포함
- 장소 목록 전체
- 이전 에피소드 기억 (메모리 시스템에서 꺼낸 정보)

#### Character 에이전트 (대사/행동 생성 담당)

- 캐릭터의 성격 요약, **말투 스타일**, 특성, 가치관, 목표
- 해당 씬에 등장하는 상대 캐릭터와의 **현재 관계** (관계 유형 + 감정 수치 + 설명)
- 비밀 목록
- 세계관 요약 + 규칙
- 씬의 목표, 장소, 스토리 비트
- 과거 기억 (이 캐릭터가 참여한 이전 상호작용 — 시맨틱 검색)
- 지금까지 이번 씬에서 오간 대사/행동 로그
- ⚠️ **나이, 성별, 외모 미포함**

#### Writer 에이전트 (대사를 소설 본문으로 변환)

- 장르, 분위기, 시제, 시점
- 세계관 요약 + 규칙
- 씬에 등장하는 캐릭터 시트 (이름, **외모**, 성격, **말투 스타일**)
  - ⚠️ 나이, 관계 미포함
- 씬 내 대사/행동 로그 전체 (Writer가 이걸 소설로 변환)
- 이전 씬 마지막 산문 (문체 일관성 유지용)
- 묘사 밀도, 목표 글자수, 대화 비중
- 작가 스타일 지시사항 (`author_style_notes`)

---

## 4. 스토리 생성 파이프라인

에피소드 생성 버튼을 클릭하면 다음 7단계 파이프라인이 순서대로 실행됩니다.
담당 파일: `backend/storyweaver/agents/episode_runner.py`

```
START
  │
  ▼
[1단계] director_plan_scenes
  — 작가의 줄거리를 읽고 3~4개의 씬(scene)으로 분해
  — 각 씬에 목표, 등장인물, 장소, 스토리 비트, 분위기 배정
  — 메모리에서 이전 회차 정보를 꺼내 주입
  │
  ▼
[2단계] simulate_scene  ←─────────────────────────┐
  — 씬에 등장하는 각 캐릭터가 라운드-로빈 순서로    │
    돌아가며 대사/행동/생각/반응 생성               │
  — 기본 최대 20턴 (설정에서 변경 가능)             │
  — 목표가 충족되면 Supervisor가 조기 종료           │
  │                                                 │
  ▼                                                 │
[3단계] check_lore                                  │
  — 대사 로그가 세계 규칙 + 캐릭터 설정을 위반했는지 검사
  — 통과 시 → [4단계]로                             │
  — 실패 시 → 수정 지시사항 생성 후 ──────────────────┘
             (최대 2회 재시도)
  │ (통과)
  ▼
[4단계] write_scene
  — 대사 로그를 실제 소설 본문으로 변환
  — 묘사, 심리, 감각적 디테일 추가
  │
  ▼
[5단계] write_scene_transition (선택)
  — 씬과 씬 사이의 연결 문장 생성
  │
  ▼
[6단계] advance_to_next_scene
  — 다음 씬으로 이동 (또는 끝났으면 종료)
  — 진행상황 체크포인트 저장 (중간에 죽어도 이어서 가능)
  │
  ▼ (씬 루프 종료 후)
[7단계] assemble_final_text
  — 모든 씬 산문을 하나의 회차 본문으로 조합
  — 회차 제목 자동 생성 (선택)
  │
  ▼
[사후처리] Episode Summarizer
  — 이번 회차를 분석해 기억 시스템에 저장
  — 실패해도 소설 본문은 보존됨
```

---

## 5. 캐릭터 관계의 기록과 동적 변화

### 5-1. 관계의 두 가지 레이어

| 레이어 | 저장 위치 | 역할 |
|---|---|---|
| **초기 관계** (정적) | `project.json` → `CharacterProfile.relationships` | 작가가 설정한 이야기 시작 시점의 관계 |
| **변화된 관계** (동적) | `data/state/character_*.json` → `CharacterMemory.relationship_updates` | 에피소드가 진행되며 변화한 최신 관계 |

두 레이어 중 **동적 레이어가 항상 우선합니다.** Character 에이전트 프롬프트에는 다음과 같이
명시됩니다:
> *"How you feel about the others here now (this supersedes your original sheet):"*

---

### 5-2. 관계 데이터 구조

```python
class Relationship(BaseModel):
    target_character_id: str  # 상대 캐릭터 id
    type: str                 # "친구", "라이벌", "스승", "연인" 등 자유 텍스트
    sentiment: float          # -1.0 (극도의 적대) ~ 0.0 (중립) ~ 1.0 (극도의 호감)
    description: str | None   # 자유 텍스트 설명
```

---

### 5-3. 관계 변화 사이클 (에피소드마다 반복)

```
[에피소드 생성 중]
Character 에이전트가 대사를 칠 때:
  → 초기 관계 또는 이전까지 누적된 최신 관계를 프롬프트로 받음
  → 그 관계를 바탕으로 행동 결정

         ↓ 에피소드 완료 후

[Episode Summarizer 실행]
  LLM이 이번 회차의 소설을 읽고 분석:
  - "이번 회차에서 누가 누구와 어떤 중요한 사건을 겪었는가?"
  - "그 결과 관계/감정이 어떻게 변했는가?"
  출력 예시:
    {
      "character_id": "kim-junho",
      "internal_state": "배신당했다는 배신감과 혼란",
      "current_goals": ["진실을 밝혀내기", "팀에서 이탈하기"],
      "relationship_updates": [
        { "target": "park-minji", "type": "배신자", "sentiment": -0.7 }
      ]
    }

         ↓

[MemoryManager.record_episode_completion() 실행]
  → StructuredStore.update_character() 호출
  → 관계를 target_character_id 기준으로 "최신 값으로 덮어쓰기"
     (기존: "친구 +0.5" → 갱신: "배신자 -0.7")

         ↓

[다음 회차 Director 에이전트 실행 시]
  → "## Character Relationships (current state)" 섹션에
    현재 시점의 모든 캐릭터 관계 그래프가 주입됨
  → Director가 이 관계를 고려하여 씬 구성

[다음 회차 Character 에이전트 실행 시]
  → 변화된 관계가 프롬프트에 "(이 설정이 초기 캐릭터 시트를 대체함)"과 함께 주입됨
```

---

### 5-4. 메모리 3개 저장소 역할 비교

| 저장소 | 기술 | 답하는 질문 | 담당 파일 |
|---|---|---|---|
| **VectorStore** | ChromaDB (임베딩 기반) | "이 상황과 비슷한 과거 사건은?" | `memory/vector_store.py` |
| **StructuredStore** | JSON 파일 | "A와 B의 현재 관계는 정확히 무엇?" | `memory/structured_store.py` |
| **PlotThreadTracker** | JSON 파일 | "아직 회수 안 된 떡밥은?" | `memory/plot_tracker.py` |

각 에이전트가 생성 시 꺼내는 기억의 양:
- **Director**: 최근 3개 에피소드 요약 + 시맨틱 검색 결과 8개
- **Character**: 자신이 참여한 과거 사건 시맨틱 검색 5개
- **Writer**: 관련 과거 사건 시맨틱 검색 4개 + 이전 씬 산문(문체 샘플)

---

## 6. 현재 구조의 한계점

개선이 필요한 부분들을 정리합니다.

### 6-1. 캐릭터 설정 관련

| 문제 | 원인 | 영향 |
|---|---|---|
| **나이가 LLM에 전달되지 않음** | `agents/character.py`의 `build_system_prompt()`에서 `age` 필드 누락 | 연령에 따른 존댓말/반말 자동 판단 불가 |
| **성별이 LLM에 전달되지 않음** | 동일한 이유 | 성별에 따른 문체 차이 반영 불가 |
| **과거사(`backstory`)가 미전달** | 동일한 이유 | 과거사 기반 행동 동기 약함 |
| **Writer에게 관계 정보 미전달** | `agents/writer.py`의 `_character_sheets()`에서 `relationships` 누락 | 인물 간 긴장감을 산문에 자동 반영 못함 |

### 6-2. 관계 설정 UI 관련

- 관계를 한 방향(`A → B`)으로만 설정할 수 있어서, `B → A`도 별도로 입력해야 함
- 관계 유형이 자유 텍스트여서 일관성이 없을 수 있음
- 에피소드 진행 이후 관계가 어떻게 변했는지 UI에서 추적/시각화하는 기능이 없음

### 6-3. 세계관 설정 관련

- 장소 간 계층 구조(`parent_location_id`)를 UI에서 직관적으로 구성하기 어려움
- 세계 규칙 위반 시 Lore Checker가 재시도하지만, 반복 위반 원인을 작가가 직접 확인하기 어려움

### 6-4. 생성 파이프라인 관련

- 씬 시뮬레이션이 **씬 당 LLM 호출을 20회 이상** 하므로 시간/비용 소요가 큼
- 씬 내 대사가 라운드-로빈(순서대로 돌아가며) 방식이어서, 상황에 관계없이 항상 정해진 순서로 말함
- Director가 배정한 씬 구성을 작가가 사전에 검토/수정하는 기능이 없음 (완전 블랙박스 생성)

---

*최종 업데이트: 2026-09-20*
