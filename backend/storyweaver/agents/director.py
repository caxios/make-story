"""Director Agent — decomposes an author's episode storyline into ordered scenes."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from storyweaver.agents import context
from storyweaver.agents.flow import flow_block
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.agents.settings_extract import NewCharacter, NewPlace
from storyweaver.models import CharacterProfile, Episode, Location, Scene, StoryBeat, WorldLore

logger = logging.getLogger(__name__)

# Three to four well-developed scenes is what a Korean web-novel 회차 carries at
# 4,500–5,500 characters. Five scenes at that length overruns; two under-runs.
DEFAULT_MIN_SCENES = 3
DEFAULT_MAX_SCENES = 4
NO_STORY_BRIEF = "(아직 정해진 전체 구상이 없습니다 — 이 화의 줄거리만 보고 구성하세요)"
NO_MEMORY = "(this is the first episode — nothing has been established yet)"

# Planning an episode for the author, the Director may bring in someone or
# somewhere new: everything a plan establishes is registered in the workshop,
# the world builder and the wiki. Inside a generation run there is no one to
# register them for, so there it keeps to what exists.
MAY_ADD = """- Use the character ids and location ids listed below, exactly as spelled.
- You MAY bring in a new character or a new location when the storyline names
  one that is not listed, or when one would make the episode better. Declare
  each in `new_characters` / `new_locations` with a short lowercase id (letters,
  digits and hyphens) and what they are — name, role, and what the story needs
  known about them — then use that id in the scenes like any other. Do not
  declare anyone who is already listed, under any spelling."""
KEEP_TO_LIST = """- Use ONLY the character ids and location ids listed below, exactly as spelled.
  If no listed location fits, leave the location empty rather than inventing one."""


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


class DirectorNewcomer(NewCharacter):
    id: str = Field(description="Short lowercase id used for them in the scenes")


class DirectorNewPlace(NewPlace):
    id: str = Field(description="Short lowercase id used for it in the scenes")


class DirectorOutput(BaseModel):
    """Structured-output envelope for the Director's scene list."""

    scenes: list[DraftScene]
    new_characters: list[DirectorNewcomer] = Field(default_factory=list)
    new_locations: list[DirectorNewPlace] = Field(default_factory=list)


@dataclass
class DirectorPlan:
    """Scenes, plus anyone and anywhere new they use — not registered yet."""

    scenes: list[Scene]
    new_characters: list[DirectorNewcomer] = field(default_factory=list)
    new_locations: list[DirectorNewPlace] = field(default_factory=list)


def build_prompt(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    min_scenes: int = DEFAULT_MIN_SCENES,
    max_scenes: int = DEFAULT_MAX_SCENES,
    memory_context: str = "",
    story_brief: str = "",
    story_flow: str = "",
    allow_new: bool = False,
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
        # The whole summary rather than the overview alone: factions and the
        # world facts outlines have added live there.
        world_overview=context.format_world_summary(world),
        world_rules=context.format_rules(world.rules),
        locations=context.format_locations(world.locations),
        # The full planning view — role, secrets, background, relationships by
        # name. A one-line blurb is enough to cast a scene, not to plot one.
        characters=context.format_cast_for_planning(char_map.values()),
        author_storyline=episode.author_storyline,
        # Where the whole work is going. The planning stages get this; the
        # Character Agent, the Writer and the Lore Checker must not — a
        # character who has read the ending stops being surprised by it.
        story_brief=story_brief or NO_STORY_BRIEF,
        story_flow=flow_block(story_flow),
        new_elements=MAY_ADD if allow_new else KEEP_TO_LIST,
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


def plan_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    min_scenes: int = DEFAULT_MIN_SCENES,
    max_scenes: int = DEFAULT_MAX_SCENES,
    memory_context: str = "",
    story_brief: str = "",
    story_flow: str = "",
) -> DirectorPlan:
    """Plan an episode for the author, newcomers allowed.

    Scenes may use a newcomer's id: they are checked against the cast *with*
    the newcomers, and the caller registers them before saving the plan.
    """
    char_map = dict(context.as_character_map(characters))
    if not char_map:
        raise ValueError("plan_episode needs at least one character profile")

    prompt = build_prompt(
        episode, world, char_map, min_scenes, max_scenes, memory_context, story_brief,
        story_flow, allow_new=True,
    )
    model = telemetry.meter(llm or get_llm(stage="director"), "director")
    output = model.with_structured_output(DirectorOutput).invoke(prompt)

    newcomers = [n for n in output.new_characters if n.id.strip() and n.name.strip()
                 and n.id not in char_map]
    for newcomer in newcomers:
        char_map[newcomer.id] = CharacterProfile(
            id=newcomer.id, name=newcomer.name,
            appearance="", personality_summary="", speech_style="",
        )
    known_places = {place.id for place in world.locations}
    places = [p for p in output.new_locations if p.id.strip() and p.name.strip()
              and p.id not in known_places]
    widened = world.model_copy(update={"locations": [
        *world.locations,
        *(Location(id=p.id, name=p.name, description=p.description) for p in places),
    ]})
    return DirectorPlan(
        scenes=_to_scenes(output.scenes, widened, char_map),
        new_characters=newcomers,
        new_locations=places,
    )


def decompose_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    min_scenes: int = DEFAULT_MIN_SCENES,
    max_scenes: int = DEFAULT_MAX_SCENES,
    memory_context: str = "",
    story_brief: str = "",
    story_flow: str = "",
) -> list[Scene]:
    """Break `episode.author_storyline` into ordered, validated `Scene`s."""
    char_map = context.as_character_map(characters)
    if not char_map:
        raise ValueError("decompose_episode needs at least one character profile")

    prompt = build_prompt(
        episode, world, char_map, min_scenes, max_scenes, memory_context, story_brief,
        story_flow,
    )
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
