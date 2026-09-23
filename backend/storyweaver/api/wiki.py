"""The wiki: every setting in the story, and the history of how it got there.

A page is assembled rather than stored. Its sections come from the registry
(the ones that stand for a typed field), from the author (the ones they
invented), and from the chronicle itself (one per relationship). Each section
shows what it is now and every step it took to get there.

Editing is appending. There is no update-in-place for a value, because the
point of the whole feature is that what a thing used to be is not lost when it
becomes something else.
"""

from __future__ import annotations

import logging
import re

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from storyweaver.api import deps
from storyweaver.models import CharacterProfile, Location, Rule
from storyweaver.models.chronicle import (
    ChronicleEntry,
    EntryKind,
    SectionKind,
    SectionSpec,
    SubjectType,
)
from storyweaver.ui.project import Project
from storyweaver.wiki import (
    STORY_SUBJECT_ID,
    current_value,
    relationship_section_key,
    relationship_target,
    section_for,
    sections_for,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Free sections are addressed by key in the URL, so a key has to be a path
# segment and not a surprise.
_KEY = re.compile(r"^[\w가-힣-]{1,64}$", re.UNICODE)

# Where per-relationship sections sit on the page: under 인간관계.
RELATIONSHIP_ORDER = 90


# ---------------------------------------------------------------------------
# What a page looks like
# ---------------------------------------------------------------------------


class SectionView(BaseModel):
    key: str
    title: str
    kind: SectionKind
    bound_field: str | None = None
    author_made: bool = False
    order: int = 0
    # Empty for a log section: its entries are the content, not a value.
    current: str = ""
    entries: list[ChronicleEntry] = Field(default_factory=list)


class SubjectPage(BaseModel):
    subject_type: SubjectType
    subject_id: str
    title: str
    summary: str = ""
    sections: list[SectionView] = Field(default_factory=list)
    # Deleted from the cast, but kept because the story used them.
    retired: bool = False
    retired_note: str = ""


class SubjectRow(BaseModel):
    subject_type: SubjectType
    subject_id: str
    title: str
    entry_count: int = 0
    last_episode: int | None = None
    retired: bool = False


class SummaryUpdate(BaseModel):
    summary: str = ""


class NewSection(BaseModel):
    title: Text
    key: str = ""
    kind: SectionKind = "stateful"
    order: int = 500


class SectionUpdate(BaseModel):
    title: str | None = None
    order: int | None = None


class NewEntry(BaseModel):
    value: str = ""
    reason: str = ""
    kind: EntryKind | None = None


class EntryEdit(BaseModel):
    value: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Finding the thing a page is about
# ---------------------------------------------------------------------------


def _subject(project: Project, subject_type: SubjectType, subject_id: str) -> object | None:
    """The typed model a page stands for, or None for a free-standing page."""
    if subject_type == "character":
        return project.get_character(subject_id)
    if subject_type == "world":
        return project.world
    if subject_type == "location":
        return next((l for l in project.world.locations if l.id == subject_id), None)
    if subject_type == "rule":
        return next((r for r in project.world.rules if r.id == subject_id), None)
    return None


def _title(project: Project, subject_type: SubjectType, subject_id: str) -> str:
    # The work's own page is named after the work. `world.title` is what the
    # novel is called; `project.name` is what the author called the folder it
    # lives in, and after a concept is committed the two diverge — the page
    # would otherwise show a stale label while the header showed the real one.
    if subject_type == "story":
        return (
            project.world.title.strip()
            or project.name.strip()
            or "작품 기획"
        )

    base = _subject(project, subject_type, subject_id)
    for attribute in ("name", "title"):
        value = getattr(base, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    if subject_type == "rule" and base is not None:
        return getattr(base, "statement", subject_id)[:40]
    return subject_id


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return "유효함" if value else "폐지됨"
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            name = getattr(item, "name", None)
            parts.append(str(name) if name else str(item))
        return "\n".join(parts)
    return "" if value is None else str(value)


def _chronicle():
    memory = deps.get_memory()
    if memory is None:
        raise HTTPException(
            status_code=503,
            detail="The memory layer is unavailable, so the wiki cannot be read or written.",
        )
    return memory.chronicle


# ---------------------------------------------------------------------------
# Assembling a page
# ---------------------------------------------------------------------------


def _relationship_sections(
    store, project: Project, subject_id: str
) -> list[SectionSpec]:
    """One section per person this character has a relationship with.

    Built from the profile and from the chronicle together: a relationship the
    story invented has a chain but is not yet on the sheet, and one the author
    wrote has a value but no chain, and both belong on the page.
    """
    character = project.get_character(subject_id)
    targets: list[str] = []
    if isinstance(character, CharacterProfile):
        targets.extend(r.target_character_id for r in character.relationships)
    for key in store.section_keys("character", subject_id):
        target = relationship_target(key)
        if target is not None and target not in targets:
            targets.append(target)

    specs = []
    for index, target in enumerate(targets):
        other = project.get_character(target)
        name = other.name if other else target
        specs.append(
            SectionSpec(
                key=relationship_section_key(target),
                title=f"인간관계 · {name}",
                kind="stateful",
                bound_field="relationships",
                order=RELATIONSHIP_ORDER + index + 1,
            )
        )
    return specs


def _base_value(base: object, section: SectionSpec, subject_id: str) -> str:
    """What the section says before the chronicle has anything to add."""
    if section.bound_field is None or base is None:
        return ""
    if section.bound_field == "relationships":
        target = relationship_target(section.key)
        relationship = next(
            (r for r in getattr(base, "relationships", []) if r.target_character_id == target),
            None,
        )
        if relationship is None:
            return ""
        if relationship.description:
            return f"{relationship.type} — {relationship.description}"
        return relationship.type
    return _as_text(getattr(base, section.bound_field, None))


def _build_page(project: Project, subject_type: SubjectType, subject_id: str) -> SubjectPage:
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)
    base = _subject(project, subject_type, subject_id)

    specs = [s for s in sections_for(subject_type) if s.bound_field != "relationships"]
    if subject_type == "character":
        specs = [*specs, *_relationship_sections(store, project, subject_id)]
    specs = [*specs, *saved.free_sections]

    views = []
    for spec in sorted(specs, key=lambda s: (s.order, s.key)):
        entries = store.chain(subject_type, subject_id, spec.key, include_all=True)
        if spec.kind == "log":
            current = ""
        else:
            current = (
                current_value(store, subject_type, subject_id, spec.key)
                or _base_value(base, spec, subject_id)
            )
        views.append(
            SectionView(
                key=spec.key,
                title=spec.title,
                kind=spec.kind,
                bound_field=spec.bound_field,
                author_made=spec.author_made,
                order=spec.order,
                current=current,
                entries=entries,
            )
        )

    return SubjectPage(
        subject_type=subject_type,
        subject_id=subject_id,
        title=saved.title or _title(project, subject_type, subject_id),
        summary=saved.summary,
        sections=views,
        retired=saved.retired,
        retired_note=saved.retired_note,
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@router.get("/subjects", response_model=list[SubjectRow])
def list_subjects(project: Project = Depends(deps.get_project)) -> list[SubjectRow]:
    """Every page the wiki has, whether or not anything has happened to it yet.

    The cast, the world, its places and its rules all get a page from the
    moment the author writes them down — a wiki whose pages only appear once a
    chapter has touched them would be empty exactly when it is most needed.
    """
    store = _chronicle()
    counts: dict[tuple[str, str], list[ChronicleEntry]] = {}
    for entry in store.timeline():
        counts.setdefault((entry.subject_type, entry.subject_id), []).append(entry)

    known: list[tuple[SubjectType, str]] = [
        # The work itself comes first: it is where an author looks to remember
        # what the novel was supposed to be.
        ("story", STORY_SUBJECT_ID),
        ("world", "world"),
        *(("character", c.id) for c in project.characters),
        *(("location", l.id) for l in project.world.locations),
        *(("rule", r.id) for r in project.world.rules),
    ]
    for subject_type, subject_id in store.known_subjects():
        if (subject_type, subject_id) not in known:
            known.append((subject_type, subject_id))

    rows = []
    for subject_type, subject_id in known:
        saved = store.get_wiki_subject(subject_type, subject_id)
        entries = counts.get((subject_type, subject_id), [])
        episodes = [e.episode_number for e in entries if e.episode_number is not None]
        rows.append(
            SubjectRow(
                subject_type=subject_type,
                subject_id=subject_id,
                title=saved.title or _title(project, subject_type, subject_id),
                entry_count=len(entries),
                last_episode=max(episodes) if episodes else None,
                retired=saved.retired,
            )
        )
    return rows


@router.get("/timeline", response_model=list[ChronicleEntry])
def timeline(episode: int | None = None) -> list[ChronicleEntry]:
    """The whole story's history in the order it was written.

    This is the view for auditing a finished arc: every change to everything,
    with the chapter that caused it and the reason it gave.
    """
    store = _chronicle()
    if episode is not None:
        return store.by_episode(episode)
    return store.timeline()


@router.get("/{subject_type}/{subject_id}", response_model=SubjectPage)
def read_subject(
    subject_type: SubjectType,
    subject_id: str,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    return _build_page(project, subject_type, subject_id)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@router.put("/{subject_type}/{subject_id}/summary", response_model=SubjectPage)
def set_summary(
    subject_type: SubjectType,
    subject_id: str,
    update: SummaryUpdate,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    """The 개요 paragraph at the top of a page. Not a chronicled value."""
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)
    saved.summary = update.summary.strip()
    if not saved.title:
        saved.title = _title(project, subject_type, subject_id)
    store.save_wiki_subject(saved)
    return _build_page(project, subject_type, subject_id)


def _slugify(value: str) -> str:
    slug = re.sub(r"[\s_]+", "-", value.strip().lower())
    slug = re.sub(r"[^\w가-힣-]", "", slug, flags=re.UNICODE)
    return re.sub(r"-{2,}", "-", slug).strip("-")


@router.post("/{subject_type}/{subject_id}/sections", response_model=SubjectPage)
def add_section(
    subject_type: SubjectType,
    subject_id: str,
    body: NewSection,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    """Add a section the registry has never heard of — 능력, 과거사, 명대사.

    These reach the model as labelled prose rather than as a typed field, and
    the summarizer records into them like any other, because a section the
    author thought worth having is a section that affects the story.
    """
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)

    key = _slugify(body.key or body.title)
    if not key or not _KEY.match(key):
        raise HTTPException(status_code=422, detail=f"{body.title!r}에서 쓸 만한 섹션 이름을 만들지 못했습니다")
    if section_for(subject_type, key) is not None or saved.section(key) is not None:
        raise HTTPException(status_code=409, detail=f"이미 {key!r} 섹션이 있습니다")

    saved.free_sections.append(
        SectionSpec(
            key=key, title=body.title, kind=body.kind, order=body.order, author_made=True
        )
    )
    store.save_wiki_subject(saved)
    return _build_page(project, subject_type, subject_id)


@router.put("/{subject_type}/{subject_id}/sections/{section_key}", response_model=SubjectPage)
def rename_section(
    subject_type: SubjectType,
    subject_id: str,
    section_key: str,
    body: SectionUpdate,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)
    spec = saved.section(section_key)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail="바꿀 수 있는 것은 직접 만드신 섹션뿐입니다",
        )
    if body.title is not None and body.title.strip():
        spec.title = body.title.strip()
    if body.order is not None:
        spec.order = body.order
    store.save_wiki_subject(saved)
    return _build_page(project, subject_type, subject_id)


@router.delete("/{subject_type}/{subject_id}/sections/{section_key}", response_model=SubjectPage)
def delete_section(
    subject_type: SubjectType,
    subject_id: str,
    section_key: str,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    """Remove a section the author added. Its history is kept.

    Deleting the section does not delete what happened — the entries stay in
    the chronicle, and re-adding the section brings them back into view. A
    wiki that lost history on a layout change would not be a record.
    """
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)
    spec = saved.section(section_key)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail="지울 수 있는 것은 직접 만드신 섹션뿐입니다",
        )
    saved.free_sections = [s for s in saved.free_sections if s.key != section_key]
    store.save_wiki_subject(saved)
    return _build_page(project, subject_type, subject_id)


@router.post(
    "/{subject_type}/{subject_id}/sections/{section_key}/entries",
    response_model=SubjectPage,
)
def add_entry(
    subject_type: SubjectType,
    subject_id: str,
    section_key: str,
    body: NewEntry,
    project: Project = Depends(deps.get_project),
) -> SubjectPage:
    """Change what a section says — by adding to its history, not overwriting it.

    This is how every author edit lands, from this page or from the Character
    Workshop. The previous value is read from the chain, or from the typed
    model when the chain is empty, so the first edit records where the story
    started rather than losing it.
    """
    store = _chronicle()
    saved = store.get_wiki_subject(subject_type, subject_id)
    spec = section_for(subject_type, section_key) or saved.section(section_key)
    is_relationship = relationship_target(section_key) is not None
    if spec is None and not is_relationship:
        raise HTTPException(status_code=404, detail=f"{section_key!r} 섹션이 없습니다")

    kind = spec.kind if spec is not None else "stateful"
    if kind != "log" and not body.value.strip():
        raise HTTPException(status_code=422, detail="빈 값으로는 바꿀 수 없습니다")
    if kind == "log" and not body.value.strip():
        raise HTTPException(status_code=422, detail="빈 기록은 남길 수 없습니다")

    previous = None
    if kind != "log" and not store.chain(subject_type, subject_id, section_key):
        base = _subject(project, subject_type, subject_id)
        if spec is not None:
            previous = _base_value(base, spec, subject_id)

    store.record(
        subject_type,
        subject_id,
        section_key,
        body.value,
        source="author",
        kind=body.kind,
        reason=body.reason,
        previous=previous,
        section_kind=kind,
    )
    return _build_page(project, subject_type, subject_id)


@router.put("/entries/{entry_id}", response_model=ChronicleEntry)
def edit_entry(entry_id: str, body: EntryEdit) -> ChronicleEntry:
    """Correct what an entry says. Where it sits in history does not move."""
    store = _chronicle()
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    updated = store.edit(entry_id, **changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="그런 기록이 없습니다")
    return updated


@router.post("/entries/{entry_id}/retract", response_model=ChronicleEntry)
def retract_entry(entry_id: str) -> ChronicleEntry:
    """Take back an entry — the way an author undoes a change the AI invented.

    Marked, not deleted. The section falls back to whatever it said before, and
    the retraction itself stays visible.
    """
    store = _chronicle()
    updated = store.retract(entry_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="그런 기록이 없습니다")
    return updated


# ---------------------------------------------------------------------------
# The author's review
# ---------------------------------------------------------------------------


class PendingReview(BaseModel):
    episode_number: int | None = None
    entries: list[ChronicleEntry] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    accept: list[str] = Field(default_factory=list)
    discard: list[str] = Field(default_factory=list)


@router.get("/pending", response_model=PendingReview)
def pending_review(episode: int | None = None) -> PendingReview:
    """What a chapter recorded, waiting for the author to accept it.

    Nothing here counts yet. The fold skips a pending entry, so a change the
    summarizer invented cannot reach the next chapter's prompt before someone
    has looked at it — which matters because the chronicle overrides the
    author's own setting.
    """
    store = _chronicle()
    return PendingReview(episode_number=episode, entries=store.pending(episode))


@router.post("/pending/apply", response_model=PendingReview)
def apply_review(body: ReviewDecision, episode: int | None = None) -> PendingReview:
    """Accept some proposals and throw the rest away.

    Accepting lets an entry count from now on. Discarding deletes it outright
    rather than striking it through: a proposal the author never accepted is
    not part of the story's history, and leaving it on the page would bury the
    record in things that did not happen.
    """
    store = _chronicle()
    for entry_id in body.accept:
        store.accept(entry_id)
    for entry_id in body.discard:
        store.discard(entry_id)
    logger.info(
        "Review applied: %d accepted, %d discarded", len(body.accept), len(body.discard)
    )
    return PendingReview(episode_number=episode, entries=store.pending(episode))


@router.post("/entries/{entry_id}/restore", response_model=ChronicleEntry)
def restore_entry(entry_id: str) -> ChronicleEntry:
    store = _chronicle()
    updated = store.restore(entry_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="그런 기록이 없습니다")
    return updated
