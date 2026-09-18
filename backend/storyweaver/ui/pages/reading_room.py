"""📖 Reading Room — the only page that shows the story as a reader would meet it."""

from __future__ import annotations

import streamlit as st

from storyweaver import export
from storyweaver.agents.checkpoint import CheckpointStore
from storyweaver.ui import components, state

components.load_styles()

project = state.get_project()
completed = project.completed_episodes()

st.title("📖 Reading Room")

if not completed:
    st.info("No episodes have been written yet. Generate one from **📝 Episode Queue**.")
    st.stop()

# --- Selection -------------------------------------------------------------

with st.sidebar:
    st.markdown("#### Chapters")
    numbers = [e.episode_number for e in completed]
    default = st.session_state.get(state.LAST_GENERATED)
    selected = st.radio(
        "Episode",
        numbers,
        index=numbers.index(default) if default in numbers else len(numbers) - 1,
        format_func=lambda n: f"{n}. {project.get_episode(n).title or '(untitled)'}",
        label_visibility="collapsed",
    )

episode = project.get_episode(selected)

columns = st.columns([3, 1, 1, 1, 1])
columns[0].markdown(f"### Episode {episode.episode_number}: {episode.title or '(untitled)'}")
compare = columns[1].toggle("Side by side", help="Show the outline you wrote alongside the prose.")
editing = columns[2].toggle("Edit mode")

# --- Regenerate with confirmation ---
regen_key = f"confirm_regen_{episode.episode_number}"
if regen_key not in st.session_state:
    st.session_state[regen_key] = False

if st.session_state[regen_key]:
    with columns[3]:
        st.warning("Regen?", icon="⚠️")
        confirm_cols = st.columns(2)
        if confirm_cols[0].button("Yes", key=f"yes_reg_{episode.episode_number}", type="primary"):
            checkpoints = CheckpointStore(state.get_store().state_dir)
            checkpoints.clear(episode.episode_number)
            project.update_episode(episode.model_copy(update={"status": "queued"}))
            state.save_project()
            st.session_state[regen_key] = False
            st.session_state["target_episode_to_generate"] = episode.episode_number
            st.session_state["start_generation"] = True
            st.switch_page("pages/episode_queue.py")
        if confirm_cols[1].button("No", key=f"no_reg_{episode.episode_number}"):
            st.session_state[regen_key] = False
            st.rerun()
else:
    if columns[3].button("🔄 Regenerate", key=f"reg_{episode.episode_number}"):
        st.session_state[regen_key] = True
        st.rerun()

# --- Delete with confirmation ---
delete_key = f"confirm_delete_{episode.episode_number}"
if delete_key not in st.session_state:
    st.session_state[delete_key] = False

if st.session_state[delete_key]:
    with columns[4]:
        st.warning("Sure?", icon="⚠️")
        confirm_cols = st.columns(2)
        if confirm_cols[0].button("Yes", key=f"yes_del_{episode.episode_number}", type="primary"):
            project.remove_episode(episode.episode_number)
            project.renumber_episodes()
            state.save_project()
            st.session_state[delete_key] = False
            state.queue_toast(f"Episode {episode.episode_number} deleted", "🗑️")
            st.rerun()
        if confirm_cols[1].button("No", key=f"no_del_{episode.episode_number}"):
            st.session_state[delete_key] = False
            st.rerun()
else:
    if columns[4].button("🗑️ Delete", key=f"del_{episode.episode_number}"):
        st.session_state[delete_key] = True
        st.rerun()

components.hint(f"{len(episode.scenes)} scenes · {len(episode.final_text.split()):,} words")

st.divider()

# --- Reading ---------------------------------------------------------------

if editing:
    with st.form("edit_prose"):
        edited = st.text_area(
            "Episode text", episode.final_text, height=640, label_visibility="collapsed"
        )
        save, revert = st.columns([4, 1])
        if save.form_submit_button("Save changes", type="primary"):
            project.update_episode(episode.model_copy(update={"final_text": edited}))
            state.save_project()
            state.queue_toast("Your edits are saved")
            st.rerun()
        if revert.form_submit_button("Cancel"):
            st.rerun()

elif compare:
    prose_column, notes_column = st.columns([3, 2])
    with prose_column:
        components.render_prose(episode.final_text)
    with notes_column:
        st.markdown("#### Your outline")
        components.panel(episode.author_storyline)
        st.markdown("#### Scenes")
        for scene in episode.scenes:
            with st.expander(f"{scene.scene_number}. {scene.title}"):
                st.markdown(f"**Objective** — {scene.objective}")
                if scene.beats:
                    st.markdown("**Beats**")
                    for beat in scene.beats:
                        st.markdown(f"- {beat.description}")
                if scene.interaction_log:
                    st.markdown("**Interaction log**")
                    st.code("\n".join(scene.interaction_log), language="text")
else:
    components.render_prose(episode.final_text)

# --- Export ----------------------------------------------------------------

st.divider()
st.subheader("Export")

stem = f"episode_{episode.episode_number}"
columns = st.columns(3)
columns[0].download_button(
    "⬇️ .txt", export.to_text(episode), file_name=f"{stem}.txt", mime="text/plain",
    use_container_width=True,
)
columns[1].download_button(
    "⬇️ .md", export.to_markdown(episode), file_name=f"{stem}.md", mime="text/markdown",
    use_container_width=True,
)
columns[2].download_button(
    "⬇️ .docx",
    export.to_docx(episode),
    file_name=f"{stem}.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    use_container_width=True,
)

st.markdown("#### The whole story")
components.hint(
    "One document with a table of contents, every chapter, and appendices for "
    "the cast and the world."
)
appendices = st.checkbox("Include appendices", value=True)
book = f"{project.name.lower().replace(' ', '_') or 'story'}"

columns = st.columns(3)
columns[0].download_button(
    "⬇️ Story (.md)",
    export.assemble_story(
        project.name, completed, project.characters, project.world,
        include_appendices=appendices,
    ),
    file_name=f"{book}.md",
    mime="text/markdown",
    use_container_width=True,
)
columns[1].download_button(
    "⬇️ Story (.txt)",
    "\n\n".join(export.to_text(e) for e in completed),
    file_name=f"{book}.txt",
    mime="text/plain",
    use_container_width=True,
)
columns[2].download_button(
    "⬇️ Story (.docx)",
    export.story_to_docx(
        project.name, completed, project.characters, project.world,
        include_appendices=appendices,
    ),
    file_name=f"{book}.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    use_container_width=True,
)
