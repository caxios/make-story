"""World / setting data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Rule(BaseModel):
    """A binding rule of the world (e.g. 'wands are required for magic')."""

    id: str
    category: str                   # "magic", "politics", "physics", ...
    statement: str                  # natural-language rule
    exceptions: list[str] = Field(default_factory=list)


class Location(BaseModel):
    """A place in the world, optionally nested inside a parent location."""

    id: str
    name: str
    description: str
    parent_location_id: str | None = None   # for hierarchy (Hogwarts > Great Hall)
    notable_features: list[str] = Field(default_factory=list)


class WorldLore(BaseModel):
    """Top-level container for the entire fictional universe."""

    title: str                      # e.g. "The Wizarding World"
    genre: str                      # "fantasy", "sci-fi", ...
    tone: str                       # "dark", "lighthearted", "epic", ...
    era: str | None = None
    overview: str                   # multi-paragraph world description
    rules: list[Rule] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    additional_lore: dict[str, str] = Field(default_factory=dict)  # open-ended key-value pairs
