"""Durable writes for the JSON state files.

A generation run is long and expensive, and it ends by rewriting several state
files. A crash or a full disk partway through a plain `write_text` leaves a
truncated file — which, for `story_memory.json`, means losing the whole story's
memory. Every state write goes through here instead.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TEMP_SUFFIX = ".tmp"
BACKUP_DIRNAME = "backups"


def write_text_atomic(path: Path | str, text: str, encoding: str = "utf-8") -> Path:
    """Write a file so that readers only ever see the old or the new version.

    The temp file lives beside the target rather than in the system temp
    directory, because `os.replace` is only atomic within one filesystem.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + TEMP_SUFFIX)

    try:
        with open(temp, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    return path


def backup_directory(source: Path | str, destination: Path | str | None = None) -> Path | None:
    """Snapshot a directory into a timestamped folder alongside it.

    Returns the snapshot path, or None if there was nothing to copy.
    """
    source = Path(source)
    if not source.is_dir() or not any(source.iterdir()):
        return None

    root = Path(destination) if destination is not None else source.parent / BACKUP_DIRNAME
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = root / f"{source.name}-{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    logger.info("Backed up %s to %s", source, target)
    return target


def prune_backups(root: Path | str, keep: int = 5) -> list[Path]:
    """Delete all but the newest `keep` snapshots. Returns what was removed."""
    root = Path(root)
    if not root.is_dir():
        return []
    snapshots = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    removed = []
    for snapshot in snapshots[keep:]:
        shutil.rmtree(snapshot, ignore_errors=True)
        removed.append(snapshot)
    return removed
