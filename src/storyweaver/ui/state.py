"""Session state shared by every page.

Streamlit re-runs a page's script top to bottom on every interaction, so nothing
may live in a module global. This is the single place that reaches into
`st.session_state`, which keeps the pages from each other's business and keeps
the keys in one file where they can be seen at once.
"""

from __future__ import annotations

import logging

import streamlit as st

from storyweaver.memory import MemoryManager
from storyweaver.ui.project import Project, ProjectStore

logger = logging.getLogger(__name__)

PROJECT = "project"
STORE = "project_store"
MEMORY = "memory_manager"
MEMORY_ERROR = "memory_error"
PROGRESS = "generation_progress"
LAST_GENERATED = "last_generated_episode"
TOAST = "pending_toast"


def get_store() -> ProjectStore:
    if STORE not in st.session_state:
        st.session_state[STORE] = ProjectStore()
    return st.session_state[STORE]


def get_project() -> Project:
    """The project currently being edited, loaded from disk on first access."""
    if PROJECT not in st.session_state:
        st.session_state[PROJECT] = get_store().load()
    return st.session_state[PROJECT]


def set_project(project: Project, save: bool = True) -> Project:
    st.session_state[PROJECT] = project
    if save:
        get_store().save(project)
    return project


def save_project() -> None:
    """Persist whatever the pages have mutated in place."""
    get_store().save(get_project())


def get_memory() -> MemoryManager | None:
    """The MemoryManager, or None if it could not be started.

    Building one loads ChromaDB, which downloads an embedding model the first
    time. That is slow and can fail offline, and none of the authoring pages
    need it — so a failure is reported rather than raised, and the rest of the
    app carries on without memory.
    """
    if MEMORY not in st.session_state:
        try:
            st.session_state[MEMORY] = MemoryManager()
            st.session_state[MEMORY_ERROR] = ""
        except Exception as error:  # noqa: BLE001 — surfaced in the UI instead
            logger.exception("Could not start the memory layer")
            st.session_state[MEMORY] = None
            st.session_state[MEMORY_ERROR] = str(error)
    return st.session_state[MEMORY]


def memory_error() -> str:
    return st.session_state.get(MEMORY_ERROR, "")


def open_thread_count() -> int:
    memory = get_memory()
    return len(memory.get_active_plot_threads()) if memory else 0


def queue_toast(message: str, icon: str = "✅") -> None:
    """Show a message after the rerun that a form submission triggers."""
    st.session_state[TOAST] = (message, icon)


def flush_toast() -> None:
    pending = st.session_state.pop(TOAST, None)
    if pending:
        st.toast(pending[0], icon=pending[1])
