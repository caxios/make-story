"""What the story has done to each thing in it, for the stages that plan.

Two kinds of change reach a planner, and they are handled oppositely.

- **What the author edited** — a character sheet, a wiki section, a faction's
  description, the concept. Only the latest version matters. Nobody planning
  episode 120 needs to know the heroine was once called something else, so
  none of that is shown; the fold and the author's own sections give the
  current text and nothing more.
- **What happened in the story** — a betrayal in episode 30, a relationship
  that turned in 45, a faction that fell in 50. That history *is* the story,
  and a 떡밥 cannot be designed or paid off by a planner that has not read it.

So each element — every character, faction, place, rule, and the world — keeps
its own window: the last `HISTORY_WINDOW` episodes **in which it appeared**,
in full. A character offstage for a hundred episodes comes back with their own
last forty, not with nothing. Everything older is kept as a digest, written by
the model once and cached, so a long serial costs one short call per element
as its window slides, not a re-read of three hundred chapters per plan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from storyweaver import telemetry
from storyweaver.agents import context as ctx
from storyweaver.agents.prompts import render_prompt
from storyweaver.llm import MODEL_MAX_OUTPUT_TOKENS, get_llm
from storyweaver.storage import write_text_atomic
from storyweaver.wiki.fold import current_value
from storyweaver.wiki.sections import relationship_target, section_for

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore
    from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

# Episodes of an element's own history given in full. Enough for a planner to
# see what is set up and not yet paid off; older than this becomes a digest.
HISTORY_WINDOW = 40
DIGEST_FILENAME = "history_digests.json"
# When the digest call fails, what is kept of the aged-out history instead —
# the latest part, since that is nearest the window.
FALLBACK_CHARS = 1500

TYPE_LABELS = {
    "character": "인물",
    "faction": "세력",
    "location": "장소",
    "rule": "규칙",
    "world": "세계",
}

HEADING = "## 작중 기록 — 요소마다 작품 속에서 일어난 일"
PREAMBLE = (
    "각 요소가 등장한 최근 {window}개 회차의 기록은 그대로, 그보다 오래된 기록은 요약으로 "
    "적었습니다. 설정(인물 시트, 위키, 세력 설명)은 위 설정란과 여기 '설정' 줄에 최신 "
    "내용만 있습니다. 떡밥을 심고 거둘 때, 관계를 움직일 때 이 기록을 근거로 삼으세요."
)


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


@dataclass
class ElementRecord:
    subject_type: str
    subject_id: str
    title: str
    # The author's own text beyond the typed fields: the page summary and any
    # sections they added. Latest version only.
    setting: list[str] = field(default_factory=list)
    # (episode, lines), oldest first.
    recent: list[tuple[int, list[str]]] = field(default_factory=list)
    older: list[tuple[int, list[str]]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"

    def is_empty(self) -> bool:
        return not (self.setting or self.recent or self.older)


def _elements(store: ChronicleStore, project: Project) -> list[tuple[str, str, str]]:
    """Every element with a page, as (type, id, title), cast first."""
    cast = sorted(project.characters, key=lambda c: (ctx._role_rank(c), c.name))
    found: list[tuple[str, str, str]] = [("character", c.id, c.name) for c in cast]
    factions = [sid for stype, sid in store.known_subjects() if stype == "faction"]
    found += [("faction", sid, "") for sid in factions]
    found += [("location", place.id, place.name) for place in project.world.locations]
    found += [("rule", rule.id, rule.statement) for rule in project.world.rules]
    found.append(("world", "world", project.world.title or "세계"))
    return found


def _section_title(spec, key: str, names: dict[str, str]) -> str:
    target = relationship_target(key)
    if target is not None:
        return f"관계 → {names.get(target, target)}"
    return spec.title if spec is not None else key


def _line(entry, title: str, is_log: bool) -> str:
    text = entry.value.strip() if is_log else f"{title}: {entry.value.strip()}"
    if entry.kind == "removed":
        text += " (사라짐/폐지)"
    reason = entry.reason.strip()
    # A relationship's reason is "N화에서 관계가 달라짐" — the episode says that.
    if reason and relationship_target(entry.section_key) is None:
        text += f" — {reason}"
    return text


def gather(
    store: ChronicleStore,
    project: Project,
    before: int,
    *,
    window: int = HISTORY_WINDOW,
) -> list[ElementRecord]:
    """Each element's setting extras and its story history before `before`."""
    names = {c.id: c.name for c in project.characters}
    records = []
    for subject_type, subject_id, title in _elements(store, project):
        page = store.get_wiki_subject(subject_type, subject_id)  # type: ignore[arg-type]
        record = ElementRecord(subject_type, subject_id, page.title or title or subject_id)

        if page.summary.strip():
            record.setting.append(f"개요: {page.summary.strip()}")
        if subject_type == "faction":
            described = current_value(store, "faction", subject_id, "description")
            if described and described.strip():
                record.setting.append(f"설명: {described.strip()}")
        for spec in sorted(page.free_sections, key=lambda s: (s.order, s.key)):
            # The world's own sections are already part of the world every
            # planner is shown (`fold_world` puts them in `additional_lore`).
            if spec.kind == "log" or subject_type == "world":
                continue
            value = current_value(store, subject_type, subject_id, spec.key)  # type: ignore[arg-type]
            if value and value.strip():
                record.setting.append(f"{spec.title}: {value.strip()}")

        by_episode: dict[int, list[str]] = {}
        for entry in store.subject(subject_type, subject_id):  # type: ignore[arg-type]
            if not entry.is_live() or not entry.value.strip():
                continue
            spec = section_for(subject_type, entry.section_key) or page.section(entry.section_key)  # type: ignore[arg-type]
            is_log = spec is not None and spec.kind == "log"
            label = _section_title(spec, entry.section_key, names)
            if entry.episode_number is None:
                # Author entries in a log section are notes the author keeps,
                # not an old version of anything: they belong with the setting.
                # Author edits to a stateful section are already the current
                # value the setting shows — their older versions are not shown.
                if is_log:
                    record.setting.append(f"{label}(작가 기록): {entry.value.strip()}")
                continue
            if entry.episode_number >= before:
                continue
            by_episode.setdefault(entry.episode_number, []).append(
                _line(entry, label, is_log)
            )

        episodes = sorted(by_episode)
        cut = max(0, len(episodes) - window)
        record.older = [(n, by_episode[n]) for n in episodes[:cut]]
        record.recent = [(n, by_episode[n]) for n in episodes[cut:]]
        if not record.is_empty():
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Digests of what aged out of the window
# ---------------------------------------------------------------------------


