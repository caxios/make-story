"""Turns pipeline node events into a checklist the author can watch.

`episode_runner.stream_episode` reports which node just ran and the state it
left. This translates that into "Writing scene 2/4… done (1,423 words)", and
keeps the running checklist that the Episode Queue page renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PENDING = "⬜"
RUNNING = "🔄"
DONE = "✅"
WARNED = "⚠️"


class Stage(str, Enum):
    """The pipeline stages an author cares about, in the order they happen."""

    PLANNING = "planning"
    SIMULATING = "simulating"
    CHECKING = "checking"
    WRITING = "writing"
    ASSEMBLING = "assembling"
    RECORDING = "recording"


NODE_STAGES = {
    "director_plan_scenes": Stage.PLANNING,
    "simulate_scene": Stage.SIMULATING,
    "check_lore": Stage.CHECKING,
    "rerun_scene": Stage.SIMULATING,
    "write_scene": Stage.WRITING,
    "assemble_episode": Stage.ASSEMBLING,
    # `advance_scene` is bookkeeping; it gets no line of its own.
}


@dataclass(frozen=True)
class ProgressEvent:
    """One thing that finished, phrased for a human."""

    stage: Stage
    text: str
    scene_number: int | None = None
    warning: bool = False

    @property
    def icon(self) -> str:
        return WARNED if self.warning else DONE

    def render(self) -> str:
        return f"{self.icon} {self.text}"


@dataclass
class GenerationProgress:
    """Accumulates events for one episode generation.

    Node updates alone are not a progress bar: `check_lore` runs several times
    per scene, `rerun_scene` may not run at all, and `advance_scene` means
    nothing to the author. This keeps the running interpretation.
    """

    episode_number: int
    events: list[ProgressEvent] = field(default_factory=list)
    scene_count: int = 0
    current_scene: int = 0
    finished: bool = False
    failed: str = ""
    _seen_reports: int = 0

    def update(self, node: str, state: dict[str, Any]) -> list[ProgressEvent]:
        """Absorb one node event; returns the events it produced (usually one)."""
        stage = NODE_STAGES.get(node)
        if stage is None:
            self.current_scene = state.get("current_scene_index", self.current_scene)
            return []

        new = getattr(self, f"_on_{stage.value}")(state)
        self.events.extend(new)
        return new

    # --- per-stage interpretation -----------------------------------------

    def _on_planning(self, state: dict[str, Any]) -> list[ProgressEvent]:
        scenes = state.get("scenes", [])
        self.scene_count = len(scenes)
        self.current_scene = 0
        return [
            ProgressEvent(
                Stage.PLANNING,
                f"Planned {len(scenes)} scene{'s' if len(scenes) != 1 else ''}",
            )
        ]

    def _on_simulating(self, state: dict[str, Any]) -> list[ProgressEvent]:
        number = self._scene_number(state)
        turns = len(state.get("current_entries", []))
        retries = state.get("retry_count", 0)
        label = "Re-simulated" if retries else "Simulated"
        return [
            ProgressEvent(
                Stage.SIMULATING,
                f"{label} {self._scene_label(number)} — {turns} turns",
                scene_number=number,
            )
        ]

    def _on_checking(self, state: dict[str, Any]) -> list[ProgressEvent]:
        reports = state.get("lore_reports", [])
        # Only the reports we have not already described.
        fresh = reports[self._seen_reports:]
        self._seen_reports = len(reports)

        events = []
        for report in fresh:
            number = report.get("scene_number")
            if report.get("passed"):
                events.append(
                    ProgressEvent(
                        Stage.CHECKING,
                        f"Lore check {self._scene_label(number)} — passed",
                        scene_number=number,
                    )
                )
            else:
                count = len(report.get("violations", []))
                events.append(
                    ProgressEvent(
                        Stage.CHECKING,
                        f"Lore check {self._scene_label(number)} — "
                        f"{count} violation{'s' if count != 1 else ''}, re-running",
                        scene_number=number,
                        warning=True,
                    )
                )
        return events

    def _on_writing(self, state: dict[str, Any]) -> list[ProgressEvent]:
        number = self._scene_number(state)
        prose = state.get("scene_prose_outputs", [])
        words = len(prose[-1].split()) if prose else 0
        return [
            ProgressEvent(
                Stage.WRITING,
                f"Wrote {self._scene_label(number)} — {words:,} words",
                scene_number=number,
            )
        ]

    def _on_assembling(self, state: dict[str, Any]) -> list[ProgressEvent]:
        self.finished = True
        words = len(state.get("final_episode_text", "").split())
        return [ProgressEvent(Stage.ASSEMBLING, f"Assembled the episode — {words:,} words")]

    # --- reporting ---------------------------------------------------------

    def note_recorded(self) -> ProgressEvent:
        event = ProgressEvent(Stage.RECORDING, "Recorded to memory")
        self.events.append(event)
        return event

    def note_failed(self, message: str) -> ProgressEvent:
        self.failed = message
        event = ProgressEvent(Stage.RECORDING, message, warning=True)
        self.events.append(event)
        return event

    def lines(self) -> list[str]:
        """The checklist so far, with the remaining work shown as pending."""
        rendered = [event.render() for event in self.events]
        if not self.finished and not self.failed:
            rendered.append(f"{RUNNING} {self.current_label()}")
            rendered.extend(f"{PENDING} {text}" for text in self._remaining())
        return rendered

    def current_label(self) -> str:
        if self.failed:
            return self.failed
        if self.finished:
            return "Done"
        if not self.scene_count:
            return "Planning scenes…"
        return f"Working on {self._scene_label(min(self.current_scene + 1, self.scene_count))}…"

    def fraction(self) -> float:
        """Rough completion, for a progress bar."""
        if self.finished:
            return 1.0
        if not self.scene_count:
            return 0.05
        # Three visible steps per scene, plus planning and assembly.
        total = self.scene_count * 3 + 2
        done = min(len([e for e in self.events if not e.warning]), total - 1)
        return max(0.05, done / total)

    def _remaining(self) -> list[str]:
        if not self.scene_count:
            return []
        remaining = []
        for number in range(self.current_scene + 1, self.scene_count + 1):
            written = any(
                e.stage is Stage.WRITING and e.scene_number == number for e in self.events
            )
            if not written:
                remaining.append(f"Scene {number}/{self.scene_count}")
        remaining.append("Assembling final text")
        return remaining

    def _scene_number(self, state: dict[str, Any]) -> int:
        return int(state.get("current_scene_index", 0)) + 1

    def _scene_label(self, number: int | None) -> str:
        if number is None:
            return "scene"
        if self.scene_count:
            return f"scene {number}/{self.scene_count}"
        return f"scene {number}"
