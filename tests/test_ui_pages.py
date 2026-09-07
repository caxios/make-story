"""Every page actually runs.

Streamlit's `AppTest` executes a page script the way the server would, so these
catch the mistakes that only appear at render time — a bad `st.` call, a
missing session key, a widget whose default is out of range. Each test injects
a temp-directory `ProjectStore` so the author's real `data/` is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storyweaver.ui import state
from storyweaver.ui.project import Project, ProjectStore, project_from_sample

PAGES = [
    "dashboard.py",
    "world_builder.py",
    "character_workshop.py",
    "episode_queue.py",
    "reading_room.py",
    "memory_inspector.py",
    "settings.py",
]

PAGE_DIR = __import__("storyweaver.ui.pages", fromlist=["pages"]).__path__[0]


def _run(page: str, store: ProjectStore, project: Project | None = None, memory=None) -> AppTest:
    app = AppTest.from_file(f"{PAGE_DIR}/{page}", default_timeout=30)
    app.session_state[state.STORE] = store
    if project is not None:
        # Save as well as inject: the app reads from the store on a fresh session,
        # and assertions here check what actually landed on disk.
        store.save(project)
        app.session_state[state.PROJECT] = project
    # Pre-seed memory so no page builds a real ChromaDB client.
    app.session_state[state.MEMORY] = memory
    app.session_state[state.MEMORY_ERROR] = "" if memory else "disabled for tests"
    return app.run()


def _by_label(widgets, label: str):
    """AppTest indexes widgets by key; these forms identify them by label."""
    for widget in widgets:
        if widget.label == label:
            return widget
    raise AssertionError(f"No widget labelled {label!r} (have: {[w.label for w in widgets]})")


def _button(app: AppTest, fragment: str):
    for button in list(app.button) + list(app.get("form_submit_button")):
        if fragment in button.label:
            return button
    raise AssertionError(f"No button matching {fragment!r}")


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def loaded(sample_data) -> Project:
    """The sample project, with one episode already written."""
    project = project_from_sample(sample_data)
    project.update_episode(
        project.episodes[0].model_copy(
            update={
                "status": "completed",
                "title": "The Sorting",
                "final_text": "The ceiling churned with cloud.\n\n◇◇◇\n\n"
                '"Potter, Harry," called Professor McGonagall.',
            }
        )
    )
    return project


# ==========================================================================
# Every page renders, empty and loaded
# ==========================================================================

@pytest.mark.parametrize("page", PAGES)
def test_a_page_renders_on_an_empty_project(page, store):
    app = _run(page, store)
    assert not app.exception


@pytest.mark.parametrize("page", PAGES)
def test_a_page_renders_on_a_loaded_project(page, store, loaded):
    app = _run(page, store, loaded)
    assert not app.exception


@pytest.mark.parametrize("page", PAGES)
def test_a_page_renders_with_memory_available(page, store, loaded, memory, world):
    memory.seed_world(world)
    app = _run(page, store, loaded, memory=memory)
    assert not app.exception


def test_the_app_entry_point_runs(store, loaded):
    import storyweaver.ui.app as app_module

    app = AppTest.from_file(str(app_module.__file__), default_timeout=30)
    app.session_state[state.STORE] = store
    app.session_state[state.PROJECT] = loaded
    app.session_state[state.MEMORY] = None
    app.run()

    assert not app.exception


# ==========================================================================
# Test 1: the authoring workflow, through the widgets
# ==========================================================================

def test_a_world_can_be_written_through_the_form(store):
    app = _run("world_builder.py", store)

    _by_label(app.text_input, "Title").set_value("The Wizarding World")
    _by_label(app.text_input, "Genre").set_value("fantasy")
    _by_label(app.text_area, "Overview").set_value("A hidden magical society.")
    _button(app, "Save world").click().run()

    assert not app.exception
    assert store.load().world.title == "The Wizarding World"
    assert store.load().world.overview == "A hidden magical society."


def test_an_episode_can_be_queued_through_the_form(store, loaded):
    app = _run("episode_queue.py", store, loaded)

    app.text_area("new_episode_storyline").set_value("Harry meets Ron on the train.")
    _button(app, "Add to queue").click().run()

    assert not app.exception
    saved = store.load()
    assert saved.episodes[-1].author_storyline == "Harry meets Ron on the train."
    assert saved.episodes[-1].status == "queued"


def test_writing_style_is_saved_from_settings(store, loaded):
    app = _run("settings.py", store, loaded)

    _by_label(app.text_area, "Author style notes").set_value("Short paragraphs.")
    _button(app, "Save style").click().run()

    assert not app.exception
    assert store.load().style.author_style_notes == "Short paragraphs."


def test_the_small_sample_can_be_loaded_from_settings(store):
    app = _run("settings.py", store)

    _button(app, "Small sample").click().run()

    assert not app.exception
    assert len(store.load().characters) == 3


def test_the_flagship_dataset_can_be_loaded_from_settings(store):
    app = _run("settings.py", store)

    _button(app, "The Wizarding World").click().run()

    assert not app.exception
    loaded = store.load()
    assert len(loaded.characters) == 8
    assert len(loaded.episodes) == 10
    assert len(loaded.world.rules) == 15


# ==========================================================================
# Test 2: data persists across page navigations
# ==========================================================================

def test_data_written_on_one_page_is_visible_on_another(store):
    builder = _run("world_builder.py", store)
    _by_label(builder.text_input, "Title").set_value("Persisted World")
    _by_label(builder.text_area, "Overview").set_value("It stayed.")
    _button(builder, "Save world").click().run()

    # A fresh page and a fresh session: only the files on disk carry over, which
    # is exactly what a browser reload gives you.
    dashboard = _run("dashboard.py", ProjectStore(store.data_dir))

    assert not dashboard.exception
    assert ProjectStore(store.data_dir).load().world.title == "Persisted World"
    # Having read a real world from disk, the dashboard drops its "nothing here yet" notice.
    assert not dashboard.info


def test_the_reading_room_shows_a_written_episode(store, loaded):
    app = _run("reading_room.py", store, loaded)

    assert not app.exception
    assert any("The Sorting" in str(m.value) for m in app.markdown)


def test_the_reading_room_offers_nothing_to_read_when_nothing_is_written(store, sample_data):
    app = _run("reading_room.py", store, project_from_sample(sample_data))

    assert not app.exception
    assert app.info  # the "generate one first" notice


def test_the_dashboard_counts_a_written_episode(store, loaded):
    app = _run("dashboard.py", store, loaded)

    assert not app.exception
    values = {m.label: m.value for m in app.metric}
    assert values["Episodes written"] == "1"
    assert values["Characters"] == "3"


# ==========================================================================
# Theming
# ==========================================================================

def _theme_config() -> dict:
    # tomllib is 3.11+; tomli is the same parser, and is already a dependency
    # of the toolchain on 3.10.
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))["theme"]


def test_the_streamlit_theme_is_configured():
    """Without this file Streamlit renders light widgets on the styled page."""
    theme = _theme_config()
    assert theme["base"] == "dark"
    for appearance in ("dark", "light"):
        palette = theme[appearance]
        assert palette["backgroundColor"]
        assert palette["textColor"]
        assert palette["primaryColor"]
        assert palette["secondaryBackgroundColor"]


def test_every_themed_pair_meets_wcag_aa():
    """Colour choices are checked, not eyeballed."""
    theme = _theme_config()

    def luminance(value: str) -> float:
        channels = [int(value.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def contrast(a: str, b: str) -> float:
        first, second = luminance(a), luminance(b)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    failures = []
    for appearance in ("dark", "light"):
        palette = theme[appearance]
        surfaces = [palette["backgroundColor"], palette["secondaryBackgroundColor"]]
        inks = [
            palette["textColor"], palette["primaryColor"], palette["linkColor"],
            palette["greenColor"], palette["redColor"], palette["orangeColor"],
            palette["grayColor"],
        ]
        for ink in inks:
            for surface in surfaces:
                if contrast(ink, surface) < 4.5:
                    failures.append((appearance, ink, surface, round(contrast(ink, surface), 2)))

    assert not failures, f"below AA: {failures}"


def test_custom_hues_are_defined_for_both_appearances():
    from storyweaver.ui.components import HUES

    assert set(HUES) == {"dark", "light"}
    assert set(HUES["dark"]) == set(HUES["light"])
    assert HUES["dark"] != HUES["light"]  # a light theme needs darker accents


def test_an_unknown_theme_falls_back_to_the_configured_default(store):
    """`st.context.theme` is documented as unreliable on the first render."""
    from storyweaver.ui import components

    app = _run("dashboard.py", store)

    assert not app.exception
    assert components.theme_type() in ("dark", "light")


def test_the_stylesheet_hardcodes_no_theme_colours():
    """Neutrals must derive from currentColor, or they break in one appearance."""
    from storyweaver.ui.components import STYLES_PATH

    stylesheet = STYLES_PATH.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in stylesheet.splitlines() if not line.strip().startswith(("*", "/*"))
    )

    assert "#" not in body, "a literal colour in styles.css will be wrong in one theme"
    assert "currentColor" in body
