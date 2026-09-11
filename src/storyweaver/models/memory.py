"""Memory data models — the growing 'story bible'."""

from __future__ import annotations

from pydantic import BaseModel, Field

from storyweaver.models.character import Relationship


class InteractionRecord(BaseModel):
    """A record of a meaningful interaction between characters."""

    episode_number: int
    scene_number: int
    participants: list[str]         # character IDs
    summary: str                    # what happened
    emotional_impact: dict[str, str] = Field(default_factory=dict)  # char_id -> how it affected them
    plot_threads_opened: list[str] = Field(default_factory=list)    # foreshadowing / 떡밥
    plot_threads_resolved: list[str] = Field(default_factory=list)


class CharacterMemory(BaseModel):
    """Accumulated memory for a single character."""

    character_id: str
    interaction_history: list[InteractionRecord] = Field(default_factory=list)
    relationship_updates: list[Relationship] = Field(default_factory=list)  # evolving relationships
    internal_state: str = ""        # current emotional/mental state summary
    current_goals: list[str] = Field(default_factory=list)  # what they are chasing right now
    last_updated_episode: int = 0   # highest episode this memory has absorbed


class StoryMemory(BaseModel):
    """Global story memory — the 'bible' that grows with each episode."""

    world_lore_updates: list[str] = Field(default_factory=list)   # newly revealed lore
    active_plot_threads: list[str] = Field(default_factory=list)  # unresolved 떡밥
    resolved_plot_threads: list[str] = Field(default_factory=list)
    episode_summaries: dict[int, str] = Field(default_factory=dict)  # episode_number -> summary
    # The literal closing passage of each episode. A summary says what happened;
    # this says where everyone was standing when the curtain fell, which is what
    # the next episode has to pick up from.
    episode_closings: dict[int, str] = Field(default_factory=dict)
    character_memories: dict[str, CharacterMemory] = Field(default_factory=dict)
