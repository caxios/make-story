"""Registering what an outline or a plan brought in.

`agents/settings_extract.py` reads the text; this writes what it found where
the author would look for it: a new character into the workshop, a place or a
rule into the world builder, a faction and a world fact into the wiki, a change
of direction onto the work's own page. Each one also leaves a line in the
work's 기획 기록, so the author can see where a setting came from.

Registering is **the latest version, not a history**. A fact about an existing
character is written as their setting now — the way an author's own edit is —
and not as something that happened in an episode: it was always true, the
outline only wrote it down.

Nothing here calls a model, and the caller holds the write lock and saves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from storyweaver.ids import unique_id
from storyweaver.models import CharacterProfile, Location, Relationship, Rule
from storyweaver.models.chronicle import SectionSpec
from storyweaver.wiki.commit import DEFAULT_RULE_CATEGORY, _relationship_note, _role, _rule_id_source
from storyweaver.wiki.fold import current_value, fold_character
from storyweaver.wiki.sections import STORY_SUBJECT_ID
from storyweaver.wiki.writeback import record_character_edit

if TYPE_CHECKING:  # pragma: no cover
    from storyweaver.agents.settings_extract import ExtractedSettings
    from storyweaver.memory.chronicle_store import ChronicleStore
    from storyweaver.models.concept import StoryConcept
    from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

# Author-made sections on the world page start after the registry's own.
WORLD_FACT_ORDER = 100
LIST_FIELDS = {"secret": "secrets", "goal": "goals"}
TEXT_FIELDS = {
    "backstory": "backstory",
    "appearance": "appearance",
    "speech": "speech_style",
    "personality": "personality_summary",
}
FIELD_LABELS = {
    "backstory": "과거", "secret": "비밀", "goal": "목표", "appearance": "외모",
    "speech": "말투", "personality": "성격", "relationship": "관계",
}


@dataclass
class Registered:
    """What was written, as lines for the author, and the ids new people got."""

    lines: list[str] = field(default_factory=list)
    character_ids: dict[str, str] = field(default_factory=dict)
    location_ids: dict[str, str] = field(default_factory=dict)


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _find_character(project: Project, name: str) -> CharacterProfile | None:
    return next((c for c in project.characters if _same(c.name, name)), None)


def _joined(existing: str, addition: str) -> str:
    existing, addition = existing.strip(), addition.strip()
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing}\n{addition}"


def register_settings(
    project: Project,
    chronicle: ChronicleStore | None,
    found: ExtractedSettings,
    *,
    source: str,
    preset_character_ids: dict[str, str] | None = None,
    preset_location_ids: dict[str, str] | None = None,
) -> Registered:
    """Write `found` into `project` (and the wiki). `source` says where it came
    from, e.g. "14화 개요", for the lines the author is shown.

    `preset_*_ids` are ids a plan already uses for someone new — the Director
    names a newcomer before they exist — kept when they are free.
    """
    done = Registered()
    presets = preset_character_ids or {}
    place_presets = preset_location_ids or {}

    # --- people -------------------------------------------------------------
    taken = {c.id for c in project.characters}
    fresh: list = []
    for proposed in found.new_characters:
        name = proposed.name.strip()
        if not name:
            continue
        existing = _find_character(project, name)
        if existing is not None:
            done.character_ids[name] = existing.id
            continue
        wanted = presets.get(name, "")
        character_id = wanted if wanted and wanted not in taken else unique_id(
            name, f"character-{len(taken) + 1}", taken
        )
        taken.add(character_id)
        done.character_ids[name] = character_id
        fresh.append((proposed, character_id))
        # Registered before relationships are resolved, so two newcomers can
        # name each other.
        project.upsert_character(CharacterProfile(
            id=character_id, name=name, role=_role(proposed.role),
            appearance="", personality_summary="", speech_style="",
        ))

    for proposed, character_id in fresh:
        relationships = []
        for raw in proposed.relationships:
            target_name, described = _relationship_note(raw)
            target = _find_character(project, target_name)
            if target is None or target.id == character_id:
                continue
            relationships.append(
                Relationship(target_character_id=target.id, type=described or "관계")
            )
        project.upsert_character(
            CharacterProfile(
                id=character_id,
                name=proposed.name.strip(),
                role=_role(proposed.role),
                age=proposed.age,
                gender=(proposed.gender or "").strip() or None,
                appearance=proposed.appearance.strip(),
                personality_summary=proposed.personality.strip(),
                speech_style=proposed.speech.strip(),
                goals=[proposed.goal.strip()] if proposed.goal.strip() else [],
                secrets=[proposed.secret.strip()] if proposed.secret.strip() else [],
                backstory=proposed.backstory.strip(),
                relationships=relationships,
            )
        )
        done.lines.append(f"인물 추가: {proposed.name.strip()} ({_role(proposed.role)})")

    # --- what was always true of someone already there -----------------------
    for fact in found.character_facts:
        base = _find_character(project, fact.name)
        value = fact.value.strip()
        if base is None or not value:
            continue
        current = fold_character(chronicle, base) if chronicle is not None else base
        kind = fact.field.strip().lower()
        update: dict = {}
        if kind in LIST_FIELDS:
            attr = LIST_FIELDS[kind]
            items = list(getattr(current, attr))
            if not any(_same(item, value) for item in items):
                update[attr] = [*items, value]
        elif kind in TEXT_FIELDS:
            attr = TEXT_FIELDS[kind]
            joined = _joined(getattr(current, attr) or "", value)
            if joined != (getattr(current, attr) or "").strip():
                update[attr] = joined
        elif kind == "relationship" and fact.target:
            other = _find_character(project, fact.target)
            if other is not None and other.id != base.id and not any(
                r.target_character_id == other.id for r in current.relationships
            ):
                update["relationships"] = [
                    *base.relationships, Relationship(target_character_id=other.id, type=value)
                ]
        if not update:
            continue
        # Onto the stored sheet, and through the chronicle where the field has
        # a history — exactly as an edit in the workshop is.
        edited = base.model_copy(update=update)
        project.upsert_character(edited)
        if chronicle is not None:
            record_character_edit(chronicle, edited)
        label = FIELD_LABELS.get(kind, kind)
        target = f" → {fact.target}" if kind == "relationship" and fact.target else ""
        done.lines.append(f"{base.name} {label}{target}: {value}")

    # --- the world ------------------------------------------------------------
    place_ids = {p.id for p in project.world.locations}
    for place in found.new_locations:
        name = place.name.strip()
        if not name:
            continue
        existing = next((p for p in project.world.locations if _same(p.name, name)), None)
        if existing is not None:
            done.location_ids[name] = existing.id
            continue
        wanted = place_presets.get(name, "")
        place_id = wanted if wanted and wanted not in place_ids else unique_id(
            name, f"location-{len(place_ids) + 1}", place_ids
        )
        place_ids.add(place_id)
        done.location_ids[name] = place_id
        project.upsert_location(Location(id=place_id, name=name, description=place.description.strip()))
        done.lines.append(f"장소 추가: {name}")

    rule_ids = {r.id for r in project.world.rules}
    for statement in found.new_rules:
        statement = statement.strip()
        if not statement or any(_same(r.statement, statement) for r in project.world.rules):
            continue
        rule_id = unique_id(_rule_id_source(statement), f"rule-{len(rule_ids) + 1}", rule_ids)
        rule_ids.add(rule_id)
        project.upsert_rule(Rule(id=rule_id, category=DEFAULT_RULE_CATEGORY, statement=statement))
        done.lines.append(f"규칙 추가: {statement}")

    faction_ids = (
        {sid for stype, sid in chronicle.known_subjects() if stype == "faction"}
        if chronicle is not None else set()
    )
    for faction in found.new_factions:
        name = faction.name.strip()
        if not name or any(_same(f, name) for f in project.world.factions):
            continue
        project.world.factions = [*project.world.factions, name]
        if chronicle is not None:
            faction_id = unique_id(name, f"faction-{len(faction_ids) + 1}", faction_ids)
            faction_ids.add(faction_id)
            page = chronicle.get_wiki_subject("faction", faction_id)
            page.title = name
            chronicle.save_wiki_subject(page)
            if faction.description.strip():
                chronicle.record(
                    "faction", faction_id, "description", faction.description.strip(),
                    source="author",
                )
        done.lines.append(f"세력 추가: {name}")

    for fact in found.world_facts:
        title, detail = fact.title.strip(), fact.detail.strip()
        if not title or not detail:
            continue
        if chronicle is None:
            if title not in project.world.additional_lore:
                project.world.additional_lore[title] = detail
                done.lines.append(f"세계 설정 추가: {title}")
            continue
        # A section of its own on the world page: editable and deletable in the
        # wiki, and folded into every agent's view of the world.
        page = chronicle.get_wiki_subject("world", "world")
        spec = next((s for s in page.free_sections if _same(s.title, title)), None)
        if spec is None:
            keys = {s.key for s in page.free_sections}
            spec = SectionSpec(
                key=unique_id(title, f"lore-{len(keys) + 1}", keys),
                title=title,
                order=WORLD_FACT_ORDER + len(page.free_sections),
                author_made=True,
            )
            page.free_sections.append(spec)
            chronicle.save_wiki_subject(page)
        now = current_value(chronicle, "world", "world", spec.key) or ""
        joined = _joined(now, detail)
        if joined != now.strip():
            chronicle.record("world", "world", spec.key, joined, source="author")
            done.lines.append(f"세계 설정: {title}")

    # --- where the work is going ------------------------------------------------
    direction = found.direction
    if direction is not None and chronicle is not None:
        for section, label, value in (
            ("logline", "로그라인", direction.logline),
            ("arc", "전체 아크", direction.arc),
            ("ending", "계획된 결말", direction.ending),
        ):
            value = value.strip()
            now = current_value(chronicle, "story", STORY_SUBJECT_ID, section) or ""
            if value and value != now.strip():
                chronicle.record("story", STORY_SUBJECT_ID, section, value, source="author")
                done.lines.append(f"작품 방향 수정: {label}")

    if chronicle is not None:
        for line in done.lines:
            chronicle.record(
                "story", STORY_SUBJECT_ID, "decisions", f"[{source}] {line}",
                source="author", section_kind="log",
            )
    if done.lines:
        logger.info("Registered from %s: %s", source, "; ".join(done.lines))
    return done


def extend_concept(concept: StoryConcept, found: ExtractedSettings) -> StoryConcept:
    """The concept, with what an outline brought in added to it.

    So 작품기획 shows the novel as it now is, and a later edit there is compared
    against a concept that already has these — nothing is applied twice.
    """
    from storyweaver.models.concept import ConceptCharacter

    names = {c.name.strip() for c in concept.characters}
    characters = list(concept.characters)
    for proposed in found.new_characters:
        if proposed.name.strip() and proposed.name.strip() not in names:
            names.add(proposed.name.strip())
            characters.append(
                ConceptCharacter(
                    name=proposed.name.strip(), role=_role(proposed.role), age=proposed.age,
                    gender=proposed.gender, appearance=proposed.appearance,
                    personality=proposed.personality, speech=proposed.speech,
                    goal=proposed.goal, secret=proposed.secret,
                    relationships=list(proposed.relationships),
                )
            )

    def added(existing: list[str], new: list[str]) -> list[str]:
        out = list(existing)
        for item in new:
            if item.strip() and not any(_same(item, e) for e in out):
                out.append(item.strip())
        return out

    update: dict = {
        "characters": characters,
        "locations": added(concept.locations, [p.name for p in found.new_locations]),
        "factions": added(concept.factions, [f.name for f in found.new_factions]),
        "rules": added(concept.rules, list(found.new_rules)),
    }
    direction = found.direction
    if direction is not None:
        for key in ("logline", "arc", "ending"):
            value = getattr(direction, key).strip()
            if value:
                update[key] = value
    return concept.model_copy(update=update)


__all__ = ["Registered", "extend_concept", "register_settings"]
