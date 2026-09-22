"""Episode Summarizer — decides what is worth remembering, and in what shape.

Everything the memory layer stores comes from here, so the granularity policy in
`prompts/episode_summarizer.md` is what keeps a fifty-episode serial from
either forgetting the trapdoor or drowning in transcripts of people eating toast.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.memory.plot_tracker import PlotThread
from storyweaver.models import (
    CharacterProfile,
    Episode,
    EntryKind,
    InteractionRecord,
    Relationship,
    SubjectType,
    WorldLore,
)

logger = logging.getLogger(__name__)

ThreadAction = Literal["open", "progress", "resolve"]

# How much of each scene the summarizer sees. Prose is the truth of what
# happened, but a whole episode of it will not fit alongside everything else.
SCENE_PROSE_CHARS = 4000


class ThreadUpdate(BaseModel):
    """One plot thread this episode opened, advanced, or paid off."""

    id: str = Field(description="snake_case thread id, reused if the thread already exists")
    action: ThreadAction
    name: str = ""
    description: str = ""
    event: str = Field(default="", description="What happened to the thread this episode")
    resolution: str = ""
    linked_characters: list[str] = Field(default_factory=list)


class CharacterStateUpdate(BaseModel):
    """Where a character stands at the end of the episode."""

    character_id: str
    internal_state: str = Field(default="", description="Emotional/mental state now")
    current_goals: list[str] = Field(default_factory=list)
    relationship_updates: list[Relationship] = Field(
        default_factory=list, description="Only relationships that actually changed"
    )


class FieldChange(BaseModel):
    """One setting the episode moved, and what in the episode moved it.

    This is what the old `character_updates` could not say. It carried a
    character's mood, goals and relationships and nothing else, so an episode
    that cut someone's hair or destroyed a landmark had nowhere to record it —
    and the next episode grew the hair back.
    """

    subject_type: SubjectType = Field(
        default="character", description="character, world, location, rule or faction"
    )
    subject_id: str = Field(description="The id of whoever or whatever changed")
    section_key: str = Field(
        description="Which part of them changed: appearance, personality, speech, "
        "role, values, goals, backstory, secrets, state, statement, ..."
    )
    previous: str = Field(default="", description="What it was before this episode")
    value: str = Field(description="What it is now")
    reason: str = Field(
        default="",
        description="The moment in THIS episode that caused it. Required: a change "
        "you cannot point at is a guess, and it will be discarded.",
    )
    kind: EntryKind = Field(
        default="changed",
        description="changed, revealed (true all along, only now told), "
        "added, removed (destroyed/abolished) or restored (repaired)",
    )


class Deed(BaseModel):
    """What one character did in this episode.

    Separate from a change on purpose: an episode where nothing about a
    character moved is still an episode they acted in, and the author asked for
    both.
    """

    character_id: str
    summary: str = Field(description="One or two sentences, past tense, plainly told")


class EpisodeMemory(BaseModel):
    """Everything the memory layer takes from one finished episode."""

    summary: str = Field(description="300-500 words, written for future reference")
    key_events: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    mood: str = ""
    interactions: list[InteractionRecord] = Field(default_factory=list)
    thread_updates: list[ThreadUpdate] = Field(default_factory=list)
    character_updates: list[CharacterStateUpdate] = Field(default_factory=list)
    world_lore_updates: list[str] = Field(default_factory=list)
    # What the chronicle is made of: settings that moved, and what everyone did.
    changes: list[FieldChange] = Field(default_factory=list)
    deeds: list[Deed] = Field(default_factory=list)

    def characters_involved(self) -> list[str]:
        """Every character id this episode's memory touches, deduplicated."""
        ids = {u.character_id for u in self.character_updates}
        for interaction in self.interactions:
            ids.update(interaction.participants)
        return sorted(ids)


def _scene_digest(episode: Episode) -> str:
    """The episode as the summarizer should read it: prose where we have it."""
    blocks = []
    for scene in episode.scenes:
        header = f"### Scene {scene.scene_number}: {scene.title}"
        body = scene.prose[:SCENE_PROSE_CHARS] if scene.prose else "\n".join(scene.interaction_log)
        blocks.append(f"{header}\nObjective: {scene.objective}\n\n{body or '(empty)'}")
    if blocks:
        return "## The Scenes\n\n" + "\n\n".join(blocks)
    return "## The Episode Text\n\n" + (episode.final_text or "(empty)")


