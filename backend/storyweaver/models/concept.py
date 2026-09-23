"""The concept of a novel, before it is a novel.

Everywhere else in this app the model transforms something the author wrote.
Here it originates: given nothing but an optional hint, it proposes whole
stories, and then the two of them refine one until the author is satisfied.

Nothing in here is a decision. A concept is committed by being written into the
project and the wiki as the *first* entry in each chain, so that every part of
it can be changed afterwards — a character invented at this stage can be
rewritten or deleted twenty episodes later, and the arc can be redrawn.

The shapes are deliberately loose. Rules, locations and factions are plain
strings rather than `Rule`, `Location` and `Faction`, because the concept stage
is about whether the idea is any good; ids and hierarchies are settled at
commit, where `api/parse.py`'s slugifying already does that work properly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConceptCharacter(BaseModel):
    """A proposed character, before they are a `CharacterProfile`."""

    name: str
    role: str = Field(
        default="조연",
        description="주인공 · 적대자 / 악역 · 서브 주인공 · 조연 · 스승 / 조력자 · "
        "라이벌 / 대조 인물 · 연인 / 히로인 · 단역 / 엑스트라 중 하나",
    )
    age: int | None = None
    gender: str | None = None
    appearance: str = ""
    personality: str = Field(default="", description="2-3 sentences")
    speech: str = Field(default="", description="How they talk: formality, tics, length")
    goal: str = ""
    secret: str = ""
    relationships: list[str] = Field(
        default_factory=list,
        description="'시월 — 경계하는 상대' 형식. 이 작품 안의 다른 인물만.",
    )


class ConceptEpisode(BaseModel):
    """One episode at the resolution the arc needs, and no finer.

    This is not a plan. Each chapter is planned in detail immediately before it
    is written, and the author approves that plan — so a line here only has to
    say what this episode is *for*.
    """

    number: int
    line: str = Field(description="One or two sentences. Not a plan.")


class StoryConcept(BaseModel):
    """One whole proposal: the unit the author picks and then refines."""

    title: str
    logline: str = Field(description="One sentence: who wants what, and what is in the way")
    genre: str
    tone: str = Field(description="2-4 words")
    era: str | None = None
    premise: str = Field(default="", description="2-3 paragraphs: the world and the hook")
    arc: str = Field(default="", description="Beginning, middle, end — 3-5 paragraphs")
    ending: str = Field(default="", description="Where it is meant to land")
    rules: list[str] = Field(
        default_factory=list, description="What this world will not contradict"
    )
    locations: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    characters: list[ConceptCharacter] = Field(default_factory=list)
    episodes: list[ConceptEpisode] = Field(default_factory=list)

    def character(self, name: str) -> ConceptCharacter | None:
        return next((c for c in self.characters if c.name == name), None)


class ConceptProposals(BaseModel):
    """Structured-output envelope for a spread of concepts."""

    concepts: list[StoryConcept]


class ConceptOutline(BaseModel):
    """Structured-output envelope for the chapter outline of one concept."""

    episodes: list[ConceptEpisode]


class ConceptTurn(BaseModel):
    """One round of the session, kept so the author can look back at it.

    Stored, but not replayed to the model: the concept itself carries the
    state, so a fiftieth refinement costs what the first one did.
    """

    turn: int
    instruction: str = ""          # empty on the opening proposal
    changed: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


ConceptStatus = Literal["proposing", "refining", "committed"]


class ConceptSession(BaseModel):
    """A concept being worked out. One per project, and it survives a restart."""

    seed: str = ""
    status: ConceptStatus = "proposing"
    proposals: list[StoryConcept] = Field(default_factory=list)
    chosen: StoryConcept | None = None
    turns: list[ConceptTurn] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    committed_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = _now()


__all__ = [
    "ConceptCharacter",
    "ConceptEpisode",
    "ConceptOutline",
    "ConceptProposals",
    "ConceptSession",
    "ConceptStatus",
    "ConceptTurn",
    "StoryConcept",
]
