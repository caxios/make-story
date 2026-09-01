"""StoryWeaver — the author's workbench.

Run with:  streamlit run src/storyweaver/ui/app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

PAGES_DIR = Path(__file__).resolve().parent / "pages"

st.set_page_config(
    page_title="StoryWeaver",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _page(filename: str, title: str, icon: str, default: bool = False):
    return st.Page(str(PAGES_DIR / filename), title=title, icon=icon, default=default)


def main() -> None:
    # Imported here so `st.set_page_config` above is the first Streamlit call.
    from storyweaver.ui import components, state

    components.load_styles()

    navigation = st.navigation(
        {
            "Story": [
                _page("dashboard.py", "Dashboard", "🏠", default=True),
                _page("world_builder.py", "World Builder", "🌍"),
                _page("character_workshop.py", "Character Workshop", "👤"),
            ],
            "Writing": [
                _page("episode_queue.py", "Episode Queue", "📝"),
                _page("reading_room.py", "Reading Room", "📖"),
            ],
            "Under the hood": [
                _page("memory_inspector.py", "Memory Inspector", "🧠"),
                _page("settings.py", "Settings", "⚙️"),
            ],
        }
    )

    project = state.get_project()
    with st.sidebar:
        st.markdown(f"### 📖 {project.name}")
        components.hint(
            f"{len(project.characters)} characters · "
            f"{len(project.completed_episodes())}/{len(project.episodes)} episodes written"
        )

    state.flush_toast()
    navigation.run()


main()
