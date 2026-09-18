"""Character-related data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Trait(BaseModel):
    """A single personality trait with intensity."""

    name: str                       # e.g. "courageous"
    intensity: float = 0.8          # 0.0 - 1.0
    description: str | None = None  # optional elaboration


class Relationship(BaseModel):
    """Directed relationship from this character to another."""

    target_character_id: str
    type: str                       # e.g. "friend", "rival", "mentor"
    sentiment: float = 0.0          # -1.0 (hatred) to 1.0 (love)
    description: str | None = None  # free-text nuance


class CharacterProfile(BaseModel):
    """Complete author-defined character sheet."""

    id: str                         # unique slug, e.g. "harry-potter"
    name: str
    # Where they stand in the story: "protagonist", "antagonist", "supporting",
    # "mentor", ... Free text, because a serial invents its own roles.
    role: str = ""
    aliases: list[str] = Field(default_factory=list)
    age: int | None = None
    gender: str | None = None
    appearance: str                 # free-text physical description
    personality_summary: str        # short paragraph
    traits: list[Trait] = Field(default_factory=list)
    speech_style: str               # how they talk - dialect, formality, quirks
    values: list[str] = Field(default_factory=list)   # what they care about
    goals: list[str] = Field(default_factory=list)    # current motivations
    backstory: str = ""
    relationships: list[Relationship] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)  # things other characters don't know
    author_notes: str = ""          # meta-notes only visible to the system
