"""Retries, backoff, and output repair, wrapped around any chat model.

Every agent takes an optional `llm=`, and `llm.get_llm()` is what they fall back
to. Putting resilience in that wrapper means one implementation covers all seven
call sites, and tests can still inject a bare fake.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
# Creative calls that come back malformed are usually stuck in a bad groove;
# nudging temperature up on the retry shakes them out of it.
TEMPERATURE_STEP = 0.15
MAX_TEMPERATURE = 1.0

BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0

# Substrings that mark an error as "wait and try again" rather than "this is broken".
RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "resource_exhausted",
    "resourceexhausted",
    "quota",
    "too many requests",
    "503",
    "unavailable",
    "deadline exceeded",
    "timeout",
)

REPAIR_PROMPT = """The following text was meant to be a JSON object matching this schema:

{schema}

It could not be parsed. Return the same content as a single valid JSON object
matching the schema exactly. Do not add commentary, explanation, or markdown
fences — output the JSON object and nothing else.

The text to repair:
{text}
"""


class ModelCallError(RuntimeError):
    """Raised when a call could not be made to succeed after every attempt."""


def is_rate_limited(error: BaseException) -> bool:
    """Whether an exception looks like throttling rather than a real fault.

    Provider SDKs raise a wide and shifting set of exception types, so this
    matches on the message rather than pinning to classes that move between
    library versions.
    """
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def backoff_seconds(attempt: int, jitter: bool = True) -> float:
    """Exponential backoff for `attempt` (0-based), capped and jittered.

    The jitter matters: without it, several agents throttled at the same moment
    would retry in lockstep and throttle each other again.
    """
    delay = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
    if jitter:
        delay *= 0.5 + random.random() / 2
    return delay


@dataclass
class RetryPolicy:
    """How hard to try, and how long to wait between tries."""

    attempts: int = DEFAULT_ATTEMPTS
    temperature_step: float = TEMPERATURE_STEP
    repair: bool = True
    sleep: Callable[[float], None] = time.sleep
    jitter: bool = True

    def delay_for(self, attempt: int) -> float:
        return backoff_seconds(attempt, jitter=self.jitter)


@dataclass
class ResilientModel:
    """A chat model that retries, backs off, and repairs malformed output.

    `factory(temperature)` builds the underlying model, so a retry can raise the
    temperature — which needs a new model object, not a new argument.
    """

    factory: Callable[[float], Any]
    temperature: float = 0.0
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    stage: str = "unknown"
    _models: dict[float, Any] = field(default_factory=dict, repr=False)

    def model_for(self, temperature: float) -> Any:
        rounded = round(min(temperature, MAX_TEMPERATURE), 3)
        if rounded not in self._models:
            self._models[rounded] = self.factory(rounded)
        return self._models[rounded]

    @property
    def base(self) -> Any:
        return self.model_for(self.temperature)

    # --- the two call shapes the agents use --------------------------------

    def invoke(self, prompt: Any, **kwargs: Any) -> Any:
        """A free-text call, as the Writer makes."""
        return self._attempt(
            lambda model: model.invoke(prompt, **kwargs),
            description="free-text call",
        )

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> "_Structured":
        return _Structured(self, schema, kwargs)

    # --- the retry loop ----------------------------------------------------

    def _attempt(
        self,
        call: Callable[[Any], Any],
        description: str,
        repair: Callable[[Any, BaseException], Any] | None = None,
    ) -> Any:
        last_error: BaseException | None = None
        # Counted separately from `attempt`: a throttled call never reached the
        # model, so there is no bad groove to shake it out of.
        escalations = 0

        for attempt in range(self.policy.attempts):
            temperature = min(
                self.temperature + escalations * self.policy.temperature_step, MAX_TEMPERATURE
            )
            try:
                return call(self.model_for(temperature))
            except BaseException as error:  # noqa: BLE001 — re-raised below
                last_error = error
                is_last = attempt == self.policy.attempts - 1

                if is_rate_limited(error):
                    # Throttling is not the model's fault; wait rather than
                    # raising the temperature at it.
                    logger.warning(
                        "%s: rate limited on %s, attempt %d/%d",
                        self.stage, description, attempt + 1, self.policy.attempts,
                    )
                    if not is_last:
                        self.policy.sleep(self.policy.delay_for(attempt))
                        continue
                else:
                    logger.warning(
                        "%s: %s failed (%s: %s), attempt %d/%d",
                        self.stage, description, type(error).__name__, error,
                        attempt + 1, self.policy.attempts,
                    )
                    escalations += 1
                    if not is_last:
                        continue

                if repair is not None and self.policy.repair:
                    try:
                        logger.info("%s: attempting to repair the model's output", self.stage)
                        return repair(self.base, error)
                    except BaseException as repair_error:  # noqa: BLE001
                        logger.warning("%s: repair failed too (%s)", self.stage, repair_error)

        raise ModelCallError(
            f"{self.stage}: {description} failed after {self.policy.attempts} attempts"
        ) from last_error


@dataclass
class _Structured:
    """The bound result of `with_structured_output`, with repair attached."""

    parent: ResilientModel
    schema: type[BaseModel]
    kwargs: dict[str, Any]

    def invoke(self, prompt: Any, **call_kwargs: Any) -> BaseModel:
        def call(model: Any) -> BaseModel:
            result = model.with_structured_output(self.schema, **self.kwargs).invoke(
                prompt, **call_kwargs
            )
            if result is None:
                raise ValueError("the model returned no structured output")
            return result

        return self.parent._attempt(
            call,
            description=f"structured call for {self.schema.__name__}",
            repair=lambda model, error: self._repair(model, prompt, error),
        )

    def _repair(self, model: Any, prompt: Any, error: BaseException) -> BaseModel:
        """Ask the model to fix its own malformed output.

        Cheaper and far more likely to work than re-running the original
        prompt: the content was probably fine and only the envelope was wrong.
        """
        raw = model.invoke(prompt)
        text = str(getattr(raw, "content", raw))
        repaired = model.invoke(
            REPAIR_PROMPT.format(schema=_schema_text(self.schema), text=text)
        )
        payload = _strip_fences(str(getattr(repaired, "content", repaired)))
        try:
            return self.schema.model_validate_json(payload)
        except ValidationError as validation_error:
            raise ModelCallError(
                f"repair produced output that still does not match {self.schema.__name__}"
            ) from validation_error


def _schema_text(schema: type[BaseModel]) -> str:
    import json

    return json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)


def _strip_fences(text: str) -> str:
    """Models wrap JSON in markdown fences no matter how firmly you ask them not to."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
    return stripped.strip()
