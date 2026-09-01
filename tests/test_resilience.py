"""Retries, backoff, and repair — the things that decide whether a run survives."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from storyweaver.resilience import (
    MAX_TEMPERATURE,
    ModelCallError,
    ResilientModel,
    RetryPolicy,
    backoff_seconds,
    is_rate_limited,
)


class Answer(BaseModel):
    value: str


class Reply:
    """Stands in for an AIMessage."""

    def __init__(self, content: str):
        self.content = content


class ScriptedModel:
    """Fails in a scripted way, and records the temperature it was built at."""

    def __init__(self, temperature: float, script: list, calls: list):
        self.temperature = temperature
        self.script = script
        self.calls = calls

    def _next(self, prompt):
        self.calls.append((self.temperature, prompt))
        outcome = self.script.pop(0) if self.script else Reply("fallback")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def invoke(self, prompt, **_kwargs):
        return self._next(prompt)

    def with_structured_output(self, schema, **_kwargs):
        return self


def _model(script, policy: RetryPolicy | None = None, temperature: float = 0.0):
    calls: list = []
    model = ResilientModel(
        factory=lambda t: ScriptedModel(t, script, calls),
        temperature=temperature,
        policy=policy or RetryPolicy(sleep=lambda _: None, jitter=False),
        stage="test",
    )
    return model, calls


# ==========================================================================
# Classifying failures
# ==========================================================================

@pytest.mark.parametrize(
    "message",
    [
        "429 Too Many Requests",
        "ResourceExhausted: quota exceeded for this project",
        "503 Service Unavailable",
        "Deadline Exceeded",
    ],
)
def test_throttling_is_recognised(message):
    assert is_rate_limited(RuntimeError(message))


@pytest.mark.parametrize(
    "message", ["invalid api key", "schema validation failed", "no such model"]
)
def test_real_faults_are_not_mistaken_for_throttling(message):
    assert not is_rate_limited(RuntimeError(message))


def test_backoff_grows_and_is_capped():
    delays = [backoff_seconds(n, jitter=False) for n in range(8)]

    assert delays == sorted(delays)
    assert delays[0] == 2.0
    assert delays[-1] <= 60.0


def test_backoff_jitter_spreads_retries():
    """Without jitter, several throttled agents retry in lockstep and re-throttle."""
    delays = {backoff_seconds(3) for _ in range(20)}

    assert len(delays) > 1
    assert all(0 < d <= backoff_seconds(3, jitter=False) for d in delays)


# ==========================================================================
# Retrying
# ==========================================================================

def test_a_successful_call_is_made_once():
    model, calls = _model([Reply("fine")])

    assert model.invoke("prompt").content == "fine"
    assert len(calls) == 1


def test_a_transient_failure_is_retried():
    model, calls = _model([ValueError("bad output"), Reply("second time lucky")])

    assert model.invoke("prompt").content == "second time lucky"
    assert len(calls) == 2


def test_the_temperature_rises_with_each_retry():
    """A model stuck in a bad groove needs nudging, not just asking again."""
    model, calls = _model([ValueError("x"), ValueError("y"), Reply("ok")], temperature=0.5)

    model.invoke("prompt")

    assert [round(t, 2) for t, _ in calls] == [0.5, 0.65, 0.8]


def test_the_temperature_never_exceeds_the_maximum():
    policy = RetryPolicy(attempts=6, temperature_step=0.5, sleep=lambda _: None, jitter=False)
    model, calls = _model([ValueError("x")] * 5 + [Reply("ok")], policy=policy, temperature=0.9)

    model.invoke("prompt")

    assert max(t for t, _ in calls) <= MAX_TEMPERATURE


def test_throttling_waits_instead_of_raising_the_temperature():
    slept: list[float] = []
    policy = RetryPolicy(sleep=slept.append, jitter=False)
    model, calls = _model([RuntimeError("429 rate limit"), Reply("ok")], policy=policy)

    model.invoke("prompt")

    assert slept == [2.0]
    assert {t for t, _ in calls} == {0.0}  # temperature untouched


def test_a_persistent_failure_raises_a_clear_error():
    model, calls = _model([ValueError("still broken")] * 3)

    with pytest.raises(ModelCallError, match="after 3 attempts"):
        model.invoke("prompt")

    assert len(calls) == 3


def test_the_original_error_is_kept_as_the_cause():
    original = ValueError("the actual problem")
    model, _ = _model([original] * 3)

    with pytest.raises(ModelCallError) as caught:
        model.invoke("prompt")

    assert caught.value.__cause__ is original


def test_attempts_are_configurable():
    policy = RetryPolicy(attempts=5, sleep=lambda _: None, jitter=False)
    model, calls = _model([ValueError("x")] * 4 + [Reply("ok")], policy=policy)

    assert model.invoke("prompt").content == "ok"
    assert len(calls) == 5


# ==========================================================================
# Structured output and repair
# ==========================================================================

def test_structured_output_passes_through():
    model, _ = _model([Answer(value="clean")])

    assert model.with_structured_output(Answer).invoke("prompt").value == "clean"


def test_a_none_result_counts_as_a_failure():
    """Providers return None instead of raising when they cannot fill the schema."""
    model, calls = _model([None, Answer(value="second try")])

    assert model.with_structured_output(Answer).invoke("prompt").value == "second try"
    assert len(calls) == 2


def test_malformed_output_is_repaired_on_the_last_attempt():
    script = [
        ValueError("cannot parse"),
        ValueError("cannot parse"),
        ValueError("cannot parse"),
        Reply('{"value": "raw but wrong shape"'),   # the repair pass re-asks
        Reply('{"value": "repaired"}'),
    ]
    model, _ = _model(script)

    result = model.with_structured_output(Answer).invoke("prompt")

    assert result.value == "repaired"


def test_repair_strips_markdown_fences():
    """Models fence their JSON no matter how firmly the prompt asks them not to."""
    script = [
        ValueError("cannot parse"),
        ValueError("cannot parse"),
        ValueError("cannot parse"),
        Reply("garbage"),
        Reply('```json\n{"value": "fenced"}\n```'),
    ]
    model, _ = _model(script)

    assert model.with_structured_output(Answer).invoke("prompt").value == "fenced"


def test_a_repair_that_also_fails_raises_the_original_style_of_error():
    script = [ValueError("nope")] * 3 + [Reply("garbage"), Reply("still not json")]
    model, _ = _model(script)

    with pytest.raises(ModelCallError):
        model.with_structured_output(Answer).invoke("prompt")


def test_repair_can_be_switched_off():
    policy = RetryPolicy(repair=False, sleep=lambda _: None, jitter=False)
    model, calls = _model([ValueError("nope")] * 3, policy=policy)

    with pytest.raises(ModelCallError):
        model.with_structured_output(Answer).invoke("prompt")

    assert len(calls) == 3  # no extra repair calls
