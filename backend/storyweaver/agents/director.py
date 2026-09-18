"""Director Agent — decomposes an author's episode storyline into ordered scenes."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, Field

from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, Episode, Scene, StoryBeat, WorldLore

logger = logging.getLogger(__name__)

# Three to four well-developed scenes is what a Korean web-novel 회차 carries at
# 4,500–5,500 characters. Five scenes at that length overruns; two under-runs.
DEFAULT_MIN_SCENES = 3
DEFAULT_MAX_SCENES = 4
NO_MEMORY = "(this is the first episode — nothing has been established yet)"


class DraftScene(BaseModel):
    """A scene as proposed by the Director.

    Deliberately narrower than `Scene`: the fields the simulation and the writer
    fill in later (`scene_number`, `interaction_log`, `prose`) are not the
    model's to invent.
    """

    title: str
    objective: str = Field(description="What this scene must accomplish narratively")
    participating_character_ids: list[str] = Field(
        description="Character ids present, ordered by who drives the scene"
    )
    location_id: str | None = Field(
        default=None, description="Id of a location from the world, or null"
    )
    beats: list[StoryBeat] = Field(default_factory=list)
    mood: str | None = None


class DirectorOutput(BaseModel):
    """Structured-output envelope for the Director's scene list."""

    scenes: list[DraftScene]


def build_prompt(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    min_scenes: int = DEFAULT_MIN_SCENES,
    max_scenes: int = DEFAULT_MAX_SCENES,
    memory_context: str = "",
) -> str:
    """Render the Director prompt. Exposed separately so it can be inspected and tested."""
    char_map = context.as_character_map(characters)
    return render_prompt(
        "director",
        memory_context=memory_context or NO_MEMORY,
        min_scenes=min_scenes,
        max_scenes=max_scenes,
        world_title=world.title,
        world_genre=world.genre,
        world_tone=world.tone,
        world_era=world.era or "unspecified",
        world_overview=world.overview,
        world_rules=context.format_rules(world.rules),
        locations=context.format_locations(world.locations),
        characters=context.format_character_summaries(list(char_map.values())),
        author_storyline=episode.author_storyline,
    )


def _to_scenes(
    drafts: Iterable[DraftScene],
    world: WorldLore,
    char_map: Mapping[str, CharacterProfile],
) -> list[Scene]:
    """Number the drafts and drop ids the model invented.

    Models hallucinate ids; every downstream agent looks characters and
    locations up by id, so an unknown one is silently dropped here rather than
    left to raise a KeyError deep inside a simulation.
    """
    known_locations = {loc.id for loc in world.locations}
    scenes: list[Scene] = []

    for position, draft in enumerate(drafts, start=1):
        participants = [cid for cid in draft.participating_character_ids if cid in char_map]
        unknown = set(draft.participating_character_ids) - set(participants)
        if unknown:
            logger.warning("Draft %d: dropping unknown character ids %s", position, sorted(unknown))
        if not participants:
            logger.warning("Draft %d (%r) has no known characters; skipping", position, draft.title)
            continue

        location_id = draft.location_id
        if location_id is not None and location_id not in known_locations:
            logger.warning("Draft %d: unknown location %r; leaving unset", position, location_id)
            location_id = None

        beats = []
        for beat in draft.beats:
            beats.append(
                beat.model_copy(
                    update={
                        "involved_character_ids": [
                            cid for cid in beat.involved_character_ids if cid in char_map
                        ],
                        "location_id": beat.location_id if beat.location_id in known_locations else None,
                        "mood": beat.mood or draft.mood,
                    }
                )
            )

        # Number by position among the *kept* scenes so a dropped draft does
        # not leave a gap in the episode's scene numbering.
        scenes.append(
            Scene(
                scene_number=len(scenes) + 1,
                title=draft.title,
                location_id=location_id,
                participating_character_ids=participants,
                objective=draft.objective,
                beats=beats,
            )
        )

    return scenes


def decompose_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    min_scenes: int = DEFAULT_MIN_SCENES,
    max_scenes: int = DEFAULT_MAX_SCENES,
    memory_context: str = "",
) -> list[Scene]:
    """Break `episode.author_storyline` into ordered, validated `Scene`s."""
    char_map = context.as_character_map(characters)
    if not char_map:
        raise ValueError("decompose_episode needs at least one character profile")

    prompt = build_prompt(episode, world, char_map, min_scenes, max_scenes, memory_context)
    model = telemetry.meter(llm or get_llm(stage="director"), "director")
    output = model.with_structured_output(DirectorOutput).invoke(prompt)
    return _to_scenes(output.scenes, world, char_map)


def direct_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    **kwargs,
) -> Episode:
    """Return a copy of `episode` with `scenes` populated and status advanced."""
    scenes = decompose_episode(episode, world, characters, llm=llm, **kwargs)
    return episode.model_copy(update={"scenes": scenes, "status": "in_progress"})
