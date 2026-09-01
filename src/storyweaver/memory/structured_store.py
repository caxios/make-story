"""JSON-backed exact-match store for character state and global story memory.

The vector store answers "what does this remind you of"; this store answers
"what is Hermione's relationship with Draco, exactly". Questions with one right
answer should never go through an embedding.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from storyweaver.models import CharacterMemory, InteractionRecord, Relationship, StoryMemory
from storyweaver.storage import write_text_atomic

logger = logging.getLogger(__name__)

STORY_FILENAME = "story_memory.json"
CHARACTER_PREFIX = "character_"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _character_filename(character_id: str) -> str:
    """Character ids are author-supplied slugs; keep them from escaping the directory."""
    safe = _SAFE_ID.sub("_", character_id)
    return f"{CHARACTER_PREFIX}{safe}.json"


class StructuredStore:
    """One JSON file per character, plus one for the global story memory.

    Character memories live in their own files rather than inside `StoryMemory`
    so that a fifty-episode serial does not rewrite every character's history
    each time one of them has a feeling.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)

    # --- characters --------------------------------------------------------

    def character_path(self, character_id: str) -> Path:
        return self.data_dir / _character_filename(character_id)

    def get_character(self, character_id: str) -> CharacterMemory:
        """Load a character's memory, or an empty one if they have no history yet."""
        path = self.character_path(character_id)
        if not path.is_file():
            return CharacterMemory(character_id=character_id)
        return CharacterMemory.model_validate_json(path.read_text(encoding="utf-8"))

    def save_character(self, memory: CharacterMemory) -> None:
        write_text_atomic(
            self.character_path(memory.character_id), memory.model_dump_json(indent=2) + "\n"
        )

    def known_character_ids(self) -> list[str]:
        if not self.data_dir.is_dir():
            return []
        ids = []
        for path in sorted(self.data_dir.glob(f"{CHARACTER_PREFIX}*.json")):
            try:
                ids.append(json.loads(path.read_text(encoding="utf-8"))["character_id"])
            except (KeyError, json.JSONDecodeError):
                logger.warning("Skipping unreadable character memory at %s", path)
        return ids

    def update_character(
        self,
        character_id: str,
        internal_state: str | None = None,
        current_goals: list[str] | None = None,
        relationship_updates: list[Relationship] | None = None,
        interactions: list[InteractionRecord] | None = None,
        episode: int | None = None,
    ) -> CharacterMemory:
        """Merge new state into a character's memory and persist it.

        Relationships are keyed by target: a new reading of an existing
        relationship replaces it, so the file holds the current state rather
        than an ever-growing pile of superseded ones.
        """
        memory = self.get_character(character_id)

        if internal_state is not None:
            memory.internal_state = internal_state
        if current_goals is not None:
            memory.current_goals = list(current_goals)
        if interactions:
            memory.interaction_history.extend(interactions)
        if relationship_updates:
            by_target = {r.target_character_id: r for r in memory.relationship_updates}
            for relationship in relationship_updates:
                by_target[relationship.target_character_id] = relationship
            memory.relationship_updates = list(by_target.values())
        if episode is not None:
            memory.last_updated_episode = max(memory.last_updated_episode, episode)

        self.save_character(memory)
        return memory

    # --- global story ------------------------------------------------------

    @property
    def story_path(self) -> Path:
        return self.data_dir / STORY_FILENAME

    def get_story(self, include_characters: bool = False) -> StoryMemory:
        """The global memory. Character memories are attached only on request."""
        if self.story_path.is_file():
            story = StoryMemory.model_validate_json(self.story_path.read_text(encoding="utf-8"))
        else:
            story = StoryMemory()
        if include_characters:
            story.character_memories = {
                cid: self.get_character(cid) for cid in self.known_character_ids()
            }
        return story

    def save_story(self, story: StoryMemory) -> None:
        """Persist the global memory, leaving character files to own themselves."""
        trimmed = story.model_copy(update={"character_memories": {}})
        write_text_atomic(self.story_path, trimmed.model_dump_json(indent=2) + "\n")

    def record_episode_summary(
        self,
        episode_number: int,
        summary: str,
        world_lore_updates: list[str] | None = None,
        opened_threads: list[str] | None = None,
        resolved_threads: list[str] | None = None,
    ) -> StoryMemory:
        story = self.get_story()
        story.episode_summaries[episode_number] = summary
        if world_lore_updates:
            story.world_lore_updates.extend(world_lore_updates)
        for thread in opened_threads or []:
            if thread not in story.active_plot_threads:
                story.active_plot_threads.append(thread)
        for thread in resolved_threads or []:
            if thread in story.active_plot_threads:
                story.active_plot_threads.remove(thread)
            if thread not in story.resolved_plot_threads:
                story.resolved_plot_threads.append(thread)
        self.save_story(story)
        return story

    def get_episode_summary(self, episode_number: int) -> str:
        return self.get_story().episode_summaries.get(episode_number, "")

    def recent_episode_summaries(self, n_episodes: int = 3) -> list[tuple[int, str]]:
        """The last `n_episodes` summaries, oldest first so they read in order."""
        summaries = self.get_story().episode_summaries
        latest = sorted(summaries)[-n_episodes:] if n_episodes > 0 else []
        return [(number, summaries[number]) for number in latest]
