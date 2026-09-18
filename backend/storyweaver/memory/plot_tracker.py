"""Plot thread (떡밥) lifecycle management, persisted as one JSON file.

A serial lives or dies on its dangling threads. This tracker knows which ones
are open, which have gone quiet, and which have been paid off — so the Director
can weave a dormant thread back in before the reader decides it was dropped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from storyweaver.storage import write_text_atomic

logger = logging.getLogger(__name__)

ThreadStatus = Literal["open", "progressing", "resolved"]
FILENAME = "plot_threads.json"


class PlotThread(BaseModel):
    """One unresolved (or since-resolved) question the story has raised."""

    id: str                             # e.g. "philosophers_stone_mystery"
    name: str                           # human-readable name
    description: str                    # what the thread is about
    status: ThreadStatus = "open"
    opened_in_episode: int
    last_referenced_episode: int = 0
    resolved_in_episode: int | None = None
    linked_characters: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)  # chronological event summaries
    resolution: str | None = None

    def model_post_init(self, _context) -> None:
        # A thread opened in episode 7 was, by definition, referenced in 7.
        if not self.last_referenced_episode:
            self.last_referenced_episode = self.opened_in_episode

    def episodes_since_reference(self, current_episode: int) -> int:
        return max(0, current_episode - self.last_referenced_episode)

    def summary_line(self) -> str:
        """One line for a prompt: what it is and how long it has been waiting."""
        text = f"{self.name} [{self.status}, opened in episode {self.opened_in_episode}"
        if self.last_referenced_episode != self.opened_in_episode:
            text += f", last touched in {self.last_referenced_episode}"
        text += f"]: {self.description}"
        if self.events:
            text += f" Most recently: {self.events[-1]}"
        return text


class PlotThreadTracker:
    """A JSON-backed collection of `PlotThread`s.

    Every mutation writes through to disk immediately — an episode run is long
    and expensive, and losing the thread state to a crash at the end of it is
    not a trade worth making for a few saved writes.
    """

    def __init__(self, data_dir: Path | str):
        self.path = Path(data_dir) / FILENAME
        self._threads: dict[str, PlotThread] = {}
        self.load()

    # --- persistence -------------------------------------------------------

    def load(self) -> None:
        if not self.path.is_file():
            self._threads = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._threads = {t["id"]: PlotThread.model_validate(t) for t in raw.get("threads", [])}

    def save(self) -> None:
        payload = {"threads": [t.model_dump(mode="json") for t in self._threads.values()]}
        write_text_atomic(self.path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # --- lifecycle ---------------------------------------------------------

    def open(self, thread: PlotThread) -> PlotThread:
        """Register a new thread. Re-opening an existing id is a no-op with a warning."""
        if thread.id in self._threads:
            logger.warning("Plot thread %r already exists; keeping the original", thread.id)
            return self._threads[thread.id]
        self._threads[thread.id] = thread
        self.save()
        return thread

    def progress(self, thread_id: str, event: str, episode: int) -> PlotThread:
        """Record that something happened on this thread in `episode`."""
        thread = self._require(thread_id)
        if thread.status == "resolved":
            logger.warning("Plot thread %r is resolved; reopening it as progressing", thread_id)
            thread.resolved_in_episode = None
            thread.resolution = None
        thread.status = "progressing"
        thread.events.append(f"Episode {episode}: {event}")
        thread.last_referenced_episode = max(thread.last_referenced_episode, episode)
        self.save()
        return thread

    def resolve(self, thread_id: str, resolution: str, episode: int) -> PlotThread:
        """Pay the thread off."""
        thread = self._require(thread_id)
        thread.status = "resolved"
        thread.resolution = resolution
        thread.resolved_in_episode = episode
        thread.events.append(f"Episode {episode}: resolved — {resolution}")
        thread.last_referenced_episode = max(thread.last_referenced_episode, episode)
        self.save()
        return thread

    # --- queries -----------------------------------------------------------

    def get(self, thread_id: str) -> PlotThread | None:
        return self._threads.get(thread_id)

    def all(self) -> list[PlotThread]:
        return sorted(self._threads.values(), key=lambda t: (t.opened_in_episode, t.id))

    def get_active(self) -> list[PlotThread]:
        """Every thread still awaiting a payoff."""
        return [t for t in self.all() if t.status != "resolved"]

    def get_stale(
        self, episodes_since_last_ref: int = 5, current_episode: int | None = None
    ) -> list[PlotThread]:
        """Active threads nobody has touched lately, oldest silence first.

        `current_episode` defaults to the latest episode any thread has seen, so
        the tracker can answer this without being told where the story is.
        """
        if current_episode is None:
            current_episode = max(
                (t.last_referenced_episode for t in self._threads.values()), default=0
            )
        stale = [
            t
            for t in self.get_active()
            if t.episodes_since_reference(current_episode) >= episodes_since_last_ref
        ]
        return sorted(stale, key=lambda t: t.last_referenced_episode)

    def _require(self, thread_id: str) -> PlotThread:
        thread = self._threads.get(thread_id)
        if thread is None:
            raise KeyError(f"No plot thread with id {thread_id!r}")
        return thread