class ElementDigest(BaseModel):
    key: str = Field(description="요청에 적힌 key 그대로")
    summary: str = Field(description="이 요소의 지난 기록을 시간 순으로 요약한 문단")


class DigestBatch(BaseModel):
    digests: list[ElementDigest]


@dataclass
class DigestJob:
    key: str
    title: str
    existing: str
    new: list[tuple[int, list[str]]]


def _fingerprint(history: Sequence[tuple[int, list[str]]]) -> str:
    return hashlib.sha1(
        json.dumps(list(history), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _render_history(history: Sequence[tuple[int, list[str]]]) -> str:
    return "\n".join(f"- {n}화: " + " / ".join(lines) for n, lines in history)


class DigestCache:
    """Digests on disk, next to the chronicle they were made from."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _plan_job(record: ElementRecord, cached: dict | None) -> tuple[str | None, DigestJob | None]:
    """The cached digest if it still fits, or the job that brings it up to date."""
    older = record.older
    if cached and cached.get("fingerprint") == _fingerprint(older):
        return cached.get("text", ""), None
    if cached:
        covered = cached.get("episodes", [])
        head = older[: len(covered)]
        if [n for n, _ in head] == covered and cached.get("fingerprint") == _fingerprint(head):
            return None, DigestJob(record.key, record.title, cached.get("text", ""), older[len(covered):])
    return None, DigestJob(record.key, record.title, "", older)


def digest(jobs: Sequence[DigestJob], llm=None) -> dict[str, str]:
    """One call that brings every job's digest up to date."""
    blocks = []
    for job in jobs:
        parts = [f"### key: {job.key} — {job.title}"]
        if job.existing.strip():
            parts.append(f"지금까지의 요약:\n{job.existing.strip()}")
        parts.append(f"새로 요약에 넣을 기록:\n{_render_history(job.new)}")
        blocks.append("\n".join(parts))
    prompt = render_prompt("history_digest", elements="\n\n".join(blocks))
    model = telemetry.meter(
        llm or get_llm(stage="summarizer", max_output_tokens=MODEL_MAX_OUTPUT_TOKENS),
        "summarizer",
    )
    result: DigestBatch = model.with_structured_output(DigestBatch).invoke(prompt)
    return {d.key: d.summary.strip() for d in result.digests if d.summary.strip()}


def _fallback(job: DigestJob) -> str:
    text = "\n".join(filter(None, [job.existing.strip(), _render_history(job.new)]))
    return text if len(text) <= FALLBACK_CHARS else "…" + text[-FALLBACK_CHARS:]


def fill_digests(
    store: ChronicleStore,
    records: Sequence[ElementRecord],
    *,
    digester: Callable[[Sequence[DigestJob]], dict[str, str]] | None = None,
) -> dict[str, str]:
    """The digest of each record's aged-out history, calling the model only for
    those whose history moved since the last time."""
    cache = DigestCache(Path(store.data_dir) / DIGEST_FILENAME)
    stored = cache.load()
    digests: dict[str, str] = {}
    jobs: list[DigestJob] = []
    for record in records:
        if not record.older:
            continue
        text, job = _plan_job(record, stored.get(record.key))
        if job is None:
            digests[record.key] = text or ""
        elif not job.new:
            digests[record.key] = job.existing
        else:
            jobs.append(job)
    if not jobs:
        return digests

    try:
        made = (digester or digest)(jobs)
    except Exception:  # noqa: BLE001 — a plan is still worth drawing without it
        logger.exception("Digesting the older history of %d elements failed", len(jobs))
        made = {}

    by_key = {r.key: r for r in records}
    for job in jobs:
        text = made.get(job.key)
        if text:
            record = by_key[job.key]
            stored[job.key] = {
                "episodes": [n for n, _ in record.older],
                "fingerprint": _fingerprint(record.older),
                "text": text,
            }
            digests[job.key] = text
        else:
            digests[job.key] = _fallback(job)
    cache.save(stored)
    return digests


# ---------------------------------------------------------------------------
# The block a planner reads
# ---------------------------------------------------------------------------


def render(records: Sequence[ElementRecord], digests: dict[str, str], window: int) -> str:
    if not records:
        return ""
    blocks = [PREAMBLE.format(window=window)]
    for record in records:
        lines = [f"### {record.title} ({TYPE_LABELS.get(record.subject_type, record.subject_type)})"]
        lines += [f"설정 — {line}" for line in record.setting]
        if record.older:
            first, last = record.older[0][0], record.older[-1][0]
            lines.append(
                f"그 이전 기록 요약 ({first}~{last}화 중 {len(record.older)}개 회차):\n"
                f"{digests.get(record.key, '').strip()}"
            )
        if record.recent:
            lines.append(f"최근 등장 {len(record.recent)}개 회차:")
            lines += [f"- {n}화: " + " / ".join(entries) for n, entries in record.recent]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def story_record(
    store: ChronicleStore | None,
    project: Project,
    before: int,
    *,
    window: int = HISTORY_WINDOW,
    digester: Callable[[Sequence[DigestJob]], dict[str, str]] | None = None,
) -> str:
    """Every element's history before episode `before`, for a planning prompt.

    Empty when nothing has anything to say — a project whose chapters are not
    written yet and whose pages the author has not added to.
    """
    if store is None:
        return ""
    records = gather(store, project, before, window=window)
    digests = fill_digests(store, records, digester=digester)
    return render(records, digests, window)


def with_heading(record: str) -> str:
    """The record as a section of its own, for a prompt that has no slot for it."""
    return f"{HEADING}\n\n{record}" if record.strip() else ""


__all__ = [
    "HISTORY_WINDOW",
    "DigestJob",
    "ElementRecord",
    "digest",
    "fill_digests",
    "gather",
    "render",
    "story_record",
]
