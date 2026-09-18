"""What the story has cost so far.

`telemetry.UsageLog` only lives as long as the run that made it, so a total
across runs has to be written down. Each finished generation appends one line
here; the endpoint adds them up.

Deliberately append-only and tiny: a run records six numbers, not its calls.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from storyweaver import config, telemetry as core
from storyweaver.api import deps
from storyweaver.storage import write_text_atomic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

FILENAME = "usage.json"
# Enough to see a trend without the file growing without bound.
MAX_RUNS = 500


def _path() -> Path:
    return deps.get_store().state_dir / FILENAME


def load_runs() -> list[dict[str, Any]]:
    path = _path()
    if not path.is_file():
        return []
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        logger.exception("Could not read %s; reporting no history", path)
        return []
    return runs if isinstance(runs, list) else []


def record_run(episode_number: int, usage: core.UsageLog) -> None:
    """Append one finished generation's totals. Never raises."""
    if not usage.calls:
        return
    try:
        runs = load_runs()
        runs.append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "episode_number": episode_number,
                "calls": usage.calls,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "seconds": round(usage.seconds, 1),
                "cost": round(usage.cost(), 4),
                "estimated": usage.any_estimated,
                "by_stage": {
                    stage: totals.total_tokens for stage, totals in usage.by_stage().items()
                },
            }
        )
        write_text_atomic(_path(), json.dumps(runs[-MAX_RUNS:], indent=2) + "\n")
    except Exception:  # noqa: BLE001 — accounting must never cost the author a chapter
        logger.exception("Could not record usage for episode %d", episode_number)


@router.get("")
def read_telemetry() -> dict:
    """Cumulative spend, the per-stage split, and the last few runs."""
    runs = load_runs()
    input_tokens = sum(run.get("input_tokens", 0) for run in runs)
    output_tokens = sum(run.get("output_tokens", 0) for run in runs)

    by_stage: dict[str, int] = {}
    for run in runs:
        for stage, tokens in (run.get("by_stage") or {}).items():
            by_stage[stage] = by_stage.get(stage, 0) + tokens

    return {
        "model": config.MODEL_NAME,
        "api_key_configured": bool(config.GOOGLE_API_KEY),
        "temperature": config.TEMPERATURE,
        "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        "input_cost_per_mtok": core.DEFAULT_INPUT_COST_PER_MTOK,
        "output_cost_per_mtok": core.DEFAULT_OUTPUT_COST_PER_MTOK,
        "runs": len(runs),
        "calls": sum(run.get("calls", 0) for run in runs),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "seconds": round(sum(run.get("seconds", 0.0) for run in runs), 1),
        "cost": round(sum(run.get("cost", 0.0) for run in runs), 4),
        # True when any run had to estimate token counts because the provider
        # did not report them — the totals are then a floor, not a measurement.
        "estimated": any(run.get("estimated") for run in runs),
        "by_stage": dict(sorted(by_stage.items(), key=lambda item: item[1], reverse=True)),
        "recent": list(reversed(runs[-10:])),
    }
