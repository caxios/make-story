"""Prompt templates, kept as plain text files so they can be edited without code changes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Load the raw template `<name>.md` from this directory."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No prompt template named {name!r} in {PROMPTS_DIR}")
    return path.read_text(encoding="utf-8")


def render_prompt(template_name: str, /, **values: object) -> str:
    """Load a template and substitute its `{placeholder}` fields.

    `template_name` is positional-only so that a template is free to use any
    placeholder it likes — including `{name}`, which the character prompt does.
    """
    return load_prompt(template_name).format(**values)


__all__ = ["PROMPTS_DIR", "load_prompt", "render_prompt"]
