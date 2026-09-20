"""The author's project: world, cast, episode queue, and style — on disk.

Deliberately free of Streamlit. Everything the UI does to a project happens
here, so the pages stay thin rendering shells and the logic stays testable.
"""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field

from storyweaver import config
from storyweaver.storage import write_text_atomic
from storyweaver.models import (
    CharacterProfile,
    Episode,
    Location,
    Rule,
    WorldLore,
    WritingStyle,
)

logger = logging.getLogger(__name__)

PROJECT_FILENAME = "project.json"
STATE_DIRNAME = "state"
CHROMA_DIRNAME = "chromadb"

QUEUED = "queued"
# The Director has drafted the scenes; the author has not approved them yet.
PLANNED = "planned"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"


def empty_world() -> WorldLore:
    """A blank world with the fields the forms need, but nothing decided."""
    return WorldLore(title="Untitled World", genre="fantasy", tone="", overview="")


@dataclass(frozen=True)
class ProjectStats:
    """The numbers the dashboard shows."""

    episodes_total: int
    episodes_completed: int
    episodes_queued: int
    total_words: int
    character_count: int
    open_thread_count: int


class Project(BaseModel):
    """Everything the author has authored, plus the style they write it in."""

    name: str = "Untitled Story"
    world: WorldLore = Field(default_factory=empty_world)
    characters: list[CharacterProfile] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    style: WritingStyle = Field(default_factory=WritingStyle)

    # --- lookups -----------------------------------------------------------

    def character_map(self) -> dict[str, CharacterProfile]:
        return {c.id: c for c in self.characters}

    def get_character(self, character_id: str) -> CharacterProfile | None:
        return next((c for c in self.characters if c.id == character_id), None)

    def get_episode(self, episode_number: int) -> Episode | None:
        return next((e for e in self.episodes if e.episode_number == episode_number), None)

    def completed_episodes(self) -> list[Episode]:
        return [e for e in self.episodes if e.status == COMPLETED]

    def next_queued_episode(self) -> Episode | None:
        """The next episode to work on: the first one not yet written."""
        return next(
            (e for e in self.episodes if e.status in (QUEUED, PLANNED)), None
        )

    def next_episode_number(self) -> int:
        return max((e.episode_number for e in self.episodes), default=0) + 1

    def stats(self, open_thread_count: int = 0) -> ProjectStats:
        completed = self.completed_episodes()
        return ProjectStats(
            episodes_total=len(self.episodes),
            episodes_completed=len(completed),
            # Planned counts as queued: both mean "written outline, no prose".
            episodes_queued=sum(
                1 for e in self.episodes if e.status in (QUEUED, PLANNED)
            ),
            total_words=sum(len(e.final_text.split()) for e in completed),
            character_count=len(self.characters),
            open_thread_count=open_thread_count,
        )

    # --- characters --------------------------------------------------------

    def upsert_character(self, character: CharacterProfile) -> None:
        """Add a character, or replace the one with the same id in place."""
        for index, existing in enumerate(self.characters):
            if existing.id == character.id:
                self.characters[index] = character
                return
        self.characters.append(character)

    def remove_character(self, character_id: str) -> None:
        """Delete a character and every relationship pointing at them.

        Leaving dangling targets behind would put ids in prompts that no longer
        resolve to anyone.
        """
        self.characters = [c for c in self.characters if c.id != character_id]
        for character in self.characters:
            character.relationships = [
                r for r in character.relationships if r.target_character_id != character_id
            ]

    def clone_character(self, character_id: str, new_id: str, new_name: str) -> CharacterProfile:
        """Duplicate a character as a starting point for a new one."""
        source = self.get_character(character_id)
        if source is None:
            raise KeyError(f"No character with id {character_id!r}")
        if self.get_character(new_id) is not None:
            raise ValueError(f"A character with id {new_id!r} already exists")
        clone = source.model_copy(deep=True, update={"id": new_id, "name": new_name})
        self.characters.append(clone)
        return clone

    # --- world -------------------------------------------------------------

    def upsert_rule(self, rule: Rule) -> None:
        for index, existing in enumerate(self.world.rules):
            if existing.id == rule.id:
                self.world.rules[index] = rule
                return
        self.world.rules.append(rule)

    def remove_rule(self, rule_id: str) -> None:
        self.world.rules = [r for r in self.world.rules if r.id != rule_id]

    def upsert_location(self, location: Location) -> None:
        for index, existing in enumerate(self.world.locations):
            if existing.id == location.id:
                self.world.locations[index] = location
                return
        self.world.locations.append(location)

    def remove_location(self, location_id: str) -> None:
        """Delete a location and re-parent anything nested inside it."""
        self.world.locations = [l for l in self.world.locations if l.id != location_id]
        for location in self.world.locations:
            if location.parent_location_id == location_id:
                location.parent_location_id = None

    def location_tree(self) -> list[tuple[int, Location]]:
        """Locations as `(depth, location)`, parents before their children."""
        by_parent: dict[str | None, list[Location]] = {}
        known = {l.id for l in self.world.locations}
        for location in self.world.locations:
            # A parent outside the world is no parent at all — show it at the root.
            parent = location.parent_location_id
            by_parent.setdefault(parent if parent in known else None, []).append(location)

        ordered: list[tuple[int, Location]] = []
        seen: set[str] = set()

        def walk(parent: str | None, depth: int) -> None:
            for location in by_parent.get(parent, []):
                if location.id in seen:  # a cycle in the hierarchy
                    continue
                seen.add(location.id)
                ordered.append((depth, location))
                walk(location.id, depth + 1)

        walk(None, 0)
        # Anything stranded in a cycle still deserves to be listed.
        ordered.extend((0, l) for l in self.world.locations if l.id not in seen)
        return ordered

    # --- episode queue -----------------------------------------------------

    def add_episode(self, author_storyline: str, title: str = "") -> Episode:
        episode = Episode(
            episode_number=self.next_episode_number(),
            title=title,
            author_storyline=author_storyline,
        )
        self.episodes.append(episode)
        return episode

    def remove_episode(self, episode_number: int) -> None:
        self.episodes = [e for e in self.episodes if e.episode_number != episode_number]

    def move_episode(self, episode_number: int, offset: int) -> None:
        """Move a queued episode up or down, renumbering the queue to match.

        Numbers follow position rather than identity — episode 4 is whatever is
        fourth — so reordering the queue reorders the story.
        """
        index = next(
            (i for i, e in enumerate(self.episodes) if e.episode_number == episode_number), None
        )
        if index is None:
            raise KeyError(f"No episode numbered {episode_number}")
        target = index + offset
        if not 0 <= target < len(self.episodes):
            return
        self.episodes[index], self.episodes[target] = self.episodes[target], self.episodes[index]
        self.renumber_episodes()

    def renumber_episodes(self) -> None:
        for position, episode in enumerate(self.episodes, start=1):
            if episode.episode_number != position:
                self.episodes[position - 1] = episode.model_copy(
                    update={"episode_number": position}
                )

    def update_episode(self, episode: Episode) -> None:
        for index, existing in enumerate(self.episodes):
            if existing.episode_number == episode.episode_number:
                self.episodes[index] = episode
                return
        self.episodes.append(episode)

    def add_episodes_from_text(self, text: str, separator: str = "---") -> list[Episode]:
        """Batch-add outlines from a pasted or uploaded file, one per section."""
        added = []
        for block in text.split(separator):
            storyline = block.strip()
            if storyline:
                added.append(self.add_episode(storyline))
        return added


