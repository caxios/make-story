"""Append-only storage for the chronicle.

One file per subject, holding every entry ever written about it. Nothing here
rewrites an entry's place in history: `retract` marks, `edit` changes the text
of one entry, and only `drop_episode` deletes — because a regenerated episode's
records describe prose that no longer exists.

Ordering is by `sequence`, a store-wide counter handed out on append. It is not
by episode number, because deleting or moving an episode renumbers the whole
queue, and it is not by timestamp, because an author correcting episode 3 after
episode 7 exists means that correction to land where they put it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from uuid import uuid4

from storyweaver.models.chronicle import ChronicleEntry, SubjectType, WikiSubject
from storyweaver.storage import safe_filename, write_text_atomic
from storyweaver.wiki.sections import section_for

logger = logging.getLogger(__name__)

CHRONICLE_DIRNAME = "chronicle"
WIKI_DIRNAME = "wiki"
SEQUENCE_FILENAME = "_sequence.json"


def new_entry_id() -> str:
    return uuid4().hex


class ChronicleStore:
    """Every entry about every subject, on disk.

    Files are laid out one per subject under `state/chronicle/<type>/`. A
    subject's whole history is small — a few hundred lines after fifty
    episodes — and reading one subject is by far the commonest access, so a
    file per subject beats both one big file and a file per section.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / CHRONICLE_DIRNAME
        self.wiki_root = self.data_dir / WIKI_DIRNAME

    # --- paths -------------------------------------------------------------

    def subject_path(self, subject_type: SubjectType, subject_id: str) -> Path:
        """One file per subject, named so two subjects can never share it.

        `safe_filename` rather than a hand-rolled slug: the scheme it replaced
        turned every three-syllable Korean name into the same filename, and
        five characters overwrote each other's memory for six episodes before
        anyone noticed. That failure is silent, and it destroys exactly the
        data this store exists to keep.
        """
        return self.root / subject_type / safe_filename("", subject_id)

    def wiki_path(self, subject_type: SubjectType, subject_id: str) -> Path:
        return self.wiki_root / subject_type / safe_filename("", subject_id)

    @property
    def sequence_path(self) -> Path:
        return self.root / SEQUENCE_FILENAME

    # --- the sequence counter ----------------------------------------------

    def _next_sequence(self, count: int = 1) -> int:
        """Reserve `count` sequence numbers and return the first.

        Callers hold `deps.write_lock()`; this is not safe against two
        processes, which matches the rest of the state directory.
        """
        current = 0
        if self.sequence_path.is_file():
            try:
                current = int(json.loads(self.sequence_path.read_text(encoding="utf-8"))["next"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                logger.exception("Unreadable chronicle sequence; continuing from the entries")
                current = self._highest_sequence()
        write_text_atomic(
            self.sequence_path, json.dumps({"next": current + count}, indent=2) + "\n"
        )
        return current

    def _highest_sequence(self) -> int:
        """Recover the counter from the entries themselves."""
        highest = 0
        for path in self.root.rglob("*.json"):
            if path.name == SEQUENCE_FILENAME:
                continue
            for entry in self._read(path):
                highest = max(highest, entry.sequence + 1)
        return highest

    # --- reading -----------------------------------------------------------

    def _read(self, path: Path) -> list[ChronicleEntry]:
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("Could not read %s; treating it as empty", path)
            return []
        return [ChronicleEntry.model_validate(item) for item in raw.get("entries", [])]

    def _write(self, path: Path, entries: Sequence[ChronicleEntry]) -> None:
        ordered = sorted(entries, key=lambda e: e.sequence)
        payload = {"entries": [json.loads(e.model_dump_json()) for e in ordered]}
        write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def subject(self, subject_type: SubjectType, subject_id: str) -> list[ChronicleEntry]:
        """Everything ever written about one subject, oldest first."""
        return self._read(self.subject_path(subject_type, subject_id))

    def chain(
        self,
        subject_type: SubjectType,
        subject_id: str,
        section_key: str,
        include_all: bool = False,
    ) -> list[ChronicleEntry]:
        """The history of one section, oldest first.

        By default only the entries that count: an entry still awaiting the
        author's review, or one they took back, is not part of what this
        section currently says.
        """
        return [
            entry
            for entry in self.subject(subject_type, subject_id)
            if entry.section_key == section_key
            and (include_all or entry.is_live())
        ]

    def section_keys(self, subject_type: SubjectType, subject_id: str) -> list[str]:
        """Every section this subject has a chain for, in first-written order."""
        seen: list[str] = []
        for entry in self.subject(subject_type, subject_id):
            if entry.section_key not in seen:
                seen.append(entry.section_key)
        return seen

    def known_subjects(self) -> list[tuple[SubjectType, str]]:
        """Every subject with a chronicle, as `(type, id)`."""
        found: list[tuple[SubjectType, str]] = []
        if not self.root.is_dir():
            return found
        for type_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for path in sorted(type_dir.glob("*.json")):
                entries = self._read(path)
                if entries:
                    found.append((entries[0].subject_type, entries[0].subject_id))
        return found

    def by_episode(self, episode_number: int) -> list[ChronicleEntry]:
        """Everything recorded for one episode, across every subject."""
        entries: list[ChronicleEntry] = []
        if not self.root.is_dir():
            return entries
        for path in self.root.rglob("*.json"):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries.extend(e for e in self._read(path) if e.episode_number == episode_number)
        return sorted(entries, key=lambda e: e.sequence)

    def timeline(self, include_all: bool = False) -> list[ChronicleEntry]:
        """Every entry in the story, in the order it was written."""
        entries: list[ChronicleEntry] = []
        if not self.root.is_dir():
            return entries
        for path in self.root.rglob("*.json"):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries.extend(
                e for e in self._read(path) if include_all or e.is_live()
            )
        return sorted(entries, key=lambda e: e.sequence)

    # --- writing -----------------------------------------------------------

    def append(self, entry: ChronicleEntry) -> ChronicleEntry:
        """Add one entry to its subject's history."""
        return self.append_many([entry])[0]

    def append_many(self, entries: Sequence[ChronicleEntry]) -> list[ChronicleEntry]:
        """Add several entries, numbering them in the order given.

        Grouped by subject so that a whole episode's worth of records costs one
        write per subject rather than one per entry.
        """
        if not entries:
            return []

        start = self._next_sequence(len(entries))
        numbered = [
            entry.model_copy(
                update={
                    "sequence": start + offset,
                    "entry_id": entry.entry_id or new_entry_id(),
                }
            )
            for offset, entry in enumerate(entries)
        ]

        by_subject: dict[tuple[SubjectType, str], list[ChronicleEntry]] = {}
        for entry in numbered:
            by_subject.setdefault((entry.subject_type, entry.subject_id), []).append(entry)

        for (subject_type, subject_id), added in by_subject.items():
            path = self.subject_path(subject_type, subject_id)
            self._write(path, [*self._read(path), *added])

        return numbered

    def record(
        self,
        subject_type: SubjectType,
        subject_id: str,
        section_key: str,
        value: str,
        *,
        source: str = "author",
        kind: str | None = None,
        episode_number: int | None = None,
        reason: str = "",
        previous: str | None = None,
        section_kind: str | None = None,
    ) -> ChronicleEntry:
        """Append an entry, filling in what can be worked out from the chain.

        `previous` and `kind` come from the chain when the caller does not say:
        the first entry in a chain is `initial`, and anything after it that
        carries a value is `changed`.

        A log section — 작중 행적 — is the exception. Its entries do not
        succeed one another, they accumulate, so there is no previous value and
        rendering one would read as "what he did in episode 1 → what he did in
        episode 2". `section_kind` overrides the registry for a section the
        author invented, which the registry has never heard of.
        """
        if section_kind is None:
            spec = section_for(subject_type, section_key)
            section_kind = spec.kind if spec else "stateful"

        if section_kind == "log":
            return self.append(
                ChronicleEntry(
                    entry_id=new_entry_id(),
                    subject_type=subject_type,
                    subject_id=subject_id,
                    section_key=section_key,
                    source=source,  # type: ignore[arg-type]
                    episode_number=episode_number,
                    kind=kind or "added",  # type: ignore[arg-type]
                    value=value,
                    previous="",
                    reason=reason,
                )
            )

        existing = self.chain(subject_type, subject_id, section_key)
        if previous is None:
            previous = existing[-1].value if existing else ""
        if kind is None:
            kind = "changed" if existing else "initial"

        return self.append(
            ChronicleEntry(
                entry_id=new_entry_id(),
                subject_type=subject_type,
                subject_id=subject_id,
                section_key=section_key,
                source=source,  # type: ignore[arg-type]
                episode_number=episode_number,
                kind=kind,  # type: ignore[arg-type]
                value=value,
                previous=previous,
                reason=reason,
            )
        )

    def get(self, entry_id: str) -> ChronicleEntry | None:
        for entry in self.timeline(include_all=True):
            if entry.entry_id == entry_id:
                return entry
        return None

    def edit(self, entry_id: str, **fields: object) -> ChronicleEntry | None:
        """Change an entry's text. Its place in history does not move.

        `sequence`, `entry_id` and `subject` are not editable: an entry that
        could move would make the chain unreadable as a history.
        """
        protected = {"entry_id", "sequence", "subject_type", "subject_id", "section_key"}
        changes = {k: v for k, v in fields.items() if k not in protected}
        return self._replace(entry_id, changes)

    def retract(self, entry_id: str) -> ChronicleEntry | None:
        """Mark an entry as no longer true.

        Marked rather than deleted: a mistaken retraction is then recoverable,
        and the audit trail stays whole. The fold skips it; the wiki shows it
        struck through.
        """
        return self._replace(entry_id, {"superseded": True})

    def restore(self, entry_id: str) -> ChronicleEntry | None:
        return self._replace(entry_id, {"superseded": False})

    # --- the author's review ------------------------------------------------

    def pending(self, episode_number: int | None = None) -> list[ChronicleEntry]:
        """Entries recorded but not yet accepted, oldest first."""
        entries = [e for e in self.timeline(include_all=True) if e.pending]
        if episode_number is not None:
            entries = [e for e in entries if e.episode_number == episode_number]
        return sorted(entries, key=lambda e: e.sequence)

    def accept(self, entry_id: str) -> ChronicleEntry | None:
        """Let an entry count. From here it folds into what the story is told."""
        return self._replace(entry_id, {"pending": False})

    def discard(self, entry_id: str) -> bool:
        """Throw away an entry the author rejected before it ever counted.

        Deleted rather than marked: a proposal the author never accepted is not
        part of the story's history, and leaving it struck through on the page
        would bury the record in things that did not happen.
        """
        for path in sorted(self.root.rglob("*.json")):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries = self._read(path)
            kept = [e for e in entries if not (e.entry_id == entry_id and e.pending)]
            if len(kept) != len(entries):
                self._write(path, kept) if kept else path.unlink(missing_ok=True)
                return True
        return False

    def _replace(self, entry_id: str, changes: dict) -> ChronicleEntry | None:
        if not changes:
            return self.get(entry_id)
        for path in sorted(self.root.rglob("*.json")):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries = self._read(path)
            for index, entry in enumerate(entries):
                if entry.entry_id != entry_id:
                    continue
                updated = entry.model_copy(update=changes)
                entries[index] = updated
                self._write(path, entries)
                return updated
        return None

    # --- episode integrity --------------------------------------------------

    def drop_episode(self, episode_number: int) -> int:
        """Delete every entry recorded for one episode. Returns how many.

        This is the one real deletion in the store, and regeneration is why it
        exists: rewriting episode 3 must not leave its old records behind, or a
        chain ends up holding both "c → b" and "c → d" for the same chapter and
        the fold picks whichever landed last.
        """
        removed = 0
        if not self.root.is_dir():
            return 0
        for path in sorted(self.root.rglob("*.json")):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries = self._read(path)
            kept = [e for e in entries if e.episode_number != episode_number]
            if len(kept) != len(entries):
                removed += len(entries) - len(kept)
                if kept:
                    self._write(path, kept)
                else:
                    path.unlink(missing_ok=True)
        if removed:
            logger.info("Dropped %d chronicle entries for episode %d", removed, episode_number)
        return removed

    def drop_subject(self, subject_type: SubjectType, subject_id: str) -> int:
        """Delete a subject's whole history, and its page. Returns how many.

        For a subject that never made it into a chapter — a character invented
        while concepting and cut before episode one. Keeping their page would
        bury the wiki in people who were never in the story.

        Anyone the story actually used is retired instead, not dropped: that
        they were written out is itself part of the record.
        """
        path = self.subject_path(subject_type, subject_id)
        removed = len(self._read(path))
        path.unlink(missing_ok=True)
        self.wiki_path(subject_type, subject_id).unlink(missing_ok=True)
        if removed:
            logger.info("Dropped %d chronicle entries for %s %r", removed, subject_type, subject_id)
        return removed

    def episode_entries(self, subject_type: SubjectType, subject_id: str) -> int:
        """How much of this subject's history the story itself wrote."""
        return sum(
            1 for entry in self.subject(subject_type, subject_id)
            if entry.source == "episode"
        )

    def renumber(self, mapping: dict[int, int | None]) -> int:
        """Follow the queue's renumbering. Returns how many entries moved.

        `delete_episode` and `move_episode` both renumber the whole queue, so an
        entry's `episode_number` goes stale the moment the author reorders. A
        number mapped to None belonged to a deleted episode and its entries go
        with it.

        `sequence` is untouched: reordering the queue does not reorder history
        that already happened, which is the whole reason the chain is not
        ordered by episode number.
        """
        changed = 0
        if not self.root.is_dir():
            return 0
        for path in sorted(self.root.rglob("*.json")):
            if path.name == SEQUENCE_FILENAME:
                continue
            entries = self._read(path)
            rebuilt: list[ChronicleEntry] = []
            touched = False
            for entry in entries:
                if entry.episode_number not in mapping:
                    rebuilt.append(entry)
                    continue
                target = mapping[entry.episode_number]
                touched = True
                changed += 1
                if target is None:
                    continue  # its episode is gone
                rebuilt.append(entry.model_copy(update={"episode_number": target}))
            if touched:
                if rebuilt:
                    self._write(path, rebuilt)
                else:
                    path.unlink(missing_ok=True)
        return changed

    # --- wiki subjects ------------------------------------------------------

    def get_wiki_subject(self, subject_type: SubjectType, subject_id: str) -> WikiSubject:
        """The page's own data — its summary and any sections the author added."""
        path = self.wiki_path(subject_type, subject_id)
        if not path.is_file():
            return WikiSubject(subject_type=subject_type, subject_id=subject_id)
        try:
            return WikiSubject.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.exception("Could not read %s; starting the page fresh", path)
            return WikiSubject(subject_type=subject_type, subject_id=subject_id)

    def save_wiki_subject(self, subject: WikiSubject) -> WikiSubject:
        write_text_atomic(
            self.wiki_path(subject.subject_type, subject.subject_id),
            subject.model_dump_json(indent=2) + "\n",
        )
        return subject

    def is_empty(self) -> bool:
        return not any(self.root.rglob("*.json")) if self.root.is_dir() else True


def entries_for_episode(
    entries: Iterable[ChronicleEntry], episode_number: int
) -> list[ChronicleEntry]:
    return [e for e in entries if e.episode_number == episode_number]


__all__ = ["ChronicleStore", "entries_for_episode", "new_entry_id"]
