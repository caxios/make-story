"""The map from wiki sections to the fields they stand for.

The registry is code rather than configuration for one reason: a section whose
`bound_field` no longer exists orphans its whole chain, and it does so quietly —
an orphaned chain folds to nothing and the model's own value wins again, with
no error anywhere. The first test here is what turns that silence into a
failing build.
"""

from __future__ import annotations

import pytest

from storyweaver.models import CharacterProfile, Location, Rule, WorldLore
from storyweaver.wiki import sections as registry
from storyweaver.wiki import (
    bound_field_for,
    relationship_section_key,
    relationship_target,
    section_for,
    sections_for,
)

MODELS = {
    "character": CharacterProfile,
    "world": WorldLore,
    "location": Location,
    "rule": Rule,
}


@pytest.mark.parametrize("subject_type", sorted(MODELS))
def test_every_bound_section_names_a_field_that_exists(subject_type):
    """Rename a model field without this table and the chain is orphaned."""
    model = MODELS[subject_type]
    for section in sections_for(subject_type):
        if section.bound_field is None:
            continue
        assert section.bound_field in model.model_fields, (
            f"{subject_type}.{section.key} is bound to "
            f"{section.bound_field!r}, which {model.__name__} does not have"
        )


def test_factions_are_declared_but_not_yet_bound():
    """`WorldLore.factions` is still a list of bare names, so there is no field."""
    for section in sections_for("faction"):
        assert section.bound_field is None


def test_every_subject_type_has_sections():
    for subject_type in ("character", "world", "location", "rule", "faction"):
        assert sections_for(subject_type), f"{subject_type} has no sections"


def test_section_keys_are_unique_within_a_type():
    for subject_type, specs in registry.SECTIONS_BY_TYPE.items():
        keys = [s.key for s in specs]
        assert len(keys) == len(set(keys)), f"{subject_type} repeats a section key"


def test_sections_come_back_in_display_order():
    orders = [s.order for s in sections_for("character")]

    assert orders == sorted(orders)


def test_a_character_has_somewhere_to_record_what_they_did():
    """The author asked for changes *and* deeds; these are different shapes."""
    deeds = section_for("character", "deeds")

    assert deeds is not None
    assert deeds.kind == "log"
    assert deeds.bound_field is None


def test_stateful_and_log_sections_both_exist():
    kinds = {s.kind for s in sections_for("character")}

    assert kinds == {"stateful", "log"}


def test_a_place_can_record_its_condition():
    """유적이 파괴됨, 게이트가 고장남 — `description` is prose, not state."""
    assert bound_field_for("location", "state") == "status"


def test_a_rule_can_be_abolished():
    assert bound_field_for("rule", "active") == "active"


# ==========================================================================
# Relationships
# ==========================================================================


def test_each_relationship_gets_its_own_section_key():
    assert relationship_section_key("시월") != relationship_section_key("한병호")


def test_a_relationship_key_resolves_to_the_relationships_section():
    """Every such chain is one member of that list, so it shares the spec."""
    spec = section_for("character", relationship_section_key("시월"))

    assert spec is not None
    assert spec.key == "relationships"
    assert spec.bound_field == "relationships"


def test_the_other_character_can_be_read_back_out_of_the_key():
    key = relationship_section_key("구미호-시월")

    assert relationship_target(key) == "구미호-시월"


def test_an_ordinary_section_is_not_a_relationship():
    assert relationship_target("appearance") is None


def test_an_empty_relationship_key_is_not_a_relationship():
    assert relationship_target("relationship:") is None


# ==========================================================================
# Lookups that should not explode
# ==========================================================================


def test_an_unknown_section_is_none_rather_than_an_error():
    assert section_for("character", "그런-것-없음") is None
    assert bound_field_for("character", "그런-것-없음") is None


def test_an_unknown_subject_type_has_no_sections():
    assert sections_for("이런-종류-없음") == []  # type: ignore[arg-type]
