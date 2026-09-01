"""Small rendering helpers shared by the pages."""

from __future__ import annotations

import html
import re
from pathlib import Path

import streamlit as st

from storyweaver.agents.episode_runner import SCENE_BREAK

STYLES_PATH = Path(__file__).resolve().parent / "styles.css"

# A line of dialogue, in the quote marks either language uses.
_DIALOGUE = re.compile(r'^\s*[""“”"「『]')


def load_styles() -> None:
    """Inject the stylesheet once per page render."""
    if STYLES_PATH.is_file():
        st.html(f"<style>{STYLES_PATH.read_text(encoding='utf-8')}</style>")


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
    blocks = []
    if title:
        blocks.append(f'<div class="sw-chapter-title">{html.escape(title)}</div>')

    for section in text.split(SCENE_BREAK):
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
