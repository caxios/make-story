"""Durable writes, backups, and per-stage token accounting."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from storyweaver import telemetry
from storyweaver.storage import backup_directory, prune_backups, write_text_atomic
from storyweaver.telemetry import CallRecord, UsageLog, record_usage


# ==========================================================================
# Atomic writes
# ==========================================================================

def test_a_write_creates_the_file_and_its_parents(tmp_path):
    target = tmp_path / "deep" / "nested" / "state.json"

    write_text_atomic(target, '{"ok": true}')

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_a_write_replaces_the_previous_contents(tmp_path):
    target = tmp_path / "state.json"
    write_text_atomic(target, "first")

    write_text_atomic(target, "second")

    assert target.read_text(encoding="utf-8") == "second"


def test_a_failed_write_leaves_the_old_file_intact(tmp_path):
    """The point of the temp file: a crash mid-write must not truncate the state."""
    target = tmp_path / "state.json"
    write_text_atomic(target, "the good version")

    with patch("storyweaver.storage.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            write_text_atomic(target, "the doomed version")

    assert target.read_text(encoding="utf-8") == "the good version"


def test_a_failed_write_cleans_up_its_temp_file(tmp_path):
    target = tmp_path / "state.json"

    with patch("storyweaver.storage.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            write_text_atomic(target, "doomed")

    assert list(tmp_path.glob("*.tmp")) == []


def test_writes_use_unix_newlines(tmp_path):
    """State files are read by other tools and diffed; keep them platform-neutral."""
    target = tmp_path / "state.json"

    write_text_atomic(target, "one\ntwo\n")

    assert target.read_bytes() == b"one\ntwo\n"


def test_unicode_survives_a_round_trip(tmp_path):
    target = tmp_path / "state.json"

    write_text_atomic(target, "떡밥 ◇◇◇ Erised")

    assert target.read_text(encoding="utf-8") == "떡밥 ◇◇◇ Erised"


# ==========================================================================
# Backups
# ==========================================================================

def test_a_directory_can_be_snapshotted(tmp_path):
    source = tmp_path / "state"
    source.mkdir()
    (source / "story_memory.json").write_text("{}", encoding="utf-8")

    snapshot = backup_directory(source)

    assert snapshot is not None
    assert (snapshot / "story_memory.json").is_file()
    assert source.is_dir()  # a copy, not a move


def test_an_empty_or_missing_directory_is_not_snapshotted(tmp_path):
    empty = tmp_path / "state"
    empty.mkdir()

    assert backup_directory(empty) is None
    assert backup_directory(tmp_path / "nothing-here") is None


def test_pruning_keeps_only_the_newest_snapshots(tmp_path):
    root = tmp_path / "backups"
    for stamp in ("state-20260101-000000", "state-20260102-000000", "state-20260103-000000"):
        (root / stamp).mkdir(parents=True)

    removed = prune_backups(root, keep=2)

    assert [p.name for p in removed] == ["state-20260101-000000"]
    assert sorted(p.name for p in root.iterdir()) == [
        "state-20260102-000000",
        "state-20260103-000000",
    ]


def test_pruning_a_missing_directory_is_harmless(tmp_path):
    assert prune_backups(tmp_path / "nothing") == []


# ==========================================================================
# Usage accounting
# ==========================================================================

class Response:
    def __init__(self, content: str, usage: dict | None = None):
        self.content = content
        if usage is not None:
            self.usage_metadata = usage


def test_nothing_is_recorded_outside_a_recording_block():
    assert telemetry.active_log() is None
    assert telemetry.record_call("writer", "prompt", Response("out"), 0.1) is None


def test_provider_reported_tokens_are_preferred():
    with record_usage("episode 1") as log:
        telemetry.record_call(
            "writer",
            "a short prompt",
            Response("out", {"input_tokens": 4000, "output_tokens": 1200}),
            1.5,
        )

    assert log.input_tokens == 4000
    assert log.output_tokens == 1200
    assert log.any_estimated is False


def test_tokens_are_estimated_when_the_provider_reports_none():
    """Structured-output responses routinely arrive without usage metadata."""
    with record_usage() as log:
        telemetry.record_call("lore", "x" * 400, Response("y" * 200), 0.3)

    assert log.input_tokens == 100  # 400 chars / 4
    assert log.output_tokens == 50
    assert log.any_estimated is True


def test_a_pydantic_response_is_measured_by_its_json():
    from storyweaver.agents.lore_checker import ValidationResult

    with record_usage() as log:
        telemetry.record_call("lore", "prompt", ValidationResult(passed=True), 0.2)

    assert log.output_tokens > 0


def test_stage_totals_rank_the_expensive_stages_first():
    log = UsageLog()
    log.add(CallRecord("supervisor", 100, 20, 0.1))
    log.add(CallRecord("character", 5000, 400, 1.0))
    log.add(CallRecord("character", 5200, 380, 1.1))
    log.add(CallRecord("writer", 6000, 3000, 4.0))

    stages = list(log.by_stage())

    # Character is two calls totalling 10,980 tokens; the Writer is one at 9,000.
    assert stages == ["character", "writer", "supervisor"]
    assert log.by_stage()["character"].calls == 2
    assert log.by_stage()["character"].total_tokens == 10980
    assert log.by_stage()["writer"].total_tokens == 9000


def test_cost_uses_separate_input_and_output_rates():
    log = UsageLog()
    log.add(CallRecord("writer", 1_000_000, 1_000_000, 1.0))

    assert log.cost(input_per_mtok=0.30, output_per_mtok=2.50) == pytest.approx(2.80)


def test_the_report_names_every_stage_and_totals_them():
    log = UsageLog(label="episode 3")
    log.add(CallRecord("character", 5000, 400, 1.0))
    log.add(CallRecord("writer", 6000, 3000, 4.0, estimated=True))

    report = log.report()

    assert "episode 3" in report
    assert "character" in report and "writer" in report
    assert "TOTAL" in report
    assert "14,400" in report  # total tokens
    assert "1/2 calls had no usage metadata" in report


def test_an_empty_report_says_so():
    assert "no LLM calls" in UsageLog(label="episode 9").report()


def test_recording_blocks_do_not_leak_into_each_other():
    with record_usage("first") as first:
        telemetry.record_call("writer", "a", Response("b"), 0.1)

    with record_usage("second") as second:
        telemetry.record_call("writer", "c", Response("d"), 0.1)

    assert first.calls == 1
    assert second.calls == 1
    assert telemetry.active_log() is None


def test_timed_call_records_what_is_handed_to_it():
    with record_usage() as log:
        with telemetry.timed_call("director", "the prompt") as slot:
            slot.append(Response("the answer"))

    assert log.calls == 1
    assert log.records[0].stage == "director"
    assert log.records[0].seconds >= 0


def test_a_call_that_raises_records_nothing():
    with record_usage() as log:
        with pytest.raises(RuntimeError):
            with telemetry.timed_call("director", "the prompt"):
                raise RuntimeError("the model fell over")

    assert log.calls == 0
