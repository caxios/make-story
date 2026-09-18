"""Token and cost accounting, per pipeline stage.

An episode is a few hundred LLM calls across seven stages. Without a per-stage
breakdown, "this episode cost too much" is not an actionable sentence — this
turns it into "the Character agent is 70% of your spend, and the supervisor is
4%", which tells you where to look.
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Gemini Flash-class pricing, USD per million tokens. Providers change these, so
# they are overridable rather than baked into the arithmetic.
DEFAULT_INPUT_COST_PER_MTOK = 0.30
DEFAULT_OUTPUT_COST_PER_MTOK = 2.50

# When the provider does not report usage, fall back to the standard rule of
# thumb. Marked `estimated` so a report never passes a guess off as a measurement.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class CallRecord:
    """One LLM call."""

    stage: str
    input_tokens: int
    output_tokens: int
    seconds: float
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StageTotals:
    """Everything one stage spent."""

    stage: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    estimated_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost(
        self,
        input_per_mtok: float = DEFAULT_INPUT_COST_PER_MTOK,
        output_per_mtok: float = DEFAULT_OUTPUT_COST_PER_MTOK,
    ) -> float:
        return (
            self.input_tokens * input_per_mtok + self.output_tokens * output_per_mtok
        ) / 1_000_000


@dataclass
class UsageLog:
    """Accumulates calls for one episode (or one whole run)."""

    label: str = "run"
    records: list[CallRecord] = field(default_factory=list)

    def add(self, record: CallRecord) -> CallRecord:
        self.records.append(record)
        return record

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def seconds(self) -> float:
        return sum(r.seconds for r in self.records)

    @property
    def any_estimated(self) -> bool:
        return any(r.estimated for r in self.records)

    def by_stage(self) -> dict[str, StageTotals]:
        totals: dict[str, StageTotals] = {}
        for record in self.records:
            entry = totals.setdefault(record.stage, StageTotals(stage=record.stage))
            entry.calls += 1
            entry.input_tokens += record.input_tokens
            entry.output_tokens += record.output_tokens
            entry.seconds += record.seconds
            entry.estimated_calls += int(record.estimated)
        return dict(
            sorted(totals.items(), key=lambda item: item[1].total_tokens, reverse=True)
        )

    def cost(
        self,
        input_per_mtok: float = DEFAULT_INPUT_COST_PER_MTOK,
        output_per_mtok: float = DEFAULT_OUTPUT_COST_PER_MTOK,
    ) -> float:
        return (
            self.input_tokens * input_per_mtok + self.output_tokens * output_per_mtok
        ) / 1_000_000

    def report(
        self,
        input_per_mtok: float = DEFAULT_INPUT_COST_PER_MTOK,
        output_per_mtok: float = DEFAULT_OUTPUT_COST_PER_MTOK,
    ) -> str:
        """A plain-text breakdown, for the CLI and the UI."""
        if not self.records:
            return f"{self.label}: no LLM calls recorded."

        header = f"{'stage':<14}{'calls':>7}{'in':>11}{'out':>10}{'tokens':>11}{'cost':>10}"
        lines = [f"Usage — {self.label}", header, "-" * len(header)]
        for totals in self.by_stage().values():
            lines.append(
                f"{totals.stage:<14}{totals.calls:>7}{totals.input_tokens:>11,}"
                f"{totals.output_tokens:>10,}{totals.total_tokens:>11,}"
                f"{totals.cost(input_per_mtok, output_per_mtok):>10.4f}"
            )
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL':<14}{self.calls:>7}{self.input_tokens:>11,}"
            f"{self.output_tokens:>10,}{self.total_tokens:>11,}"
            f"{self.cost(input_per_mtok, output_per_mtok):>10.4f}"
        )
        lines.append(f"Wall time in model calls: {self.seconds:.1f}s")
        if self.any_estimated:
            estimated = sum(1 for r in self.records if r.estimated)
            lines.append(
                f"Note: {estimated}/{self.calls} calls had no usage metadata; "
                f"their tokens are estimated at ~{CHARS_PER_TOKEN} chars/token."
            )
        return "\n".join(lines)


# The active log, if any. A contextvar rather than a global so that a UI session
# generating two episodes does not merge their accounting.
_active: contextvars.ContextVar[UsageLog | None] = contextvars.ContextVar(
    "storyweaver_usage_log", default=None
)


def active_log() -> UsageLog | None:
    return _active.get()


@contextmanager
def record_usage(label: str = "run") -> Iterator[UsageLog]:
    """Collect every LLM call made inside this block."""
    log = UsageLog(label=label)
    token = _active.set(log)
    try:
        yield log
    finally:
        _active.reset(token)


def estimate_tokens(text: Any) -> int:
    return max(1, len(str(text)) // CHARS_PER_TOKEN)


def _reported_usage(response: Any) -> tuple[int, int] | None:
    """Pull real token counts off a response, if the provider sent any."""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        output_tokens = usage.get("output_tokens") or usage.get("candidates_token_count")
        if input_tokens is not None and output_tokens is not None:
            return int(input_tokens), int(output_tokens)

    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        usage = metadata.get("usage_metadata") or metadata.get("token_usage")
        if isinstance(usage, dict):
            input_tokens = usage.get("prompt_token_count") or usage.get("prompt_tokens")
            output_tokens = usage.get("candidates_token_count") or usage.get("completion_tokens")
            if input_tokens is not None and output_tokens is not None:
                return int(input_tokens), int(output_tokens)
    return None


def record_call(stage: str, prompt: Any, response: Any, seconds: float) -> CallRecord | None:
    """Log one call against the active `UsageLog`, if there is one.

    Prefers the provider's own counts and falls back to estimating from length —
    structured-output responses in particular often carry no usage metadata.
    """
    log = active_log()
    if log is None:
        return None

    reported = _reported_usage(response)
    if reported is not None:
        input_tokens, output_tokens = reported
        estimated = False
    else:
        input_tokens = estimate_tokens(prompt)
        output_tokens = estimate_tokens(
            getattr(response, "content", None)
            or (response.model_dump_json() if hasattr(response, "model_dump_json") else response)
        )
        estimated = True

    return log.add(
        CallRecord(
            stage=stage,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            seconds=seconds,
            estimated=estimated,
        )
    )


class MeteredModel:
    """Wraps any chat model so every call it makes is timed and counted.

    Applied at the agent call sites rather than inside the model factory, so an
    injected model is metered too — otherwise the accounting would silently
    measure only the calls that happened to come from `get_llm`.
    """

    def __init__(self, model: Any, stage: str):
        self._model = model
        self._stage = stage

    def invoke(self, prompt: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = self._model.invoke(prompt, **kwargs)
        record_call(self._stage, prompt, result, time.perf_counter() - started)
        return result

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "MeteredModel":
        return MeteredModel(self._model.with_structured_output(schema, **kwargs), self._stage)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def meter(model: Any, stage: str) -> Any:
    """Meter a model, unless nothing is recording or it is already metered."""
    if active_log() is None or isinstance(model, MeteredModel):
        return model
    return MeteredModel(model, stage)


@contextmanager
def timed_call(stage: str, prompt: Any) -> Iterator[list]:
    """Time a call and record it. Append the response to the yielded list.

        with timed_call("writer", prompt) as slot:
            result = model.invoke(prompt)
            slot.append(result)
    """
    slot: list = []
    started = time.perf_counter()
    try:
        yield slot
    finally:
        if slot:
            record_call(stage, prompt, slot[0], time.perf_counter() - started)
