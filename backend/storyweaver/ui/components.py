"""Small rendering helpers shared by the pages."""

from __future__ import annotations

import html
import re
from pathlib import Path

import streamlit as st

from storyweaver.agents.episode_runner import SCENE_BREAK

STYLES_PATH = Path(__file__).resolve().parent / "styles.css"

# The few colours that must be real hues rather than a tint of the ink. Both
# sets are checked for WCAG AA (4.5:1) against their own backgrounds; they
# mirror the palettes in .streamlit/config.toml.
HUES = {
    "dark": {
        "--sw-accent": "#e0a951",
        "--sw-good": "#8fbe6e",
        "--sw-warn": "#e3a45e",
        "--sw-bad": "#e08078",
    },
    "light": {
        "--sw-accent": "#845808",
        "--sw-good": "#4a6b33",
        "--sw-warn": "#8a5a17",
        "--sw-bad": "#9a3b33",
    },
}

# A line of dialogue, in the quote marks either language uses.
_DIALOGUE = re.compile(r'^\s*[""“”"「『]')


def theme_type() -> str:
    """Which appearance the viewer is on: "dark" or "light".

    `st.context.theme` is documented as unreliable on the first render of a
    session and immediately after a theme change, so anything unexpected falls
    back to the configured default rather than guessing.
    """
    try:
        reported = st.context.theme.type
    except Exception:  # noqa: BLE001 — not worth a broken page
        return "dark"
    return reported if reported in HUES else "dark"


def load_styles() -> None:
    """Inject the stylesheet once per page render.

    The hue variables are emitted here rather than written into the stylesheet
    because Streamlit does not expose its theme to CSS, and these are the only
    values that cannot be derived from `currentColor`.
    """
    if not STYLES_PATH.is_file():
        return
    hues = "".join(f"{name}:{value};" for name, value in HUES[theme_type()].items())
    stylesheet = STYLES_PATH.read_text(encoding="utf-8")
    st.html(f"<style>:root{{{hues}}}\n{stylesheet}</style>")


def panel(markdown: str) -> None:
    st.html(f'<div class="sw-panel">{markdown}</div>')


def hint(text: str) -> None:
    st.html(f'<p class="sw-hint">{html.escape(text)}</p>')


def status_pill(status: str, label: str | None = None) -> str:
    """A coloured pill for an episode status or plot-thread status."""
    safe = html.escape(label or status.replace("_", " "))
    return f'<span class="sw-pill {html.escape(status)}">{safe}</span>'


def render_prose(text: str, title: str = "") -> None:
    """Show generated prose the way a reader would want to meet it.

    Scene breaks become dividers rather than three literal diamonds, and
    dialogue is lifted a shade so speech separates from narration at a glance.
    """
    # Sanitise: fix literal escape sequences and strip API metadata junk
    # that might be baked into episodes saved before the writer cleanup.
    cleaned = text.replace("\\n", "\n").replace("\\t", "\t")
    cleaned = re.sub(
        r"""(?:extras|additional_kwargs|response_metadata|safety_ratings|usage_metadata)"""
        r"""['"]?\s*[:=]\s*\{[^}]{20,}\}""",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"""['"]?signature['"]?\s*[:=]\s*['"][A-Za-z0-9+/=]{40,}['"]""", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    blocks = []
    if title:
        blocks.append(f'<div class="sw-chapter-title">{html.escape(title)}</div>')

    for section in cleaned.split(SCENE_BREAK):
        paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
        for paragraph in paragraphs:
            css_class = "sw-line" if _DIALOGUE.match(paragraph) else ""
            escaped = html.escape(paragraph)
            blocks.append(f'<p class="{css_class}">{escaped}</p>')
        blocks.append(f'<div class="sw-break">{html.escape(SCENE_BREAK)}</div>')

    if blocks and blocks[-1].startswith('<div class="sw-break"'):
        blocks.pop()  # no divider after the final scene

    st.html(f'<div class="sw-prose">{"".join(blocks)}</div>')


def render_checklist(lines: list[str], current: str = "") -> None:
    """The generation checklist, with the line in flight highlighted."""
    rendered = []
    for line in lines:
        css_class = "sw-now" if current and current in line else ""
        rendered.append(f'<div class="{css_class}">{html.escape(line)}</div>')
    st.html(f'<div class="sw-checklist">{"".join(rendered)}</div>')


def require_project(need_characters: bool = False) -> bool:
    """Guard a page that cannot do anything useful on an empty project."""
    from storyweaver.ui import state

    project = state.get_project()
    if not project.world.overview.strip():
        st.info(
            "This story has no world yet. Start in **🌍 World Builder**, or load the "
            "bundled sample from **⚙️ Settings**."
        )
        return False
    if need_characters and not project.characters:
        st.info("Add at least one character in **👤 Character Workshop** first.")
        return False
    return True
