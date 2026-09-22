"""Helpers that turn Phase 1 models into the plain-text blocks prompts expect."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from storyweaver.models import (
    CharacterProfile,
    InteractionEntry,
    Location,
    Rule,
    StoryBeat,
    WorldLore,
)

NONE_PLACEHOLDER = "(none)"


def as_character_map(
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
) -> dict[str, CharacterProfile]:
    """Accept either a `{id: profile}` mapping or a plain iterable of profiles."""
    if isinstance(characters, Mapping):
        return dict(characters)
    return {c.id: c for c in characters}


def format_bullets(items: Iterable[str]) -> str:
    lines = [f"- {item}" for item in items if item]
    return "\n".join(lines) if lines else NONE_PLACEHOLDER


def format_rules(rules: Sequence[Rule]) -> str:
    def one(rule: Rule) -> str:
        text = f"[{rule.category}] {rule.statement}"
        if rule.exceptions:
            text += " (Exceptions: " + "; ".join(rule.exceptions) + ")"
        return text

    return format_bullets(one(rule) for rule in rules)


def format_locations(locations: Sequence[Location]) -> str:
    def one(loc: Location) -> str:
        text = f"{loc.id} — {loc.name}: {loc.description}"
        if loc.parent_location_id:
            text += f" (inside {loc.parent_location_id})"
        if loc.notable_features:
            text += " Features: " + ", ".join(loc.notable_features) + "."
        return text

    return format_bullets(one(loc) for loc in locations)


def format_character_summaries(characters: Sequence[CharacterProfile]) -> str:
    """Short one-per-character blurbs, for the Director's casting decisions."""

    def one(c: CharacterProfile) -> str:
        parts = [f"{c.id} — {c.name}: {c.personality_summary}"]
        if c.goals:
            parts.append("Goals: " + ", ".join(c.goals) + ".")
        return " ".join(parts)

    return format_bullets(one(c) for c in characters)


# The role vocabulary the Character Workshop offers, plus the English values
# earlier versions wrote. A project holds a mixture of both, and a prompt that
# showed one character as "protagonist" and the next as "조연" would be asking
# the model to read two vocabularies at once.
ROLE_LABELS = {
    "protagonist": "주인공",
    "antagonist": "적대자 / 악역",
    "deuteragonist": "서브 주인공",
    "supporting": "조연",
    "mentor": "스승 / 조력자",
    "foil": "라이벌 / 대조 인물",
    "love interest": "연인 / 히로인",
    "minor": "단역 / 엑스트라",
}


def describe_role(role: str) -> str:
    """A character's story role, in the words the author sees in the UI."""
    return ROLE_LABELS.get(role.strip().lower(), role.strip())


def format_traits(character: CharacterProfile) -> str:
    def one(trait) -> str:
        text = f"{trait.name} (intensity {trait.intensity:.1f})"
        if trait.description:
            text += f" — {trait.description}"
        return text

    return format_bullets(one(t) for t in character.traits)


def format_relationships(
    character: CharacterProfile,
    present_ids: Iterable[str],
    characters: Mapping[str, CharacterProfile],
) -> str:
    """Only the relationships that matter right now — the ones in this scene."""
    present = set(present_ids) - {character.id}

    def one(rel) -> str:
        other = characters.get(rel.target_character_id)
        name = other.name if other else rel.target_character_id
        text = f"{name} ({rel.target_character_id}) — {rel.type}, sentiment {rel.sentiment:+.1f}"
        if rel.description:
            text += f": {rel.description}"
        return text

    return format_bullets(
        one(rel) for rel in character.relationships if rel.target_character_id in present
    )


def format_beats(beats: Sequence[StoryBeat]) -> str:
    def one(beat: StoryBeat) -> str:
        text = beat.description
        if beat.mood:
            text += f" (mood: {beat.mood})"
        return text

    return format_bullets(one(beat) for beat in beats)


def format_world_summary(world: WorldLore) -> str:
    """The world as every agent is told it.

    Factions and `additional_lore` are included because they were not, and an
    author who wrote "불사조 기사단" into the world got a model that had never
    heard of it. They are stored, exported and indexed for recall — this is the
    only path by which they reach a prompt, and it is shared by the Director,
    the Character Agent, the Lore Checker, the Writer and the Summarizer.
    """
    era = f", {world.era}" if world.era else ""
    parts = [f"{world.title} — a {world.tone} {world.genre} setting{era}.", world.overview]

    if world.factions:
        parts.append("Factions and powers: " + ", ".join(world.factions) + ".")
    for heading, body in world.additional_lore.items():
        if str(body).strip():
            parts.append(f"{heading}: {body}")

    return "\n\n".join(part for part in parts if str(part).strip())


def format_interaction_log(
    entries: Sequence[InteractionEntry],
    limit: int | None = None,
    characters: Mapping[str, CharacterProfile] | None = None,
    show_turns: bool = False,
) -> str:
    """Render the log for a prompt, optionally keeping only the last `limit` turns.

    `show_turns` prefixes each line with its turn number, which the Lore Checker
    needs so it can point at the entry it is objecting to.
    """
    shown = entries[-limit:] if limit else entries
    if not shown:
        return "(nothing yet — you are opening the scene)"

    def one(entry: InteractionEntry) -> str:
        speaker = entry.character_id
        if characters and entry.character_id in characters:
            speaker = characters[entry.character_id].name
        target = ""
        if entry.directed_at:
            target = entry.directed_at
            if characters and entry.directed_at in characters:
                target = characters[entry.directed_at].name
            target = f" (to {target})"
        prefix = f"Turn {entry.turn} — " if show_turns else ""
        return f"{prefix}{speaker}{target} [{entry.type}]: {entry.content}"

    return "\n".join(one(entry) for entry in shown)


def present_character_names(
    ids: Iterable[str], characters: Mapping[str, CharacterProfile]
) -> str:
    names = [
        f"{characters[i].name} ({i})" if i in characters else i for i in ids
    ]
    return ", ".join(names) if names else NONE_PLACEHOLDER
