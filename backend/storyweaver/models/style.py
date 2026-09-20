"""Author-facing writing style configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field

PERSPECTIVES = {
    "third_person_limited": (
        "third-person limited — stay inside one character's head, and never report "
        "what another character thinks or feels except as this character perceives it"
    ),
    "third_person_omniscient": (
        "third-person omniscient — the narrator may move between characters' inner lives"
    ),
    "first_person": (
        "first person — the point-of-view character narrates in their own voice"
    ),
}

PROSE_DENSITIES = {
    "sparse": "Lean and quick. Short sentences, minimal description, whitespace between beats.",
    "moderate": "Balanced. Description where it earns its place, dialogue that moves.",
    "lush": "Rich and textured. Layered imagery, longer rhythms, lingering sensory detail.",
}


TENSES = {
    "past": "past tense — the standard for narrative fiction",
    "present": (
        "present tense — immediate and close; keep it consistent, and never "
        "slip back into the past except for genuine flashback"
    ),
}


PACING = {
    "slow": (
        "Slow and introspective. Let moments breathe; favour interiority and sensory "
        "detail over event. Longer paragraphs, fewer hard cuts."
    ),
    "normal": "Even. Move when the scene moves, linger when it earns lingering.",
    "fast": (
        "Fast and action-heavy. Short sentences, hard cuts, verbs doing the work. "
        "Cut description to what the moment needs to stay legible."
    ),
}


def describe_tense(tense: str) -> str:
    """The tense as an instruction, falling back to the raw value."""
    return TENSES.get(tense, tense)


def describe_pacing(pacing: str) -> str:
    """Pacing as an instruction, falling back to the raw value."""
    return PACING.get(pacing, pacing)


# ---------------------------------------------------------------------------
# Creativity: how much latitude the prose has, per episode
#
# Two things move together here, and both matter. The instruction tells the
# model how far it may go; the temperature decides how far it actually goes.
# Setting one without the other produces a model that is told to be daring and
# samples timidly, or told to be plain and reaches for a metaphor anyway.
# ---------------------------------------------------------------------------

DEFAULT_CREATIVITY = 0.5

# What each end of the dial asks for, in the Writer's own terms.
CREATIVITY_LEVELS: list[tuple[float, str]] = [
    (
        0.2,
        "Restrained. Plain, concrete sentences; say what happens and little "
        "more. No extended metaphor, no flourishes, no invented detail beyond "
        "what the log and the world already establish. When in doubt, cut.",
    ),
    (
        0.4,
        "Measured. Clear prose with description where the scene needs it. "
        "Imagery is allowed but should stay close to the literal.",
    ),
    (
        0.6,
        "Balanced. Write it as a working novelist would: sensory detail, "
        "figurative language where it earns its place, a voice of its own — "
        "without reaching for effect.",
    ),
    (
        0.8,
        "Expressive. Lean into voice, rhythm and imagery. Invent the texture "
        "of the moment freely — how the light falls, what the silence sounds "
        "like — as long as every event in the log still happens.",
    ),
    (
        1.0,
        "Unrestrained. Take real risks with language: unusual images, unusual "
        "sentence shapes, the surprising word over the expected one. Nothing "
        "in the log or the world rules may change, but everything in how it is "
        "told is yours.",
    ),
]

# The sampling temperature at each end. Below 0.5 the prose turns wooden and
# repetitive; above 1.1 it starts losing the thread of the scene.
MIN_TEMPERATURE = 0.5
MAX_TEMPERATURE = 1.1


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def describe_creativity(creativity: float | None) -> str:
    """The latitude instruction for this level, as the Writer is told it."""
    level = _clamp(DEFAULT_CREATIVITY if creativity is None else creativity)
    for threshold, description in CREATIVITY_LEVELS:
        if level <= threshold:
            return description
    return CREATIVITY_LEVELS[-1][1]


def temperature_for(creativity: float | None) -> float:
    """The sampling temperature that matches that instruction."""
    level = _clamp(DEFAULT_CREATIVITY if creativity is None else creativity)
    span = MAX_TEMPERATURE - MIN_TEMPERATURE
    return round(MIN_TEMPERATURE + span * level, 2)


class WritingStyle(BaseModel):
    """Global prose preferences the author sets once for the whole story."""

    perspective: str = "third_person_limited"   # or "first_person", "third_person_omniscient"
    pov_character_id: str | None = None         # for limited / first-person perspective
    tense: str = "past"                         # "past" or "present"
    prose_density: str = "moderate"             # "sparse", "moderate", "lush"
    dialogue_ratio: float = Field(default=0.4, ge=0.0, le=1.0)  # rough dialogue-to-narration target
    # Per scene. The unit follows `language`: for Korean (and other languages
    # counted by character) this is 자, 공백 포함; for English it is words. The
    # default of 1,400 자 across 3–4 scenes lands a 회차 at the Korean
    # web-novel standard of 4,500–5,500 자.
    #
    # The field keeps its old name so existing `project.json` files load
    # unchanged; `describe_target_length()` is what agents should ask.
    target_word_count_per_scene: int = Field(default=1400, gt=0)
    language: str = "ko"                        # output language
    author_style_notes: str = ""                # e.g. "Write like Brandon Sanderson"

    def describe_perspective(self) -> str:
        """The perspective as an instruction, falling back to the raw value."""
        return PERSPECTIVES.get(self.perspective, self.perspective)

    def describe_density(self) -> str:
        return PROSE_DENSITIES.get(self.prose_density, self.prose_density)

    def counts_characters(self) -> bool:
        """Whether this language is measured in characters rather than words.

        Korean, Japanese and Chinese publishing all count characters, and a
        model told to write "1,400 words" of Korean produces something three to
        four times longer than intended, because it reads that as 어절.
        """
        return self.language.strip().lower()[:2] in {"ko", "ja", "zh"} or (
            self.language.strip().lower()
            in {"korean", "japanese", "chinese", "한국어", "日本語", "中文"}
        )

    def describe_target_length(self) -> str:
        """The length instruction, in the unit this language is actually measured in."""
        target = self.target_word_count_per_scene
        # A band, not a point: a single number invites the model to stop dead on
        # it, and the low end is what matters.
        low = int(round(target * 0.9 / 50)) * 50
        high = int(round(target * 1.1 / 50)) * 50
        if not self.counts_characters():
            return f"{low:,}–{high:,} words"
        instruction = f"{low:,}–{high:,} characters, counting spaces"
        if self.language.strip().lower()[:2] == "ko" or "한국" in self.language:
            instruction += f" (공백 포함 {low:,}~{high:,}자)"
        return instruction

    def describe_tense(self) -> str:
        return describe_tense(self.tense)