class ProjectStore:
    """Loads and saves a `Project`, and packages it up for export."""

    def __init__(self, data_dir: Path | str | None = None):
        self.data_dir = Path(data_dir) if data_dir is not None else config.DATA_DIR

    @property
    def path(self) -> Path:
        return self.data_dir / PROJECT_FILENAME

    @property
    def state_dir(self) -> Path:
        return self.data_dir / STATE_DIRNAME

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / CHROMA_DIRNAME

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> Project:
        """Load the project, or hand back an empty one if there is none yet."""
        if not self.exists():
            return Project()
        try:
            return Project.model_validate_json(self.path.read_text(encoding="utf-8"))
        except ValueError:
            logger.exception("Could not read %s; starting from an empty project", self.path)
            return Project()

    def save(self, project: Project) -> None:
        write_text_atomic(self.path, project.model_dump_json(indent=2) + "\n")

    def reset(self, keep_memory: bool = False) -> Project:
        """Start a new project, optionally wiping what the story remembered."""
        project = Project()
        self.save(project)
        if not keep_memory:
            shutil.rmtree(self.state_dir, ignore_errors=True)
            shutil.rmtree(self.chroma_dir, ignore_errors=True)
        return project

    # --- import / export ---------------------------------------------------

    def export_zip(self, project: Project, include_memory: bool = True) -> bytes:
        """The whole project as a ZIP: the authored data plus what it remembers."""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(PROJECT_FILENAME, project.model_dump_json(indent=2))
            if include_memory:
                for directory in (self.state_dir, self.chroma_dir):
                    if not directory.is_dir():
                        continue
                    for file in sorted(directory.rglob("*")):
                        if file.is_file():
                            archive.write(file, str(file.relative_to(self.data_dir)))
        return buffer.getvalue()

    def import_zip(self, data: bytes, restore_memory: bool = True) -> Project:
        """Restore a project from an exported ZIP and make it the current one."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            if PROJECT_FILENAME not in names:
                raise ValueError(f"Archive does not contain {PROJECT_FILENAME}")
            project = Project.model_validate_json(archive.read(PROJECT_FILENAME).decode("utf-8"))

            if restore_memory:
                for name in names:
                    if name == PROJECT_FILENAME or name.endswith("/"):
                        continue
                    target = _safe_target(self.data_dir, name)
                    if target is None:
                        logger.warning("Skipping archive entry outside the project: %s", name)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))

        self.save(project)
        return project


def _safe_target(root: Path, name: str) -> Path | None:
    """Resolve an archive entry inside `root`, refusing anything that escapes it."""
    target = (root / name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def project_from_sample(raw: dict) -> Project:
    """Build a project from the `harry_potter_sample.json` layout."""
    return Project(
        name=raw.get("world", {}).get("title", "Imported Story"),
        world=WorldLore.model_validate(raw["world"]),
        characters=[CharacterProfile.model_validate(c) for c in raw.get("characters", [])],
        episodes=[Episode.model_validate(e) for e in raw.get("episodes", [])],
    )


def load_sample_project(path: Path | None = None) -> Project:
    """The bundled Harry Potter sample, as a ready-to-run project."""
    path = path or (config.EXAMPLES_DIR / "harry_potter_sample.json")
    return project_from_sample(json.loads(path.read_text(encoding="utf-8")))
