"""Where a concept session lives between visits.

Working out what a novel is takes more than one sitting. The session is
therefore on disk from the first proposal, not held in a browser tab — closing
the tab must not cost the author the concept they have been refining for an
hour.

It sits beside the other state rather than inside `MemoryManager`, because it
is work in progress rather than something the story remembers. Once it is
committed it stays: it is the record of how the work began, and the wiki's
기획 기록 section points back at it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from storyweaver.models.concept import ConceptSession
from storyweaver.storage import write_text_atomic

logger = logging.getLogger(__name__)

SESSION_FILENAME = "concept_session.json"


class ConceptStore:
    """One concept session per project."""

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)

    @property
    def path(self) -> Path:
        return self.data_dir / SESSION_FILENAME

    def load(self) -> ConceptSession | None:
        """The session in progress, or None if there has never been one."""
        if not self.path.is_file():
            return None
        try:
            return ConceptSession.model_validate_json(self.path.read_text(encoding="utf-8"))
        except ValueError:
            # A session is worth much less than the project, and an unreadable
            # one must not stop the app from starting.
            logger.exception("Could not read %s; treating it as absent", self.path)
            return None

    def save(self, session: ConceptSession) -> ConceptSession:
        session.touch()
        write_text_atomic(self.path, session.model_dump_json(indent=2) + "\n")
        return session

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def exists(self) -> bool:
        return self.path.is_file()


__all__ = ["ConceptStore", "SESSION_FILENAME"]
