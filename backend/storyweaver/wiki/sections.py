"""Which sections each kind of subject has, and what each one stands for.

This is code rather than configuration on purpose. A section's `bound_field`
names an attribute on a typed model, and the chain of entries under that
section is the history of that attribute. If a field is renamed and this table
is not, every entry in its chain is orphaned — silently, because an orphaned
chain simply folds to nothing and the model's own value quietly wins again.
Being code means a rename fails a test instead.
"""

from __future__ import annotations

from storyweaver.models.chronicle import SectionSpec, SubjectType

# A character has many relationships, so one section cannot hold them. Each
# pair gets its own chain under `relationship:<target_id>`, which is what makes
# "시월과의 관계: 경계 → 동료 → 연인" read as one history instead of a pile of
# list edits.
RELATIONSHIP_PREFIX = "relationship:"


def relationship_section_key(target_character_id: str) -> str:
    return f"{RELATIONSHIP_PREFIX}{target_character_id}"


def relationship_target(section_key: str) -> str | None:
    """The other character in a relationship section, or None if not one."""
    if not section_key.startswith(RELATIONSHIP_PREFIX):
        return None
    return section_key[len(RELATIONSHIP_PREFIX) :] or None


CHARACTER_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="summary", title="개요", bound_field="personality_summary", order=10),
    SectionSpec(key="appearance", title="외모", bound_field="appearance", order=20),
    SectionSpec(key="personality", title="성격", bound_field="traits", order=30),
    SectionSpec(key="speech", title="말투", bound_field="speech_style", order=40),
    SectionSpec(key="role", title="역할", bound_field="role", order=50),
    SectionSpec(key="values", title="가치관", bound_field="values", order=60),
    SectionSpec(key="goals", title="목표", bound_field="goals", order=70),
    SectionSpec(key="backstory", title="과거", bound_field="backstory", order=80),
    # Relationships are held as `relationship:<id>` chains rather than one
    # section; this entry is the heading they are grouped under.
    SectionSpec(key="relationships", title="인간관계", bound_field="relationships", order=90),
    SectionSpec(key="secrets", title="비밀", bound_field="secrets", order=100),
    # No current value — the entries are the content, oldest first. This is the
    # author's "what did they do in this episode", as opposed to "what changed".
    SectionSpec(key="deeds", title="작중 행적", kind="log", order=110),
]

WORLD_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="overview", title="개요", bound_field="overview", order=10),
    SectionSpec(key="tone", title="분위기", bound_field="tone", order=20),
    SectionSpec(key="era", title="시대", bound_field="era", order=30),
    SectionSpec(key="genre", title="장르", bound_field="genre", order=40),
    SectionSpec(key="events", title="주요 사건", kind="log", order=50),
]

LOCATION_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="description", title="개요", bound_field="description", order=10),
    SectionSpec(key="features", title="특징", bound_field="notable_features", order=20),
    # Where "유적이 파괴됨", "게이트가 고장남", "게이트가 수리됨" live. A place's
    # state can go and come back, which is why `removed` and `restored` exist.
    SectionSpec(key="state", title="상태", bound_field="status", order=30),
    SectionSpec(key="events", title="작중 변화", kind="log", order=40),
]

RULE_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="statement", title="조문", bound_field="statement", order=10),
    SectionSpec(key="exceptions", title="예외", bound_field="exceptions", order=20),
    # A rule can be abolished mid-story; `statement` cannot say so.
    SectionSpec(key="active", title="효력", bound_field="active", order=30),
]

# Factions have no typed model yet — `WorldLore.factions` is still a list of
# bare names. These sections are therefore unbound: the chronicle can hold a
# faction's history today, and it reaches prompts as prose the way any free
# section does. They gain `bound_field` when `Faction` lands.
FACTION_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="description", title="개요", order=10),
    SectionSpec(key="events", title="작중 행적", kind="log", order=20),
]

# The work itself: what it is about, where it is going, and how it is meant to
# end. There is no typed model behind any of this, so every section is prose —
# and that is the point. An arc is a plan, not a setting, and the moment it is
# stored as world lore it reaches every character's prompt (see `SubjectType`).
#
# `STORY_SUBJECT_ID` is a constant the way the world's is: there is one work.
STORY_SUBJECT_ID = "story"

STORY_SECTIONS: list[SectionSpec] = [
    SectionSpec(key="logline", title="로그라인", order=10),
    SectionSpec(key="premise", title="기획 의도", order=20),
    SectionSpec(key="arc", title="전체 아크", order=30),
    SectionSpec(key="ending", title="계획된 결말", order=40),
    # Rough, one line per episode, at the resolution the arc needs. The detailed
    # plan for a chapter is made just before it is written and approved then.
    SectionSpec(key="episodes", title="회차 구상", kind="log", order=50),
    # How the concept came to be: what was asked for, and what changed.
    SectionSpec(key="decisions", title="기획 기록", kind="log", order=60),
]

SECTIONS_BY_TYPE: dict[SubjectType, list[SectionSpec]] = {
    "story": STORY_SECTIONS,
    "character": CHARACTER_SECTIONS,
    "world": WORLD_SECTIONS,
    "location": LOCATION_SECTIONS,
    "rule": RULE_SECTIONS,
    "faction": FACTION_SECTIONS,
}


def sections_for(subject_type: SubjectType) -> list[SectionSpec]:
    """The bound sections of a subject type, in display order."""
    return sorted(SECTIONS_BY_TYPE.get(subject_type, []), key=lambda s: s.order)


def section_for(subject_type: SubjectType, section_key: str) -> SectionSpec | None:
    """The spec for one section, or None if the type has no such section.

    A `relationship:<id>` key resolves to the relationships section, since every
    such chain is one entry in that list.
    """
    if relationship_target(section_key) is not None:
        section_key = "relationships"
    return next(
        (s for s in SECTIONS_BY_TYPE.get(subject_type, []) if s.key == section_key), None
    )


def bound_field_for(subject_type: SubjectType, section_key: str) -> str | None:
    """The model attribute a section stands for, or None if it is free."""
    section = section_for(subject_type, section_key)
    return section.bound_field if section else None


__all__ = [
    "CHARACTER_SECTIONS",
    "STORY_SECTIONS",
    "STORY_SUBJECT_ID",
    "FACTION_SECTIONS",
    "LOCATION_SECTIONS",
    "RELATIONSHIP_PREFIX",
    "RULE_SECTIONS",
    "SECTIONS_BY_TYPE",
    "WORLD_SECTIONS",
    "bound_field_for",
    "relationship_section_key",
    "relationship_target",
    "section_for",
    "sections_for",
]
