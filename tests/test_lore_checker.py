"""The Lore Checker must catch real violations and produce actionable fixes."""

from __future__ import annotations

from storyweaver.agents import lore_checker
from storyweaver.agents.lore_checker import ValidationResult, Violation
from storyweaver.models import InteractionEntry


def _wandless_magic_log() -> list[InteractionEntry]:
    """Turn 2 breaks the world's rule that deliberate magic needs a wand."""
    return [
        InteractionEntry(turn=1, character_id="harry-potter", type="dialogue", content="Lend a hand?"),
        InteractionEntry(
            turn=2,
            character_id="ron-weasley",
            type="action",
            content="He waved a bare hand and the trunk floated neatly onto the rack.",
        ),
    ]


def test_prompt_carries_rules_characters_and_numbered_turns(
    sample_entries, world, characters, two_character_scene
):
    prompt = lore_checker.build_prompt(sample_entries, world, characters, two_character_scene)

    assert "wand" in prompt.lower()                    # world rules listed
    assert "Ron Weasley" in prompt                     # character constraints
    assert "hand-me-down" in prompt                    # ... including secrets
    assert "Turn 1 —" in prompt and "Turn 4 —" in prompt  # citable turn numbers
    assert two_character_scene.objective in prompt


def test_prompt_only_describes_characters_in_the_scene(
    sample_entries, world, characters, two_character_scene
):
    prompt = lore_checker.build_prompt(sample_entries, world, characters, two_character_scene)
    assert "Hermione" not in prompt


def test_clean_log_passes(sample_entries, world, characters, scripted_llm):
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(passed=True, violations=[])
    )

    result = lore_checker.check(sample_entries, world, characters, llm=llm)

    assert result.passed is True
    assert result.violations == []
    assert result.first_bad_turn is None
    assert result.constraints() == []


def test_world_rule_violation_is_reported_with_a_fix(world, characters, scripted_llm):
    entries = _wandless_magic_log()
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(
            passed=False,
            violations=[
                Violation(
                    turn=2,
                    category="world_rule",
                    violated="Deliberate spellcasting requires a wand.",
                    suggested_fix="Have Ron draw his wand before levitating the trunk.",
                    offending_content="He waved a bare hand",
                )
            ],
        )
    )

    result = lore_checker.check(entries, world, characters, llm=llm)

    assert result.passed is False
    assert result.first_bad_turn == 2
    constraint = result.constraints()[0]
    assert "draw his wand" in constraint
    assert "turn 2" in constraint
    assert "world rule" in constraint  # the category, humanised


def test_earliest_violation_drives_the_rerun_point(world, characters, scripted_llm):
    entries = _wandless_magic_log()
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(
            passed=False,
            violations=[
                Violation(turn=2, category="continuity", violated="b", suggested_fix="fix b"),
                Violation(turn=1, category="world_rule", violated="a", suggested_fix="fix a"),
            ],
        )
    )

    result = lore_checker.check(entries, world, characters, llm=llm)

    assert result.first_bad_turn == 1
    assert len(result.constraints()) == 2


def test_passed_flag_is_derived_from_the_violation_list(
    sample_entries, world, characters, scripted_llm
):
    """Models say `passed: true` next to a list of violations; the list wins."""
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(
            passed=True,
            violations=[
                Violation(turn=1, category="continuity", violated="x", suggested_fix="fix x")
            ],
        )
    )

    result = lore_checker.check(sample_entries, world, characters, llm=llm)

    assert result.passed is False


def test_failed_flag_with_no_violations_is_treated_as_a_pass(
    sample_entries, world, characters, scripted_llm
):
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(passed=False, violations=[])
    )

    assert lore_checker.check(sample_entries, world, characters, llm=llm).passed is True


def test_violations_citing_turns_outside_the_log_are_dropped(
    sample_entries, world, characters, scripted_llm
):
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(
            passed=False,
            violations=[
                Violation(turn=99, category="continuity", violated="x", suggested_fix="fix x"),
                Violation(turn=3, category="continuity", violated="y", suggested_fix="fix y"),
            ],
        )
    )

    result = lore_checker.check(sample_entries, world, characters, llm=llm)

    assert [v.turn for v in result.violations] == [3]


def test_a_log_of_only_hallucinated_turns_passes(
    sample_entries, world, characters, scripted_llm
):
    llm = scripted_llm(
        ValidationResult=lambda prompt, index: ValidationResult(
            passed=False,
            violations=[
                Violation(turn=99, category="continuity", violated="x", suggested_fix="fix x")
            ],
        )
    )

    result = lore_checker.check(sample_entries, world, characters, llm=llm)

    assert result.passed is True
    assert result.violations == []


def test_empty_log_passes_without_calling_the_model(world, characters, scripted_llm):
    llm = scripted_llm()  # any call would raise

    result = lore_checker.check([], world, characters, llm=llm)

    assert result.passed is True
    assert llm.calls == []
