"""Run a whole episode through the Phase 3 pipeline against the real model.

    python -m storyweaver.demo_episode
    python -m storyweaver.demo_episode --language en --density lush --words 1200
    python -m storyweaver.demo_episode --out chapter.md

With memory on, run a serial: episode 2 is written knowing what episode 1
established, and both are persisted under data/.

    python -m storyweaver.demo_episode --memory
    python -m storyweaver.demo_episode --memory --episode 2 \
        --storyline "Ron's wand snaps during Charms and Harry keeps his promise."

Requires GOOGLE_API_KEY. Prints the finished chapter, then the Lore Checker's
report for every scene and attempt.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from storyweaver.agents import episode_runner
from storyweaver.demo_scene import load_sample
from storyweaver.memory import MemoryManager
from storyweaver.models import WritingStyle


def _print_lore_report(reports: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("Lore Checker report")
    print("=" * 60)
    for report in reports:
        status = "passed" if report["passed"] else "FAILED"
        print(f"  Scene {report['scene_number']}, attempt {report['attempt']}: {status}")
        for violation in report["violations"]:
            print(f"    - turn {violation['turn']} [{violation['category']}]")
            print(f"      violated: {violation['violated']}")
            print(f"      fix:      {violation['suggested_fix']}")


def _print_memory_state(memory: MemoryManager) -> None:
    print("\n" + "=" * 60)
    print("Memory after this episode")
    print("=" * 60)
    threads = memory.get_active_plot_threads()
    print(f"  Active plot threads ({len(threads)}):")
    for thread in threads:
        print(f"    - {thread.summary_line()}")
    stale = memory.get_stale_plot_threads()
    if stale:
        print(f"  Going cold ({len(stale)}):")
        for thread in stale:
            print(f"    - {thread.name}")
    for character_id in sorted(memory.structured_store.known_character_ids()):
        state = memory.get_character_state(character_id)
        print(f"  {character_id}: {state.internal_state or '(no state)'}")
        for goal in state.current_goals:
            print(f"      goal: {goal}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="ko", help="output language (default: ko)")
    parser.add_argument(
        "--density", default="moderate", choices=["sparse", "moderate", "lush"]
    )
    parser.add_argument("--words", type=int, default=1500, help="target words per scene")
    parser.add_argument(
        "--perspective",
        default="third_person_limited",
        choices=["third_person_limited", "third_person_omniscient", "first_person"],
    )
    parser.add_argument("--max-turns", type=int, default=12, help="turn cap per scene")
    parser.add_argument("--notes", default="", help="author style notes for the Writer")
    parser.add_argument("--out", type=Path, help="also write the chapter to this file")
    parser.add_argument("--quiet", action="store_true", help="hide pipeline progress")
    parser.add_argument(
        "--memory", action="store_true",
        help="persist to and read from data/ so episodes build on each other",
    )
    parser.add_argument("--episode", type=int, help="episode number (default: the sample's)")
    parser.add_argument("--storyline", help="override the sample episode's storyline")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    world, characters, episode = load_sample()

    memory = None
    if args.memory:
        memory = MemoryManager()
        memory.seed_world(world)

    updates = {"title": ""}  # drop the sample title so auto-titling is exercised
    if args.episode is not None:
        updates["episode_number"] = args.episode
    if args.storyline:
        updates["author_storyline"] = args.storyline
    episode = episode.model_copy(update=updates)

    style = WritingStyle(
        perspective=args.perspective,
        prose_density=args.density,
        target_word_count_per_scene=args.words,
        language=args.language,
        author_style_notes=args.notes,
    )

    done, state = episode_runner.run_episode(
        episode,
        world,
        characters,
        style=style,
        max_turns_per_scene=args.max_turns,
        memory=memory,
    )

    print("\n" + done.final_text)
    _print_lore_report(state["lore_reports"])
    if memory is not None:
        _print_memory_state(memory)
    print(f"\n{len(done.scenes)} scenes, {len(done.final_text.split())} words.")

    if args.out:
        args.out.write_text(done.final_text, encoding="utf-8")
        print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
