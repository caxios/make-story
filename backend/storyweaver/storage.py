"""Durable writes for the JSON state files.

A generation run is long and expensive, and it ends by rewriting several state
files. A crash or a full disk partway through a plain `write_text` leaves a
truncated file — which, for `story_memory.json`, means losing the whole story's
memory. Every state write goes through here instead.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TEMP_SUFFIX = ".tmp"
BACKUP_DIRNAME = "backups"

# Only what a filesystem cannot take: path separators, the characters Windows
# reserves, and control codes. Everything else — Korean above all — is kept, so
# that the state directory stays readable by the person whose story it is.
_UNSAFE_ID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(prefix: str, raw_id: str, suffix: str = ".json") -> str:
    """A filename that is safe to write and belongs to exactly one subject.

    Ids here are author-supplied — character ids, location ids, rule ids — so
    anything the filesystem cannot take is dropped. That stripping is not
    enough on its own. When it was `[^A-Za-z0-9._-]` a Korean cast collapsed
    onto one filename: 한병호, 나도현 and 임소희 all became `character____.json`
    and overwrote each other's memory on every episode any of them appeared in.

    So the readable part only makes the file recognisable, and a digest of the
    whole id is what guarantees it belongs to one subject — two ids differing
    only in a stripped character still get their own file. The id is normalised
    first so the same name typed on a Mac and on Windows lands on one file.

    `prefix` does more than label: it is why an id like `..` or a reserved
    Windows device name can never come out of here.
    """
    normalized = unicodedata.normalize("NFC", raw_id)
    # Trailing dots and spaces are legal in an id and illegal in a Windows
    # filename, so they go too.
    readable = _UNSAFE_ID.sub("", normalized).strip().strip(".") or "unnamed"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{readable}_{digest}{suffix}"


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
