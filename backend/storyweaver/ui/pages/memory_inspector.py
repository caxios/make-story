"""🧠 Memory Inspector — what the story remembers, and what it is forgetting."""

from __future__ import annotations

import streamlit as st

from storyweaver.ui import components, state

components.load_styles()

project = state.get_project()
memory = state.get_memory()

st.title("🧠 Memory Inspector")

if memory is None:
    st.error(
        "The memory layer could not start, so there is nothing to inspect. "
        f"({state.memory_error()})"
    )
    st.stop()

threads_tab, characters_tab, summaries_tab, search_tab = st.tabs(
    ["Plot threads", "Character memory", "Episode summaries", "Search"]
)

# --- Plot threads ----------------------------------------------------------

with threads_tab:
    all_threads = memory.plot_tracker.all()
    stale_ids = {t.id for t in memory.get_stale_plot_threads()}

    if not all_threads:
        components.hint("No threads yet. They are opened by the Summarizer as episodes land.")

    wanted = st.multiselect(
        "Status", ["open", "progressing", "resolved"], default=["open", "progressing"]
    )
    shown = [t for t in all_threads if t.status in wanted]
    components.hint(f"{len(shown)} of {len(all_threads)} threads")

    for thread in shown:
        pills = components.status_pill(thread.status)
        if thread.id in stale_ids:
            pills += " " + components.status_pill("stale", "going cold")

        with st.expander(f"{thread.name}  ({thread.id})"):
            st.html(pills)
            st.markdown(thread.description)
            components.hint(
                f"Opened in episode {thread.opened_in_episode} · "
                f"last touched in {thread.last_referenced_episode}"
                + (
                    f" · resolved in {thread.resolved_in_episode}"
                    if thread.resolved_in_episode
                    else ""
                )
            )
            if thread.linked_characters:
                names = [
                    project.get_character(c).name if project.get_character(c) else c
                    for c in thread.linked_characters
                ]
                st.markdown("**Who it involves** — " + ", ".join(names))

            if thread.events:
                st.markdown("**Timeline**")
                for event in thread.events:
                    st.markdown(f"- {event}")
            if thread.resolution:
                st.success(f"Resolved: {thread.resolution}")

            st.divider()
            columns = st.columns([3, 1])
            if thread.status == "resolved":
                if columns[1].button("Reactivate", key=f"reopen_{thread.id}"):
                    memory.progress_plot_thread(
                        thread.id, "Reopened by the author.", project.next_episode_number() - 1
                    )
                    state.queue_toast(f"Reactivated {thread.name}")
                    st.rerun()
            else:
                resolution = columns[0].text_input(
                    "Resolution", key=f"res_{thread.id}", placeholder="How it was paid off"
                )
                if columns[1].button("Force resolve", key=f"forceres_{thread.id}"):
                    memory.resolve_plot_thread(
                        thread.id,
                        resolution.strip() or "Resolved by the author.",
                        project.next_episode_number() - 1,
                    )
                    state.queue_toast(f"Resolved {thread.name}")
                    st.rerun()

# --- Character memory ------------------------------------------------------

with characters_tab:
    known = memory.structured_store.known_character_ids()
    if not known:
        components.hint("No character memories yet — they are written as episodes complete.")
    else:
        selected = st.selectbox(
            "Character",
            known,
            format_func=lambda i: project.get_character(i).name
            if project.get_character(i)
            else i,
        )
        record = memory.get_character_state(selected)

        columns = st.columns(2)
        with columns[0]:
            st.markdown("#### Current state")
            components.panel(record.internal_state or "<em>Nothing recorded.</em>")
            st.markdown("#### Goals")
            if record.current_goals:
                for goal in record.current_goals:
                    st.markdown(f"- {goal}")
            else:
                components.hint("No goals recorded.")

        with columns[1]:
            st.markdown("#### How they feel about others now")
            if not record.relationship_updates:
                components.hint("No relationship changes recorded.")
            for relationship in record.relationship_updates:
                target = project.get_character(relationship.target_character_id)
                name = target.name if target else relationship.target_character_id
                st.markdown(
                    f"**{name}** — {relationship.type} ({relationship.sentiment:+.1f})"
                    + (f"  \n{relationship.description}" if relationship.description else "")
                )

        st.markdown("#### Interaction timeline")
        history = sorted(
            record.interaction_history, key=lambda r: (r.episode_number, r.scene_number)
        )
        if not history:
            components.hint("No interactions recorded.")
        for entry in history:
            others = [
                project.get_character(p).name if project.get_character(p) else p
                for p in entry.participants
                if p != selected
            ]
            with st.expander(
                f"Episode {entry.episode_number}, scene {entry.scene_number}"
                + (f" — with {', '.join(others)}" if others else "")
            ):
                st.markdown(entry.summary)
                if entry.emotional_impact:
                    st.markdown(
                        "**How it landed** — "
                        + "; ".join(f"{k}: {v}" for k, v in entry.emotional_impact.items())
                    )
                for thread in entry.plot_threads_opened:
                    st.markdown(f"- opened `{thread}`")
                for thread in entry.plot_threads_resolved:
                    st.markdown(f"- resolved `{thread}`")

# --- Episode summaries -----------------------------------------------------

with summaries_tab:
    summaries = memory.structured_store.get_story().episode_summaries
    if not summaries:
        components.hint("No summaries yet.")
    else:
        needle = st.text_input("Search summaries", placeholder="trapdoor, promise, Flamel…")
        for number in sorted(summaries):
            text = summaries[number]
            if needle and needle.lower() not in text.lower():
                continue
            title = project.get_episode(number)
            label = f"Episode {number}"
            if title and title.title:
                label += f": {title.title}"
            with st.expander(label):
                st.markdown(text)

# --- Semantic search -------------------------------------------------------

with search_tab:
    components.hint(
        "This is the same retrieval the agents use. If a memory does not surface here, "
        "it will not reach a prompt either."
    )
    query = st.text_input("Search memory", placeholder="What does Ron know about the Stone?")
    columns = st.columns([1, 1])
    top_k = columns[0].slider("Results", 1, 25, 8)
    scope = columns[1].selectbox(
        "Only what this character remembers",
        [""] + [c.id for c in project.characters],
        format_func=lambda i: project.get_character(i).name if i else "— anyone —",
    )

    if query.strip():
        results = memory.search(query, top_k=top_k, character_id=scope or None)
        if not results:
            st.info("Nothing matched.")
        for result in results:
            with st.expander(
                f"{result.collection} · {result.id}"
                + (f" · distance {result.distance:.3f}" if result.distance is not None else "")
            ):
                st.markdown(result.document)
                st.json(result.metadata, expanded=False)
