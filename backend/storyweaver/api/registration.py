"""Registering the settings an outline or a plan brings in — the API side.

Called whenever an outline or a plan is saved: by `POST /api/episodes/
extract-settings` after the browser saves outlines, and by the plan routes
themselves. A text already read is not read again, so saving an episode whose
outline did not change costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from storyweaver.agents import settings_extract
from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.storage import write_text_atomic
from storyweaver.wiki import story_brief
from storyweaver.wiki.register import Registered, extend_concept, register_settings

logger = logging.getLogger(__name__)

SEEN_FILENAME = "settings_extracted.json"


def _seen_path() -> Path:
    return Path(deps.get_store().state_dir) / SEEN_FILENAME


def _fingerprint(label: str, text: str) -> str:
    return hashlib.sha1(f"{label}\n{text.strip()}".encode("utf-8")).hexdigest()


def _load_seen() -> set[str]:
    try:
        return set(json.loads(_seen_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_seen(seen: set[str]) -> None:
    path = _seen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(sorted(seen)) + "\n")


def absorb_into_concept(found: settings_extract.ExtractedSettings) -> None:
    """Carry what was registered into 작품기획, so both show the same novel."""
    store = ConceptStore(deps.get_store().state_dir)
    session = store.load()
    if session is None or session.status != "committed" or session.chosen is None:
        return
    baseline = session.committed_concept or session.chosen
    session.chosen = extend_concept(session.chosen, found)
    # The baseline moves with it: the work already has these, so a later edit
    # in 작품기획 must not apply them a second time.
    session.committed_concept = extend_concept(baseline, found)
    store.save(session)


def register_found(
    found: settings_extract.ExtractedSettings,
    source: str,
    *,
    preset_character_ids: dict[str, str] | None = None,
    preset_location_ids: dict[str, str] | None = None,
) -> Registered:
    """Write what was found into the work, the wiki and the concept."""
    if found.is_empty():
        return Registered()
    memory = deps.get_memory()
    with deps.write_lock():
        project = deps.get_project()
        done = register_settings(
            project,
            memory.chronicle if memory is not None else None,
            found,
            source=source,
            preset_character_ids=preset_character_ids,
            preset_location_ids=preset_location_ids,
        )
        deps.save_project(project)
    if done.lines:
        absorb_into_concept(found)
    return done


def register_from(texts: Sequence[tuple[int, str, str]], *, llm=None) -> list[str]:
    """Read `(episode_number, label, text)` for new settings and register them.

    One model call for everything not read before; none when nothing is new.
    Raises when the call fails — the caller decides whether that is fatal.
    """
    seen = _load_seen()
    fresh = [
        (number, label, text) for number, label, text in texts
        if text.strip() and _fingerprint(label, text) not in seen
    ]
    if not fresh:
        return []

    memory = deps.get_memory()
    folded = deps.folded_project()
    found = settings_extract.extract(
        folded,
        fresh,
        brief=story_brief(memory.chronicle) if memory is not None else "",
        llm=llm,
    )
    numbers = sorted({number for number, _, _ in fresh})
    labels = sorted({label for _, label, _ in fresh})
    span = f"{numbers[0]}화" if len(numbers) == 1 else f"{numbers[0]}~{numbers[-1]}화"
    done = register_found(found, f"{span} {'·'.join(labels)}")

    seen.update(_fingerprint(label, text) for _, label, text in fresh)
    _save_seen(seen)
    return done.lines


__all__ = ["absorb_into_concept", "register_found", "register_from"]
