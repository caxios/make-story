"""Shared dependencies: the store, the project on disk, and the memory layer.

The project is the file on disk, not an object held in RAM: every request
reloads it and every mutation writes it straight back. That keeps the API and a
Streamlit session pointed at the same `data/` directory honest with each other,
and it means a restart loses nothing.
"""

from __future__ import annotations

import logging
import threading

from fastapi import HTTPException

from storyweaver.agents.checkpoint import CheckpointStore
from storyweaver.memory import MemoryManager
from storyweaver.models import CharacterProfile, Episode
from storyweaver.ui.project import Project, ProjectStore

logger = logging.getLogger(__name__)

# One writer at a time. Saves are atomic already (`write_text_atomic`), but a
# read-modify-write across two requests still needs serializing.
_write_lock = threading.RLock()

_store: ProjectStore | None = None
_memory: MemoryManager | None = None
_memory_error: str = ""
_memory_tried = False


def set_store(store: ProjectStore | None) -> None:
    """Point the API at a different data directory (used by the tests)."""
    global _store, _memory, _memory_error, _memory_tried
    _store = store
    _memory = None
    _memory_error = ""
    _memory_tried = False


def set_memory(memory: MemoryManager | None, error: str = "") -> None:
    """Inject a memory layer instead of building one (used by the tests)."""
    global _memory, _memory_error, _memory_tried
    _memory = memory
    _memory_error = error
    _memory_tried = True


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store


def get_project() -> Project:
    """The project as it currently sits on disk."""
    return get_store().load()


def save_project(project: Project) -> Project:
    with _write_lock:
        get_store().save(project)
    return project


def write_lock() -> threading.RLock:
    return _write_lock


def get_checkpoints() -> CheckpointStore:
    return CheckpointStore(get_store().state_dir)


def get_memory() -> MemoryManager | None:
    """The memory layer, or None if it could not be started.

    Building one loads ChromaDB, which downloads an embedding model the first
    time — slow, and impossible offline. Every other endpoint works without it,
    so a failure is remembered and reported rather than raised.
    """
    global _memory, _memory_error, _memory_tried
    if not _memory_tried:
        _memory_tried = True
        try:
            _memory = MemoryManager()
            _memory_error = ""
        except Exception as error:  # noqa: BLE001 — surfaced through the API
            logger.exception("Could not start the memory layer")
            _memory = None
            _memory_error = str(error)
    return _memory


def memory_error() -> str:
    return _memory_error


def require_memory() -> MemoryManager:
    memory = get_memory()
    if memory is None:
        raise HTTPException(
            status_code=503,
            detail=f"The memory layer is unavailable: {_memory_error or 'not started'}",
        )
    return memory


# --- lookups that 404 rather than returning None ---------------------------


def require_episode(project: Project, episode_number: int) -> Episode:
    episode = project.get_episode(episode_number)
    if episode is None:
        raise HTTPException(status_code=404, detail=f"No episode numbered {episode_number}")
    return episode


def require_character(project: Project, character_id: str) -> CharacterProfile:
    character = project.get_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail=f"No character with id {character_id!r}")
    return character
