"""Partial-episode recovery.

An episode is dozens of model calls over several minutes. An API outage four
scenes in should cost you the fifth scene, not the four you already paid for —
so completed scenes are written to disk as they land, and a resumed run picks up
from the last one.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from storyweaver import config
from storyweaver.models import Scene
from storyweaver.storage import write_text_atomic

logger = logging.getLogger(__name__)

CHECKPOINT_DIRNAME = "checkpoints"


class EpisodeCheckpoint(BaseModel):
    """Everything needed to restart an episode from where it stopped."""

    episode_number: int
    author_storyline: str
    scenes: list[Scene] = Field(default_factory=list)
    scene_prose_outputs: list[str] = Field(default_factory=list)
    transitions: list[str] = Field(default_factory=list)
    current_scene_index: int = 0
    lore_reports: list[dict] = Field(default_factory=list)

    @property
    def scenes_completed(self) -> int:
        return len(self.scene_prose_outputs)

    def matches(self, episode_number: int, author_storyline: str) -> bool:
        """Whether this checkpoint is still valid for the episode being run.

        An edited storyline means the Director would now plan different scenes,
        so the saved ones are no longer the right ones to resume into.
        """
        return (
            self.episode_number == episode_number
            and self.author_storyline.strip() == author_storyline.strip()
        )


class CheckpointStore:
    """One JSON file per in-flight episode, removed when the episode completes."""

    def __init__(self, data_dir: Path | str | None = None):
        base = Path(data_dir) if data_dir is not None else config.STATE_DIR
        self.directory = base / CHECKPOINT_DIRNAME

    def path_for(self, episode_number: int) -> Path:
        return self.directory / f"episode_{episode_number}.json"

    def save(self, checkpoint: EpisodeCheckpoint) -> Path:
        path = self.path_for(checkpoint.episode_number)
        write_text_atomic(path, checkpoint.model_dump_json(indent=2) + "\n")
        logger.debug(
            "Checkpointed episode %d after %d scene(s)",
            checkpoint.episode_number,
            checkpoint.scenes_completed,
        )
        return path

    def load(self, episode_number: int) -> EpisodeCheckpoint | None:
        path = self.path_for(episode_number)
        if not path.is_file():
            return None
        try:
            return EpisodeCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.exception("Discarding unreadable checkpoint at %s", path)
            path.unlink(missing_ok=True)
            return None

    def clear(self, episode_number: int) -> None:
        self.path_for(episode_number).unlink(missing_ok=True)

    def pending(self) -> list[EpisodeCheckpoint]:
        """Every episode with an unfinished run on disk, lowest number first."""
        if not self.directory.is_dir():
            return []
        found = []
        for path in sorted(self.directory.glob("episode_*.json")):
            try:
                found.append(EpisodeCheckpoint.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, json.JSONDecodeError):
                logger.warning("Ignoring unreadable checkpoint at %s", path)
        return sorted(found, key=lambda c: c.episode_number)
