# Phase 1 (Backend): Natural Language Parse API

**Depends on:** Nothing. Can be implemented independently of Phase 1 Frontend.  
**Goal:** Two new POST endpoints that accept free-text descriptions and return fully-populated model objects.

---

## Files to Create / Modify

| # | File | Action |
|---|---|---|
| 1 | `backend/storyweaver/api/parse.py` | **CREATE** — two endpoints |
| 2 | `backend/storyweaver/api/__init__.py` | **MODIFY** — register `parse.router` |

---

## How the Existing LLM Infrastructure Works

Before writing `parse.py`, understand the patterns used elsewhere:

### `get_llm()` — `backend/storyweaver/llm.py`
Returns a configured LangChain LLM (model, temperature, API key all read from env). Usage:
```python
from storyweaver.llm import get_llm
llm = get_llm()
result = llm.invoke("your prompt string")
prose = result.content  # str
```

### Structured output (JSON from LLM) — pattern from `director.py`
The Director agent instructs the LLM to return JSON, then parses it with Pydantic. The same pattern applies here. Look at how `director.py` uses `.with_structured_output()` or JSON extraction. Two approaches exist in the codebase:

**Option A — `with_structured_output` (preferred if the model supports it):**
```python
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile

llm = get_llm()
structured = llm.with_structured_output(CharacterProfile)
result = structured.invoke(prompt)  # result is already a CharacterProfile
```

**Option B — prompt returns raw JSON, parse manually:**
```python
import json, re

def _extract_json(text: str) -> str:
    """Strip markdown code fences if present."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text.strip()

result = llm.invoke(prompt)
data = json.loads(_extract_json(result.content))
profile = CharacterProfile.model_validate(data)
```

Use **Option A** first; fall back to Option B if the model rejects the schema.

### Router registration pattern — `backend/storyweaver/api/__init__.py`
```python
ROUTERS = [
    project.router,
    world.router,
    characters.router,
    episodes.router,
    generation.router,
    memory.router,
    export.router,
    telemetry.router,
]
```
New routers are added to this list. The main `app.py` (or wherever FastAPI is assembled) iterates `ROUTERS` and calls `app.include_router(r)` for each.

---

## File 1: `backend/storyweaver/api/parse.py` (CREATE)

```python
"""Parse endpoints — turn free-text author descriptions into structured data.

These endpoints call the LLM to extract a CharacterProfile or WorldLore from
whatever the author has written. The result is returned for the frontend to
preview and edit; nothing is saved to disk here.
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from storyweaver.api.deps import get_project
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, WorldLore
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/parse", tags=["parse"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ParseCharacterRequest(BaseModel):
    text: str
    existing_character_ids: list[str] = []


class ParseWorldRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """Strip markdown code fences and return the raw JSON string."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text.strip()


def _build_character_prompt(text: str, existing_ids: list[str]) -> str:
    existing_note = (
        f"The id must NOT be any of these (already taken): {existing_ids}"
        if existing_ids
        else "Any valid slug is fine."
    )
    return f"""\
You are a story-bible assistant. Extract a character profile from the author's description below.
Return ONLY valid JSON — no markdown, no explanation, no extra keys.

{existing_note}

JSON schema to follow exactly:
{{
  "id": "<slug: lowercase letters, digits, hyphens only; unique>",
  "name": "<full name>",
  "role": "<one of: 주인공, 적대자 / 악역, 서브 주인공, 조연, 스승 / 조력자, 라이벌 / 대조 인물, 연인 / 히로인, 단역 / 엑스트라>",
  "aliases": [],
  "age": <integer or null>,
  "gender": "<string or null>",
  "appearance": "<physical description paragraph>",
  "personality_summary": "<2–3 sentence personality summary>",
  "traits": [
    {{"name": "<trait name>", "intensity": <0.0–1.0>, "description": "<optional elaboration or null>"}}
  ],
  "speech_style": "<how they speak: formality level, dialect, verbal tics, sentence length>",
  "values": ["<value 1>", "<value 2>"],
  "goals": ["<goal 1>", "<goal 2>"],
  "backstory": "<background paragraph>",
  "relationships": [
    {{
      "target_character_id": "<slug of the other character, if mentioned>",
      "type": "<relationship type in Korean>",
      "sentiment": <-1.0 to 1.0>,
      "description": "<one sentence>"
    }}
  ],
  "secrets": ["<secret>"],
  "author_notes": ""
}}

Infer as much as you can from the description. Where information is absent, use sensible
defaults (empty lists, null for optional scalars). Do not invent information that is not
implied by the text.

Author's description:
{text}
"""


def _build_world_prompt(text: str) -> str:
    return f"""\
You are a story-bible assistant. Extract a world / setting profile from the author's
description below. Return ONLY valid JSON — no markdown, no explanation.

JSON schema to follow exactly:
{{
  "title": "<story or world title>",
  "genre": "<one of: fantasy, science fiction, mystery, modern, historical, horror, romance, thriller, literary>",
  "tone": "<mood / atmosphere in 2–4 words>",
  "era": "<time period string or null>",
  "overview": "<multi-paragraph world description — preserve the author's own words where possible>",
  "rules": [
    {{
      "id": "<slug>",
      "category": "<one of: magic, physics, society, politics, technology, taboo, economy, biology>",
      "statement": "<the rule as a single declarative sentence>",
      "exceptions": ["<exception>"]
    }}
  ],
  "locations": [
    {{
      "id": "<slug>",
      "name": "<place name>",
      "description": "<one-paragraph description>",
      "parent_location_id": "<slug of enclosing location or null>",
      "notable_features": ["<feature>"]
    }}
  ],
  "factions": ["<faction name>"],
  "additional_lore": {{}}
}}

Infer rules and locations from the description. If the text mentions "only the royal family
may use magic", that is a rule. If it names a city or building, that is a location.
Use null / empty lists for any field the text does not address.

Author's description:
{text}
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/character", response_model=CharacterProfile)
def parse_character(
    body: ParseCharacterRequest,
    project: Project = Depends(get_project),
) -> CharacterProfile:
    """
    Extract a CharacterProfile from free-text author input.

    The result is NOT saved — the frontend receives it for preview / editing,
    then POSTs to /api/characters to persist.
    """
    llm = get_llm()
    prompt = _build_character_prompt(body.text, body.existing_character_ids)

    try:
        # Attempt structured output first (cleaner, no JSON parsing needed).
        structured_llm = llm.with_structured_output(CharacterProfile)
        return structured_llm.invoke(prompt)
    except Exception:
        # Fall back to raw JSON extraction.
        logger.warning("with_structured_output failed for parse_character; falling back to JSON extraction")

    try:
        result = llm.invoke(prompt)
        raw = _extract_json(result.content)
        return CharacterProfile.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.exception("LLM returned invalid JSON for parse_character")
        raise HTTPException(
            status_code=422,
            detail=f"The model returned output that could not be parsed into a character profile. Try simplifying your description. Details: {exc}",
        ) from exc


@router.post("/world", response_model=WorldLore)
def parse_world(body: ParseWorldRequest) -> WorldLore:
    """
    Extract a WorldLore from free-text author input.

    The result is NOT saved — the frontend receives it for preview / editing,
    then PUTs to /api/world to persist.
    """
    llm = get_llm()
    prompt = _build_world_prompt(body.text)

    try:
        structured_llm = llm.with_structured_output(WorldLore)
        return structured_llm.invoke(prompt)
    except Exception:
        logger.warning("with_structured_output failed for parse_world; falling back to JSON extraction")

    try:
        result = llm.invoke(prompt)
        raw = _extract_json(result.content)
        return WorldLore.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.exception("LLM returned invalid JSON for parse_world")
        raise HTTPException(
            status_code=422,
            detail=f"The model returned output that could not be parsed into a world profile. Details: {exc}",
        ) from exc
```

