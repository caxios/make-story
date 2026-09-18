"""🏠 Dashboard — where the story stands, and what to do next."""

from __future__ import annotations

import streamlit as st

from storyweaver.ui import components, state

components.load_styles()

project = state.get_project()
memory = state.get_memory()
stats = project.stats(open_thread_count=state.open_thread_count())

st.title("🏠 Dashboard")

if not project.world.overview.strip():
    st.info(
        "Nothing here yet. Build a world in **🌍 World Builder**, or load the bundled "
        "Harry Potter sample from **⚙️ Settings** to see the whole pipeline work."
    )

# --- Story stats -----------------------------------------------------------

columns = st.columns(4)
columns[0].metric("Episodes written", stats.episodes_completed)
columns[1].metric("Total words", f"{stats.total_words:,}")
columns[2].metric("Characters", stats.character_count)
columns[3].metric("Open threads", stats.open_thread_count)

if state.memory_error():
    st.warning(
        "The memory layer could not start, so episodes will be written without "
        f"continuity from earlier ones. ({state.memory_error()})"
    )

st.divider()

left, right = st.columns([3, 2])

# --- Quick actions ---------------------------------------------------------

with left:
    st.subheader("Quick actions")
    next_episode = project.next_queued_episode()

    if next_episode is None:
        components.hint("Nothing is queued. Add an episode outline to get going.")
        if st.button("📝 Add an episode", use_container_width=True):
            st.switch_page("pages/episode_queue.py")
    else:
        components.hint(
            f"Next up — Episode {next_episode.episode_number}: "
            f"{next_episode.author_storyline[:140]}"
            + ("…" if len(next_episode.author_storyline) > 140 else "")
        )
        if st.button(
            f"✨ Generate Episode {next_episode.episode_number}",
            type="primary",
            use_container_width=True,
        ):
            # The queue page owns generation; it has the progress display.
            st.session_state["start_generation"] = True
            st.switch_page("pages/episode_queue.py")

    if project.completed_episodes():
        if st.button("📖 Open the Reading Room", use_container_width=True):
            st.switch_page("pages/reading_room.py")

    # --- Recent activity ---------------------------------------------------

    st.subheader("Recent activity")
    recent = sorted(
        project.completed_episodes(), key=lambda e: e.episode_number, reverse=True
    )[:3]
    if not recent:
        components.hint("No episodes have been generated yet.")
    for episode in recent:
        words = len(episode.final_text.split())
        st.html(
            f'<div class="sw-panel"><strong>Episode {episode.episode_number}'
            f'{": " + episode.title if episode.title else ""}</strong> '
            f'{components.status_pill(episode.status)}'
            f'<p class="sw-hint">{len(episode.scenes)} scenes · {words:,} words</p></div>'
        )

# --- Plot threads ----------------------------------------------------------

with right:
    st.subheader("Active plot threads (떡밥)")
    if memory is None:
        components.hint("Memory is unavailable, so threads cannot be shown.")
    else:
        threads = memory.get_active_plot_threads()
        stale_ids = {t.id for t in memory.get_stale_plot_threads()}
        if not threads:
            components.hint("No open threads yet — they appear as episodes are written.")
        for thread in threads[:5]:
            pill = components.status_pill(thread.status)
            if thread.id in stale_ids:
                pill += " " + components.status_pill("stale", "going cold")
            st.html(
                f'<div class="sw-panel"><strong>{thread.name}</strong> {pill}'
                f'<p class="sw-hint">{thread.description}<br>'
                f'Opened in episode {thread.opened_in_episode}, '
                f'last touched in {thread.last_referenced_episode}.</p></div>'
            )
        if len(threads) > 5:
            components.hint(f"…and {len(threads) - 5} more in the Memory Inspector.")
