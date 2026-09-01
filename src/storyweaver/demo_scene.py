"""Run the Phase 2 pipeline against the sample story, using the real model.

    python -m storyweaver.demo_scene            # direct the episode, then play scene 1
    python -m storyweaver.demo_scene --two      # a fixed 2-character scene
    python -m storyweaver.demo_scene --three    # a fixed 3-character scene

Requires GOOGLE_API_KEY. Everything here is a thin wrapper over the agents —
the module exists so the scene simulation can be eyeballed end to end.
"""

from __future__ import annotations

import argparse
import json
import logging

from storyweaver.agents import director, scene_runner
from storyweaver.config import EXAMPLES_DIR
from storyweaver.models import CharacterProfile, Episode, Scene, StoryBeat, WorldLore

SAMPLE_PATH = EXAMPLES_DIR / "harry_potter_sample.json"


def load_sample() -> tuple[WorldLore, dict[str, CharacterProfile], Episode]:
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    world = WorldLore.model_validate(raw["world"])
    characters = {
        c["id"]: CharacterProfile.model_validate(c) for c in raw["characters"]
    }
    episode = Episode.model_validate(raw["episodes"][0])
    return world, characters, episode


def two_character_scene() -> Scene:
    return Scene(
        scene_number=1,
        title="A Compartment on the Hogwarts Express",
        participating_character_ids=["harry-potter", "ron-weasley"],
        objective="Harry and Ron meet and begin an unlikely friendship.",
        beats=[
            StoryBeat(description="Ron asks to share the compartment.", mood="awkward"),
            StoryBeat(description="Harry asks about the wizarding world he knows nothing about."),
        ],
    )


def three_character_scene() -> Scene:
    return Scene(
        scene_number=1,
        title="The Great Hall",
        location_id="great-hall",
        participating_character_ids=["harry-potter", "ron-weasley", "hermione-granger"],
        objective="The three size each other up for the first time, before the Sorting.",
        beats=[StoryBeat(description="Hermione corrects Ron and he bristles.", mood="prickly")],
    )


def _print_scene(
    scene: Scene,
    world: WorldLore,
    characters: dict[str, CharacterProfile],
    max_turns: int,
) -> None:
    print(f"\n=== Scene {scene.scene_number}: {scene.title} ===")
    print(f"Objective: {scene.objective}\n")

    played, entries = scene_runner.run_scene(scene, world, characters, max_turns=max_turns)
    for entry in entries:
        speaker = characters[entry.character_id].name
        target = f" (to {characters[entry.directed_at].name})" if entry.directed_at else ""
        print(f"{entry.turn:>3}. {speaker}{target} [{entry.type}]\n     {entry.content}\n")
    print(f"({len(played.interaction_log)} turns)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--two", action="store_true", help="run the 2-character scene")
    parser.add_argument("--three", action="store_true", help="run the 3-character scene")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--verbose", action="store_true", help="show agent warnings")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    world, characters, episode = load_sample()

    if args.two or args.three:
        if args.two:
            _print_scene(two_character_scene(), world, characters, args.max_turns)
        if args.three:
            _print_scene(three_character_scene(), world, characters, args.max_turns)
        return

    print("Directing episode 1 ...")
    directed = director.direct_episode(episode, world, characters)
    for scene in directed.scenes:
        cast = ", ".join(scene.participating_character_ids)
        print(f"  {scene.scene_number}. {scene.title} — {cast}")
    _print_scene(directed.scenes[0], world, characters, args.max_turns)


if __name__ == "__main__":
    main()
