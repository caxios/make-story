"""Carrying edits to a committed concept into the work.

Committing is a one-time write: the concept becomes the world, the cast, the
work's page and the queue. After that the author keeps working in the concept
screen — refining, editing by hand — and this is how those later changes reach
the work.

The rule is **only what changed in the concept moves**. The comparison is
between the concept as it was last carried over (`before`) and as it is now
(`after`), never between the concept and the project. By the time the author
edits the concept again, the project has usually moved on its own — a
character's look changed in chapter 9, a rule rewritten in the World Builder —
and comparing against the project would treat every one of those as something
to overwrite. Comparing concept to concept touches only what the author just
changed here.

Some changes are not carried, and are said so rather than half-done:

- a character, rule or place **removed** from the concept is not deleted from
  the work — deletion has its own screens, with their own warnings, and a
  character the story has used should not vanish because a planning note did;
- an episode line for a chapter that is **already written**, or that is not in
  the queue at all, is not applied — the queue owns episodes from commit on.

No model calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from storyweaver.ids import unique_id
from storyweaver.models import CharacterProfile, Location, Relationship, Rule
from storyweaver.models.concept import ConceptCharacter, StoryConcept
from storyweaver.wiki.commit import (
    DEFAULT_RULE_CATEGORY,
    _relationship_note,
    _role,
    _rule_id_source,
)
from storyweaver.wiki.sections import STORY_SUBJECT_ID
from storyweaver.wiki.writeback import (
    record_character_edit,
    record_world_edit,
)

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.memory.chronicle_store import ChronicleStore
    from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

# Episodes a concept edit may re-outline: queued, nothing written.
REWRITABLE = ("queued", "planned")


class SyncReport:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.skipped: list[str] = []

    def as_dict(self) -> dict:
        return {"applied": self.applied, "skipped": self.skipped}

    @property
    def empty(self) -> bool:
        return not self.applied and not self.skipped


def _clean(values: list[str]) -> list[str]:
    return [v.strip() for v in values if v.strip()]


def _relationships(
    proposed: ConceptCharacter, ids: dict[str, str], own_id: str, report: SyncReport
) -> list[Relationship]:
    out = []
    for raw in proposed.relationships:
        target_name, described = _relationship_note(raw)
        target_id = ids.get(target_name)
        if target_id is None or target_id == own_id:
            report.skipped.append(f"{proposed.name}의 관계 '{raw}' — 그런 인물이 없습니다")
            continue
        out.append(
            Relationship(target_character_id=target_id, type=described or "관계", sentiment=0.0)
        )
    return out


def _character_changes(before: ConceptCharacter, after: ConceptCharacter) -> dict:
    """The profile fields to update: only those the concept edit moved."""
    changes: dict = {}
    if after.role.strip() != before.role.strip():
        changes["role"] = _role(after.role)
    if after.age != before.age:
        changes["age"] = after.age
    if (after.gender or "").strip() != (before.gender or "").strip():
        changes["gender"] = (after.gender or "").strip() or None
    if after.appearance.strip() != before.appearance.strip():
        changes["appearance"] = after.appearance.strip()
    if after.personality.strip() != before.personality.strip():
        changes["personality_summary"] = after.personality.strip()
    if after.speech.strip() != before.speech.strip():
        changes["speech_style"] = after.speech.strip()
    if after.goal.strip() != before.goal.strip():
        changes["goals"] = [after.goal.strip()] if after.goal.strip() else []
    if after.secret.strip() != before.secret.strip():
        changes["secrets"] = [after.secret.strip()] if after.secret.strip() else []
    return changes


FIELD_LABELS = {
    "role": "역할", "age": "나이", "gender": "성별", "appearance": "외모",
    "personality_summary": "성격", "speech_style": "말투", "goals": "목표",
    "secrets": "비밀", "relationships": "관계",
}


def sync_concept(
    project: Project,
    chronicle: ChronicleStore | None,
    before: StoryConcept,
    after: StoryConcept,
) -> SyncReport:
    """Apply what changed between `before` and `after` to `project`.

    `project` is mutated and must be saved by the caller under its lock. Pass
    `chronicle=None` for a dry run that only reports.
    """
    report = SyncReport()

    # --- the world header -----------------------------------------------------
    world_changes: dict = {}
    for field, target, label in (
        ("title", "title", "제목"),
        ("genre", "genre", "장르"),
        ("tone", "tone", "톤"),
        ("premise", "overview", "세계관 개요"),
    ):
        if getattr(after, field).strip() != getattr(before, field).strip():
            world_changes[target] = getattr(after, field).strip()
            report.applied.append(f"세계관 {label}")
    if (after.era or "").strip() != (before.era or "").strip():
        world_changes["era"] = (after.era or "").strip() or None
        report.applied.append("세계관 시대")
    if _clean(after.factions) != _clean(before.factions):
        world_changes["factions"] = _clean(after.factions)
        report.applied.append("세력 목록")
    if world_changes:
        project.world = project.world.model_copy(update=world_changes)
        if chronicle is not None:
            record_world_edit(chronicle, project.world)

    # --- the work's own page --------------------------------------------------
    for section, label in (
        ("logline", "한 줄 요약"), ("premise", "기획 의도"),
        ("arc", "전체 아크"), ("ending", "계획된 결말"),
    ):
        value = getattr(after, section).strip()
        if value and value != getattr(before, section).strip():
            report.applied.append(f"작품 문서 · {label}")
            if chronicle is not None:
                chronicle.record(
                    "story", STORY_SUBJECT_ID, section, value,
                    source="author", reason="작품 기획에서 수정",
                )

    # --- rules and places: additions only ------------------------------------
    old_rules, new_rules = _clean(before.rules), _clean(after.rules)
    taken = {rule.id for rule in project.world.rules}
    for index, statement in enumerate(new_rules, start=1):
        if statement in old_rules:
            continue
        rule_id = unique_id(_rule_id_source(statement), f"rule-{index}", taken)
        taken.add(rule_id)
        project.upsert_rule(Rule(id=rule_id, category=DEFAULT_RULE_CATEGORY, statement=statement))
        report.applied.append(f"규칙 추가: {statement}")
    for statement in old_rules:
        if statement not in new_rules:
            report.skipped.append(f"규칙 '{statement}' — 삭제는 세계관 빌더에서 해 주세요")

    old_places, new_places = _clean(before.locations), _clean(after.locations)
    taken = {place.id for place in project.world.locations}
    for index, name in enumerate(new_places, start=1):
        if name in old_places:
            continue
        place_id = unique_id(name, f"location-{index}", taken)
        taken.add(place_id)
        project.upsert_location(Location(id=place_id, name=name, description=""))
        report.applied.append(f"장소 추가: {name}")
    for name in old_places:
        if name not in new_places:
            report.skipped.append(f"장소 '{name}' — 삭제는 세계관 빌더에서 해 주세요")

    # --- the cast ---------------------------------------------------------------
    by_name = {c.name.strip(): c for c in project.characters}
    old_cast = {c.name.strip(): c for c in before.characters if c.name.strip()}
    new_cast = {c.name.strip(): c for c in after.characters if c.name.strip()}

    # Ids for newcomers first, so a relationship can name someone added in the
    # same edit.
    taken = {c.id for c in project.characters}
    ids = {name: c.id for name, c in by_name.items()}
    for index, name in enumerate(new_cast, start=1):
        if name not in ids:
            ids[name] = unique_id(name, f"character-{index}", taken)
            taken.add(ids[name])

    for name, proposed in new_cast.items():
        existing = by_name.get(name)
        if existing is None:
            project.upsert_character(
                CharacterProfile(
                    id=ids[name],
                    name=name,
                    role=_role(proposed.role),
                    age=proposed.age,
                    gender=(proposed.gender or "").strip() or None,
                    appearance=proposed.appearance.strip(),
                    personality_summary=proposed.personality.strip(),
                    speech_style=proposed.speech.strip(),
                    goals=[proposed.goal.strip()] if proposed.goal.strip() else [],
                    secrets=[proposed.secret.strip()] if proposed.secret.strip() else [],
                    relationships=_relationships(proposed, ids, ids[name], report),
                )
            )
            report.applied.append(f"인물 추가: {name}")
            continue

        previous = old_cast.get(name)
        if previous is None:
            # In the work but not in the concept last time (added in the
            # workshop, say). Nothing to compare against, so nothing moves.
            continue
        changes = _character_changes(previous, proposed)
        if [r.strip() for r in proposed.relationships] != [r.strip() for r in previous.relationships]:
            kept = [r for r in existing.relationships
                    if r.target_character_id not in {ids.get(_relationship_note(x)[0]) for x in previous.relationships}]
            changes["relationships"] = kept + _relationships(proposed, ids, existing.id, report)
        if changes:
            updated = existing.model_copy(update=changes)
            project.upsert_character(updated)
            if chronicle is not None:
                record_character_edit(chronicle, updated)
            report.applied.append(
                f"인물 {name}: " + ", ".join(FIELD_LABELS.get(k, k) for k in changes)
            )

    for name in old_cast:
        if name not in new_cast and name in by_name:
            report.skipped.append(f"인물 '{name}' — 삭제는 캐릭터 워크숍에서 해 주세요")

    # --- episode lines ----------------------------------------------------------
    old_lines = {e.number: e.line.strip() for e in before.episodes}
    for episode in after.episodes:
        line = episode.line.strip()
        if not line or old_lines.get(episode.number) == line:
            continue
        queued = project.get_episode(episode.number)
        if queued is None:
            report.skipped.append(f"{episode.number}화 구상 — 큐에 없는 회차입니다. 에피소드 큐에서 추가해 주세요")
            continue
        if queued.status not in REWRITABLE or queued.final_text.strip():
            report.skipped.append(f"{episode.number}화 구상 — 이미 쓴 회차라 바꾸지 않았습니다")
            continue
        updates: dict = {"author_storyline": line}
        if queued.status == "planned":
            updates.update({"status": "queued", "scenes": []})
        project.update_episode(queued.model_copy(update=updates))
        report.applied.append(f"{episode.number}화 개요")
        if chronicle is not None:
            chronicle.record(
                "story", STORY_SUBJECT_ID, "episodes", f"{episode.number}화 — {line}",
                source="author", section_kind="log",
            )

    logger.info(
        "Concept sync: %d applied, %d skipped", len(report.applied), len(report.skipped)
    )
    return report
