"""Making ids out of what an author or a model wrote.

Ids are matched exactly everywhere downstream — scenes name characters by id,
relationships point at them, the chronicle files itself by them, and the Lore
Checker cites rules by them. What matters is that an id is stable and has no
spaces, not that it is ASCII: Korean is kept rather than transliterated,
because an id the author cannot read is an id they cannot debug.

This lives at the top level rather than in `api/` because the API is not the
only thing that needs it — committing a concept mints ids for a whole cast, and
reaching into a route module for that would drag the entire FastAPI app into
the import graph.
"""

from __future__ import annotations

import re

# Uniqueness is tried with a numeric suffix this many times before falling back
# on the count, which is only reachable with a hundred colliding names.
MAX_SUFFIX = 100


def slugify(value: str) -> str:
    """A usable id, keeping Korean as it is rather than transliterating it."""
    slug = re.sub(r"[\s_]+", "-", value.strip().lower())
    slug = re.sub(r"[^\w가-힣-]", "", slug, flags=re.UNICODE)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def unique_id(proposed: str, fallback: str, taken: set[str]) -> str:
    """An id that cannot collide with one that already means someone.

    This matters more than it looks: saving a character upserts by id, so an id
    that happened to be reused would overwrite whoever already had it.
    """
    base = slugify(proposed) or slugify(fallback) or "item"
    if base not in taken:
        return base
    for suffix in range(2, MAX_SUFFIX):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base}-{len(taken) + 1}"


__all__ = ["MAX_SUFFIX", "slugify", "unique_id"]
