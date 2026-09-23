"""Parse endpoints — turn free-text author descriptions into structured data.

The author writes a paragraph about a character or a world; these hand it to
the model and get back a filled-in `CharacterProfile` or `WorldLore`.

Nothing here is saved. The result goes to the browser to be read, corrected and
then posted to the endpoints that do save — because a model's reading of a
paragraph is a draft, and a draft the author has not seen is not a character
sheet.
"""

from __future__ import annotations

import json
import logging
import re

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from storyweaver import telemetry
from storyweaver.api import deps
from storyweaver.ids import slugify, unique_id
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, WorldLore
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/parse", tags=["parse"])

# The roles the Character Workshop offers. The model is asked for one of these
# so the parsed profile drops straight into the dropdown rather than arriving
# with a role the UI has never heard of.
ROLES = (
    "주인공",
    "적대자 / 악역",
    "서브 주인공",
    "조연",
    "스승 / 조력자",
    "라이벌 / 대조 인물",
    "연인 / 히로인",
    "단역 / 엑스트라",
)

GENRES = (
    "fantasy",
    "science fiction",
    "mystery",
    "modern",
    "historical",
    "horror",
    "romance",
    "thriller",
    "literary",
)

RULE_CATEGORIES = (
    "magic",
    "physics",
    "society",
    "politics",
    "technology",
    "taboo",
    "economy",
    "biology",
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ParseCharacterRequest(BaseModel):
    # Stripped, so a box with nothing but spaces in it is refused here rather
    # than costing a model call to find out there was nothing to read.
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    # The cast is read from the project as well, so this is only for ids the
    # browser is holding but has not saved yet.
    existing_character_ids: list[str] = Field(default_factory=list)


class ParseWorldRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """Strip markdown code fences and return the raw JSON string."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text.strip()


# Both live in `storyweaver.ids` now: committing a concept mints ids for a whole
# cast, and reaching into a route module for that would drag the whole FastAPI
# app into the import graph.
_slugify = slugify
_unique_id = unique_id


def _ask(prompt: str, schema: type[BaseModel], stage: str, what: str) -> BaseModel:
    """Ask the model for one object, structured output first, JSON second.

    `with_structured_output` is the clean path. When a model will not honour a
    schema it fails outright, so the second attempt asks for plain text and
    parses the JSON out of it — the same answer, reached the hard way.
    """
    model = telemetry.meter(get_llm(stage=stage), stage)

    try:
        return model.with_structured_output(schema).invoke(prompt)
    except Exception:  # noqa: BLE001 — the fallback below is the point
        logger.warning(
            "Structured output failed while parsing a %s; falling back to raw JSON", what
        )

    try:
        result = model.invoke(prompt)
        raw = _extract_json(str(getattr(result, "content", result)))
        return schema.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.exception("The model returned unusable output while parsing a %s", what)
        raise HTTPException(
            status_code=422,
            detail=(
                f"모델이 {what} 정보를 알아볼 수 있는 형태로 돌려주지 않았습니다. "
                f"설명을 조금 더 단순하게 적고 다시 시도해 보세요. ({exc})"
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — a dead model is not a 500 here
        logger.exception("The model call failed while parsing a %s", what)
        raise HTTPException(
            status_code=502, detail=f"모델 호출에 실패했습니다: {exc}"
        ) from exc


def _build_character_prompt(text: str, existing_ids: list[str]) -> str:
    existing_note = (
        "The id must NOT be any of these, which are already taken: "
        + ", ".join(existing_ids)
        if existing_ids
        else "Any stable slug is fine."
    )
    return f"""\
You are a story-bible assistant. Extract a character profile from the author's
description below. Return ONLY valid JSON — no markdown, no explanation, no
extra keys.

{existing_note}

JSON schema to follow exactly:
{{
  "id": "<slug: no spaces; Korean characters are fine; unique>",
  "name": "<full name>",
  "role": "<exactly one of: {' | '.join(ROLES)}>",
  "aliases": [],
  "age": <integer or null>,
  "gender": "<string or null>",
  "appearance": "<physical description paragraph>",
  "personality_summary": "<2-3 sentence personality summary>",
  "traits": [
    {{"name": "<trait name>", "intensity": <0.0-1.0>, "description": "<optional elaboration or null>"}}
  ],
  "speech_style": "<how they speak: formality, dialect, verbal tics, sentence length>",
  "values": ["<value>"],
  "goals": ["<goal>"],
  "backstory": "<background paragraph>",
  "relationships": [
    {{
      "target_character_id": "<slug of the other character, if one is mentioned>",
      "type": "<relationship type in Korean>",
      "sentiment": <-1.0 to 1.0>,
      "description": "<one sentence>"
    }}
  ],
  "secrets": ["<secret>"],
  "author_notes": ""
}}

Write every piece of prose in the language the author used.

Infer as much as the description genuinely implies, and no more. Where it says
nothing, use empty lists and null — an invented detail is worse than a blank
field, because the author will not know it was invented.

Author's description:
{text}
"""


def _build_world_prompt(text: str) -> str:
    return f"""\
You are a story-bible assistant. Extract a world / setting profile from the
author's description below. Return ONLY valid JSON — no markdown, no
explanation.

JSON schema to follow exactly:
{{
  "title": "<story or world title>",
  "genre": "<exactly one of: {', '.join(GENRES)}>",
  "tone": "<mood / atmosphere in 2-4 words>",
  "era": "<time period string or null>",
  "overview": "<multi-paragraph world description — keep the author's own words where you can>",
  "rules": [
    {{
      "id": "<slug>",
      "category": "<exactly one of: {', '.join(RULE_CATEGORIES)}>",
      "statement": "<the rule as a single declarative sentence>",
      "exceptions": ["<exception>"]
    }}
  ],
  "locations": [
    {{
      "id": "<slug>",
      "name": "<place name>",
      "description": "<one-paragraph description>",
      "parent_location_id": "<slug of the enclosing location, or null>",
      "notable_features": ["<feature>"]
    }}
  ],
  "factions": ["<faction name>"],
  "additional_lore": {{}}
}}

Write every piece of prose in the language the author used.

A rule is anything the story must not contradict: "only the royal family may
use magic" is a rule. A named city or building is a location. Nest a location
inside another with `parent_location_id` when the text says so.

Use null and empty lists for anything the text does not address. Do not invent
rules the author did not imply — the Lore Checker will enforce whatever ends up
here, on every scene.

Author's description:
{text}
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/character", response_model=CharacterProfile)
def parse_character(
    body: ParseCharacterRequest,
    project: Project = Depends(deps.get_project),
) -> CharacterProfile:
    """Read a character out of the author's own description of them.

    Nothing is saved: the browser gets this to show and let the author correct,
    and saving is a separate `POST /api/characters`.
    """
    # The saved cast as well as whatever the browser is holding unsaved, so a
    # parsed profile cannot land on an id that already belongs to someone.
    taken = {character.id for character in project.characters}
    taken.update(body.existing_character_ids)

    parsed = _ask(
        _build_character_prompt(body.text, sorted(taken)),
        CharacterProfile,
        stage="parse",
        what="캐릭터",
    )

    # Models return ids with spaces, capitals, or one that is already taken.
    # None of that is worth a failed parse, and all of it is worth fixing.
    return parsed.model_copy(
        update={"id": _unique_id(parsed.id, parsed.name, taken)}
    )


@router.post("/world", response_model=WorldLore)
def parse_world(body: ParseWorldRequest) -> WorldLore:
    """Read a world out of the author's own description of it.

    Nothing is saved: saving is a separate `PUT /api/world`.
    """
    parsed = _ask(
        _build_world_prompt(body.text), WorldLore, stage="parse", what="세계관"
    )

    # Rule and location ids are matched exactly by scenes and by the Lore
    # Checker, so they are tidied the same way a character's is.
    rules, seen_rules = [], set()
    for index, rule in enumerate(parsed.rules, start=1):
        rule_id = _unique_id(rule.id, f"rule-{index}", seen_rules)
        seen_rules.add(rule_id)
        rules.append(rule.model_copy(update={"id": rule_id}))

    locations, seen_locations = [], set()
    renamed: dict[str, str] = {}
    for index, location in enumerate(parsed.locations, start=1):
        location_id = _unique_id(location.id, location.name or f"location-{index}", seen_locations)
        seen_locations.add(location_id)
        renamed[location.id] = location_id
        locations.append(location.model_copy(update={"id": location_id}))

    # Parents are followed through the rename, and a parent that points at
    # nothing is dropped to the root rather than left dangling.
    def resolve_parent(parent: str | None) -> str | None:
        if parent is None:
            return None
        resolved = renamed.get(parent, parent)
        return resolved if resolved in seen_locations else None

    locations = [
        location.model_copy(
            update={"parent_location_id": resolve_parent(location.parent_location_id)}
        )
        for location in locations
    ]

    return parsed.model_copy(update={"rules": rules, "locations": locations})
