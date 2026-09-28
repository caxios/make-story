"""Reading an outline or a plan back for the settings it brings in.

Outlines and plans are where a serial grows: a new face in episode 14, a guild
nobody had named, a detail of someone's past that makes episode 30 work, an
ending that has quietly moved. Before this, all of it lived only in the text of
one episode, and the author had to copy it into the workshop, the world builder
and the wiki by hand — or the next planner never heard of it.

This reads the text once and returns what it establishes. What it deliberately
does **not** return is anything that *happens*: "A and B become lovers in 35",
"C dies". Those are plans, and they are recorded as history when the episode is
written — registering them now would have the characters of episode 20 already
living in episode 35.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from storyweaver import telemetry
from storyweaver.agents import context as ctx
from storyweaver.agents.prompts import render_prompt
from storyweaver.llm import MODEL_MAX_OUTPUT_TOKENS, get_llm
from storyweaver.models import Episode
from storyweaver.ui.project import Project

NO_BRIEF = "(작품 페이지에 적힌 방향이 없습니다.)"


class NewCharacter(BaseModel):
    name: str
    role: str = Field(default="조연", description="주인공, 서브 주인공, 적대자 / 악역, 조연, 단역 등")
    age: int | None = None
    gender: str | None = None
    appearance: str = ""
    personality: str = Field(default="", description="1-2문장")
    speech: str = Field(default="", description="말투")
    goal: str = ""
    secret: str = ""
    backstory: str = ""
    relationships: list[str] = Field(
        default_factory=list,
        description="'상대 이름 — 관계' 형식. 처음부터 그런 관계만 (예: 남매, 옛 동료)",
    )


class CharacterFact(BaseModel):
    """Something true of an existing character from the start, newly written down."""

    name: str = Field(description="이미 있는 인물의 이름, 인물 목록에 적힌 그대로")
    field: str = Field(
        description="backstory, secret, goal, appearance, speech, personality, relationship 중 하나"
    )
    value: str = Field(description="덧붙일 내용. relationship이면 관계를 짧게 (예: 이복남매)")
    target: str | None = Field(
        default=None, description="relationship일 때만: 상대 인물의 이름"
    )


class NewPlace(BaseModel):
    name: str
    description: str = ""


class NewFaction(BaseModel):
    name: str
    description: str = ""


class WorldFact(BaseModel):
    title: str = Field(description="짧은 제목 (예: 마나석의 성질)")
    detail: str


class DirectionUpdate(BaseModel):
    """The work's direction, rewritten whole — only when it has actually moved."""

    logline: str = ""
    arc: str = ""
    ending: str = ""


class ExtractedSettings(BaseModel):
    new_characters: list[NewCharacter] = Field(default_factory=list)
    character_facts: list[CharacterFact] = Field(default_factory=list)
    new_locations: list[NewPlace] = Field(default_factory=list)
    new_factions: list[NewFaction] = Field(default_factory=list)
    new_rules: list[str] = Field(default_factory=list)
    world_facts: list[WorldFact] = Field(default_factory=list)
    direction: DirectionUpdate | None = None

    def is_empty(self) -> bool:
        return not (
            self.new_characters or self.character_facts or self.new_locations
            or self.new_factions or self.new_rules or self.world_facts
            or (self.direction and any(
                (self.direction.logline, self.direction.arc, self.direction.ending)
            ))
        )


def plan_text(episode: Episode) -> str:
    """A saved plan, as text to read settings from."""
    lines = []
    for scene in episode.scenes:
        lines.append(f"장면 {scene.scene_number}. {scene.title}: {scene.objective}")
        lines += [f"  - {beat.description}" for beat in scene.beats if beat.description.strip()]
    return "\n".join(lines)


def build_prompt(
    project: Project, texts: Sequence[tuple[int, str, str]], *, brief: str = ""
) -> str:
    rendered = "\n\n".join(f"### {number}화 {label}\n{text.strip()}" for number, label, text in texts)
    factions = ", ".join(project.world.factions) or "(없음)"
    return render_prompt(
        "settings_extract",
        title=project.world.title or project.name,
        brief=brief.strip() or NO_BRIEF,
        cast=ctx.format_cast_for_planning(project.characters),
        world=ctx.format_world_for_planning(project.world),
        factions=factions,
        texts=rendered,
    )


def extract(
    project: Project,
    texts: Sequence[tuple[int, str, str]],
    *,
    brief: str = "",
    llm=None,
) -> ExtractedSettings:
    """What these outlines or plans establish that the work does not have yet.

    `texts` is `(episode_number, "개요" | "기획서", text)`. One call for all of
    them, so twenty outlines added at once cost one read.
    """
    prompt = build_prompt(project, texts, brief=brief)
    # Reading back, not inventing: the cold stage. Twenty outlines can bring in
    # a lot, and a cut-off answer would drop settings silently.
    model = telemetry.meter(
        llm or get_llm(stage="parse", max_output_tokens=MODEL_MAX_OUTPUT_TOKENS), "parse"
    )
    return model.with_structured_output(ExtractedSettings).invoke(prompt)


__all__ = [
    "CharacterFact",
    "DirectionUpdate",
    "ExtractedSettings",
    "NewCharacter",
    "NewFaction",
    "NewPlace",
    "WorldFact",
    "build_prompt",
    "extract",
    "plan_text",
]
