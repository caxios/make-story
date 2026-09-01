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


def describe_pacing(pacing: str) -> str:
    """Pacing as an instruction, falling back to the raw value."""
    return PACING.get(pacing, pacing)


class WritingStyle(BaseModel):
    """Global prose preferences the author sets once for the whole story."""

    perspective: str = "third_person_limited"   # or "first_person", "third_person_omniscient"
    pov_character_id: str | None = None         # for limited / first-person perspective
    prose_density: str = "moderate"             # "sparse", "moderate", "lush"
    dialogue_ratio: float = Field(default=0.4, ge=0.0, le=1.0)  # rough dialogue-to-narration target
    target_word_count_per_scene: int = Field(default=1500, gt=0)
    language: str = "ko"                        # output language
    author_style_notes: str = ""                # e.g. "Write like Brandon Sanderson"

    def describe_perspective(self) -> str:
        """The perspective as an instruction, falling back to the raw value."""
        return PERSPECTIVES.get(self.perspective, self.perspective)

    def describe_density(self) -> str:
        return PROSE_DENSITIES.get(self.prose_density, self.prose_density)