def build_prompt(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    open_threads: Sequence[PlotThread] = (),
    language: str = "ko",
) -> str:
    """Render the summarizer prompt for a completed episode."""
    return render_prompt(
        "episode_summarizer",
        episode_number=episode.episode_number,
        episode_title=episode.title or "(untitled)",
        author_storyline=episode.author_storyline,
        world_summary=context.format_world_summary(world),
        character_summaries=context.format_character_summaries(list(characters.values())),
        open_threads=context.format_bullets(t.summary_line() for t in open_threads)
        if open_threads
        else "(none yet)",
        scene_digest=_scene_digest(episode),
        language=language,
    )


def _sanitise(
    memory: EpisodeMemory, episode: Episode, known_characters: Mapping[str, CharacterProfile]
) -> EpisodeMemory:
    """Drop invented character ids and stamp the episode number onto records.

    Records are keyed and filtered by these ids for the rest of the story's
    life, so a hallucinated one is a memory nobody can ever retrieve.
    """
    known = set(known_characters)

    interactions = []
    for record in memory.interactions:
        participants = [p for p in record.participants if p in known]
        if not participants:
            logger.warning("Dropping interaction record with no known participants: %s",
                           record.summary[:60])
            continue
        interactions.append(
            record.model_copy(
                update={
                    "episode_number": episode.episode_number,
                    "participants": participants,
                    "emotional_impact": {
                        k: v for k, v in record.emotional_impact.items() if k in known
                    },
                }
            )
        )

    updates = []
    for update in memory.character_updates:
        if update.character_id not in known:
            logger.warning("Dropping state update for unknown character %r", update.character_id)
            continue
        updates.append(
            update.model_copy(
                update={
                    "relationship_updates": [
                        r for r in update.relationship_updates
                        if r.target_character_id in known
                    ]
                }
            )
        )

    threads = [
        t.model_copy(
            update={"linked_characters": [c for c in t.linked_characters if c in known]}
        )
        for t in memory.thread_updates
        if t.id.strip()
    ]

    changes = [c for c in memory.changes if _is_justified(c, known)]
    deeds = [
        d for d in memory.deeds if d.character_id in known and d.summary.strip()
    ]

    return memory.model_copy(
        update={
            "interactions": interactions,
            "character_updates": updates,
            "thread_updates": threads,
            "changes": changes,
            "deeds": deeds,
        }
    )


def _is_justified(change: FieldChange, known: set[str]) -> bool:
    """Whether a reported change has earned its place in the chronicle.

    The chronicle wins over the author's original setting, so an unfounded
    change does not merely sit in a log — it becomes what the next episode is
    told this character is. A prickly character may soften across chapters of
    being worn down; what is not allowed is a character who changes with
    nothing in the text behind it.

    The reason is therefore the gate, not a decoration. A change is dropped
    rather than failing the whole episode's memory: losing one line is much
    cheaper than losing the record of a chapter that has already been paid for.
    """
    if not change.value.strip():
        logger.warning("Dropping an empty change to %s.%s",
                       change.subject_id, change.section_key)
        return False
    if not change.reason.strip():
        logger.warning(
            "Dropping an unjustified change to %s.%s (%r): the summarizer named no "
            "cause in the episode",
            change.subject_id, change.section_key, change.value[:60],
        )
        return False
    if change.subject_type == "character" and change.subject_id not in known:
        logger.warning("Dropping a change to unknown character %r", change.subject_id)
        return False
    return True


def summarize_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile],
    open_threads: Sequence[PlotThread] = (),
    language: str = "ko",
    llm=None,
) -> EpisodeMemory:
    """Extract the memory record for a finished episode."""
    if not episode.scenes and not episode.final_text.strip():
        raise ValueError(
            f"Episode {episode.episode_number} has no scenes or text to summarize"
        )

    prompt = build_prompt(episode, world, characters, open_threads, language)
    model = telemetry.meter(llm or get_llm(stage="summarizer"), "summarizer")
    memory: EpisodeMemory = model.with_structured_output(EpisodeMemory).invoke(prompt)

    return _sanitise(memory, episode, characters)