---

## File 2: `backend/storyweaver/api/__init__.py` (MODIFY)

**Current content:**
```python
from storyweaver.api import (
    characters,
    episodes,
    export,
    generation,
    memory,
    project,
    telemetry,
    world,
)

ROUTERS = [
    project.router,
    world.router,
    characters.router,
    episodes.router,
    generation.router,
    memory.router,
    export.router,
    telemetry.router,
]
```

**Add `parse` to both the import and the `ROUTERS` list:**
```python
from storyweaver.api import (
    characters,
    episodes,
    export,
    generation,
    memory,
    parse,          # <-- ADD
    project,
    telemetry,
    world,
)

ROUTERS = [
    project.router,
    world.router,
    characters.router,
    episodes.router,
    generation.router,
    memory.router,
    export.router,
    telemetry.router,
    parse.router,   # <-- ADD
]
```

---

## Verification

### Start the backend and test with curl

```powershell
# Start backend (from project root)
.venv\Scripts\python -m uvicorn storyweaver.app:app --reload --port 8000

# Test parse/character
$body = '{"text": "지민은 19세 미대생으로, 짧은 검은 머리카락에 조용하지만 강단 있는 성격이다. 어릴 때부터 유나와 절친한 친구였지만, 최근 유나가 비밀을 숨기고 있다는 걸 느끼고 있다.", "existing_character_ids": []}'
Invoke-RestMethod -Uri "http://localhost:8000/api/parse/character" -Method POST -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 10

# Test parse/world
$wbody = '{"text": "현대 한국 서울을 배경으로 한 스릴러. 대기업들이 정치권과 결탁해 사회를 지배한다. 주요 장소는 여의도 금융타워와 강남의 지하 클럽이다."}'
Invoke-RestMethod -Uri "http://localhost:8000/api/parse/world" -Method POST -ContentType "application/json" -Body $wbody | ConvertTo-Json -Depth 10
```

**Expected response for character:** A valid `CharacterProfile` JSON object with:
- `age: 19`
- `name` in Korean
- A relationship entry pointing to a `target_character_id` matching 유나's slug
- `role` set to one of the allowed Korean values

**Expected response for world:**
- `genre: "thriller"`
- At least one `location` for 여의도 or 강남
- `era: null` or a reasonable era string

### Also verify via the OpenAPI docs
After starting the backend, navigate to `http://localhost:8000/docs` — the `/api/parse/character` and `/api/parse/world` endpoints should appear under the **parse** tag.

---

## Notes for the Implementer

- **Do not call `get_project()`** in `parse_world` — it doesn't need the current project state. The `Depends(get_project)` in `parse_character` is included only as a convenience if you want to auto-populate `existing_character_ids` from the current cast in a future version. Remove it if unused.
- If `llm.with_structured_output()` is not available on the configured model, the fallback path will always run. That is fine — both paths produce the same result.
- The endpoints intentionally **do not save anything**. Saving is the frontend's job: after the user reviews and edits the parsed result, the frontend calls the existing `POST /api/characters` or `PUT /api/world` endpoints.
- The `id` field in `CharacterProfile` requires a slug (lowercase, hyphens). The LLM sometimes returns names with spaces or uppercase. If validation fails because of this, add a post-processing step that slugifies the `id` field before calling `model_validate`.
