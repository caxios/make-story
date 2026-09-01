"""The Phase 6 flagship run: ten episodes of the Wizarding World, for real.

    python scripts/run_wizarding_world.py --episodes 10 --out build/

Requires GOOGLE_API_KEY. This is the run a human reads: the automated test
proves the pipeline holds together, but only a reader can say whether Snape
stays cold and Hagrid keeps his dialect across ten chapters.

Each episode prints its cost breakdown, and the whole arc is exported to
Markdown, plain text and DOCX at the end.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from storyweaver import config, export, telemetry
from storyweaver.agents import episode_runner
from storyweaver.agents.checkpoint import CheckpointStore
from storyweaver.memory import MemoryManager
from storyweaver.ui.progress import GenerationProgress
from storyweaver.ui.project import Project, project_from_sample

DATASET = config.EXAMPLES_DIR / "wizarding_world.json"


def load_project(path: Path) -> Project:
    return project_from_sample(json.loads(path.read_text(encoding="utf-8")))


def _print_lore(reports: list[dict]) -> None:
    failures = [r for r in reports if not r["passed"]]
    if not failures:
        print("  Lore: clean on every scene.")
        return
    print(f"  Lore: {len(failures)} scene(s) needed a re-run.")
    for report in failures:
        for violation in report["violations"]:
            print(
                f"    scene {report['scene_number']} turn {violation['turn']} "
                f"[{violation['category']}] {violation['violated']}"
            )


def _print_threads(memory: MemoryManager, episode_number: int) -> None:
    active = memory.get_active_plot_threads()
    stale = {t.id for t in memory.get_stale_plot_threads(current_episode=episode_number)}
    print(f"  Open threads ({len(active)}):")
    for thread in active:
        mark = " [going cold]" if thread.id in stale else ""
        print(f"    - {thread.name}{mark}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=10, help="how many to generate")
    parser.add_argument("--start", type=int, default=1, help="first episode number")
    parser.add_argument("--max-turns", type=int, default=12, help="turn cap per scene")
    parser.add_argument("--language", default="en", help="output language")
    parser.add_argument("--out", type=Path, default=Path("build"), help="where to write exports")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--no-memory", action="store_true", help="run without continuity, for comparison"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not config.GOOGLE_API_KEY:
        print("GOOGLE_API_KEY is not set. Put it in .env and try again.", file=sys.stderr)
        return 1

    project = load_project(args.dataset)
    project.style = project.style.model_copy(update={"language": args.language})

    memory = None
    if not args.no_memory:
        memory = MemoryManager()
        memory.seed_world(project.world)

    checkpoints = CheckpointStore()
    wanted = [
        e for e in project.episodes
        if args.start <= e.episode_number < args.start + args.episodes
    ]

    print(f"{project.name}: {len(project.characters)} characters, "
          f"{len(project.world.rules)} rules, {len(wanted)} episodes to write.\n")

    started = time.perf_counter()
    with telemetry.record_usage("whole arc") as arc_usage:
        for episode in wanted:
            print("=" * 70)
            print(f"Episode {episode.episode_number}: {episode.title}")
            print("=" * 70)

            progress = GenerationProgress(episode_number=episode.episode_number)

            with telemetry.record_usage(f"episode {episode.episode_number}") as usage:
                try:
                    done, state = episode_runner.run_episode(
                        episode,
                        project.world,
                        project.character_map(),
                        style=project.style,
                        max_turns_per_scene=args.max_turns,
                        memory=memory,
                        checkpoints=checkpoints,
                        on_event=lambda node, s: _show(progress, node, s),
                    )
                except Exception as error:  # noqa: BLE001 — reported, then we stop
                    print(f"\n  FAILED: {error}")
                    print("  The finished scenes are checkpointed; re-run to resume.")
                    return 1

            project.update_episode(done)
            print(f"\n  {len(done.scenes)} scenes, {len(done.final_text.split()):,} words.")
            _print_lore(state["lore_reports"])
            if memory is not None:
                _print_threads(memory, done.episode_number)
            print()
            print(usage.report())
            print()
            # Fold this episode's calls into the arc total.
            for record in usage.records:
                arc_usage.add(record)

    elapsed = time.perf_counter() - started
    completed = project.completed_episodes()

    print("=" * 70)
    print(arc_usage.report())
    print(f"\nWall clock: {elapsed / 60:.1f} minutes for {len(completed)} episodes.")
    if completed:
        print(f"Average per episode: {arc_usage.total_tokens // len(completed):,} tokens, "
              f"${arc_usage.cost() / len(completed):.3f}")

    args.out.mkdir(parents=True, exist_ok=True)
    story = export.assemble_story(
        project.name, completed, project.characters, project.world
    )
    (args.out / "wizarding_world.md").write_text(story, encoding="utf-8")
    (args.out / "wizarding_world.txt").write_text(
        "\n\n".join(export.to_text(e) for e in completed), encoding="utf-8"
    )
    (args.out / "wizarding_world.docx").write_bytes(
        export.story_to_docx(project.name, completed, project.characters, project.world)
    )
    print(f"\nExported to {args.out.resolve()}")
    return 0


def _show(progress: GenerationProgress, node: str, state: dict) -> None:
    for event in progress.update(node, state):
        print(f"  {event.render()}")


if __name__ == "__main__":
    raise SystemExit(main())
