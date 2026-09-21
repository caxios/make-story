"""Shared Gemini chat-model factory.

Every agent goes through :func:`get_llm`, so the model name, temperature, token
budget, retry behaviour and usage accounting are all configured in exactly one
place. Agents accept an optional ``llm`` argument, which makes them trivially
testable with a stub.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from storyweaver import config
from storyweaver.resilience import ResilientModel, RetryPolicy

# What each stage is for, and how much invention it wants. Judgement calls run
# cold; prose runs warm. See docs/architecture.md for the full audit.
STAGE_TEMPERATURES = {
    "director": 0.7,
    "character": config.TEMPERATURE,
    "supervisor": 0.0,
    "lore": 0.0,
    "writer": config.TEMPERATURE,
    "summarizer": 0.2,
    # Reading an author's paragraph back as structured data. Nothing here is
    # meant to be invented, so it runs as cold as the other judgement calls.
    "parse": 0.1,
    # Drawing a one-line summary out into an episode outline. Warmer than
    # parsing, cooler than prose: it is inventing structure, not sentences.
    "planner": 0.6,
    "titler": 0.5,
    "transition": config.TEMPERATURE,
}


@lru_cache(maxsize=16)
def build_model(
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> ChatGoogleGenerativeAI:
    """Build (and cache) a raw Gemini chat model.

    Constructed lazily so that importing an agent module never requires an API
    key — only actually invoking one does.
    """
    return ChatGoogleGenerativeAI(
        model=config.MODEL_NAME,
        google_api_key=config.require_api_key(),
        temperature=config.TEMPERATURE if temperature is None else temperature,
        max_output_tokens=(
            config.MAX_OUTPUT_TOKENS if max_output_tokens is None else max_output_tokens
        ),
    )


def get_llm(
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    stage: str = "unknown",
    policy: RetryPolicy | None = None,
) -> ResilientModel:
    """The model an agent should use: metered, and resilient to bad days.

    `stage` names the caller for the usage report and the retry logs. When no
    `temperature` is given, the stage's own default applies — a continuity
    judgement and a paragraph of prose do not want the same setting.
    """
    if temperature is None:
        temperature = STAGE_TEMPERATURES.get(stage, config.TEMPERATURE)

    def factory(value: float):
        return build_model(value, max_output_tokens)

    return ResilientModel(
        factory=factory,
        temperature=temperature,
        policy=policy or RetryPolicy(),
        stage=stage,
    )
