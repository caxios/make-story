"""World / setting data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Rule(BaseModel):
    """A binding rule of the world (e.g. 'wands are required for magic')."""

    id: str
    category: str                   # "magic", "politics", "physics", ...
    statement: str                  # natural-language rule
    exceptions: list[str] = Field(default_factory=list)
    # A rule can be abolished partway through a serial — the ban is lifted, the
    # treaty collapses. `statement` cannot say that, and deleting the rule would
    # lose the fact that it used to hold, which is exactly what the chronicle
    # exists to keep.
    active: bool = True


class Location(BaseModel):
    """A place in the world, optionally nested inside a parent location."""

    id: str
    name: str
    description: str
    parent_location_id: str | None = None   # for hierarchy (Hogwarts > Great Hall)
    notable_features: list[str] = Field(default_factory=list)
    # What has become of the place: "파괴됨", "고장", "봉쇄됨". `description` is
    # prose about what it is; this is its condition now, and a place's condition
    # can go and come back — a gate breaks, and later it is repaired.
    status: str = ""


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
