"""📝 Episode Queue — outlines in, and the button that turns one into a chapter."""

from __future__ import annotations

import streamlit as st

from storyweaver import telemetry
from storyweaver.agents import episode_runner
from storyweaver.agents.checkpoint import CheckpointStore
from storyweaver.models.style import PACING
from storyweaver.ui import components, state
from storyweaver.ui.progress import GenerationProgress

components.load_styles()

project = state.get_project()
checkpoints = CheckpointStore(state.get_store().state_dir)

st.title("📝 Episode Queue")

unfinished = checkpoints.pending()
if unfinished:
    numbers = ", ".join(str(c.episode_number) for c in unfinished)
    st.info(
        f"Episode {numbers} stopped partway through, and the scenes already written "
        "are saved. Generating it again picks up from where it left off."
    )

queue_tab, add_tab = st.tabs(["Queue", "Add episodes"])

# --- The queue -------------------------------------------------------------

with queue_tab:
    if not project.episodes:
        components.hint("Nothing queued yet. Add an outline in the next tab.")

    for index, episode in enumerate(project.episodes):
        words = len(episode.final_text.split())
        header = f"**{episode.episode_number}.** {episode.title or '(untitled)'}"
        columns = st.columns([5, 2, 1, 1, 1, 1])
        columns[0].markdown(header)
        columns[1].html(
            components.status_pill(episode.status)
            + (f' <span class="sw-hint">{words:,} words</span>' if words else "")
        )
        if columns[2].button("↑", key=f"up_{episode.episode_number}", disabled=index == 0):
            project.move_episode(episode.episode_number, -1)
            state.save_project()
            st.rerun()
        if columns[3].button(
            "↓",
            key=f"down_{episode.episode_number}",
            disabled=index == len(project.episodes) - 1,
        ):
            project.move_episode(episode.episode_number, 1)
            state.save_project()
            st.rerun()
        if columns[4].button("🔄", key=f"requeue_{episode.episode_number}", help="Re-queue / Regenerate this episode"):
            checkpoints.clear(episode.episode_number)
            project.update_episode(episode.model_copy(update={"status": "queued"}))
            state.save_project()
            st.session_state["target_episode_to_generate"] = episode.episode_number
            state.queue_toast(f"Episode {episode.episode_number} queued for generation", "🔄")
            st.rerun()
        if columns[5].button("🗑️", key=f"del_{episode.episode_number}"):
            if episode.status == "completed":
                st.session_state[f"confirm_queue_del_{episode.episode_number}"] = True
                st.rerun()
            else:
                project.remove_episode(episode.episode_number)
                project.renumber_episodes()
                state.save_project()
                st.rerun()

        # Confirmation dialog for completed episodes
        confirm_key = f"confirm_queue_del_{episode.episode_number}"
        if st.session_state.get(confirm_key, False):
            st.warning(
                f"Episode {episode.episode_number} is already **completed** "
                f"({len(episode.final_text.split()):,} words). Delete it?",
                icon="⚠️",
            )
            confirm_cols = st.columns([1, 1, 6])
            if confirm_cols[0].button("Yes, delete", key=f"yes_qdel_{episode.episode_number}", type="primary"):
                project.remove_episode(episode.episode_number)
                project.renumber_episodes()
                state.save_project()
                st.session_state[confirm_key] = False
                state.queue_toast(f"Episode {episode.episode_number} deleted", "🗑️")
                st.rerun()
            if confirm_cols[1].button("Cancel", key=f"no_qdel_{episode.episode_number}"):
                st.session_state[confirm_key] = False
                st.rerun()

        with st.expander("Storyline", expanded=False):
            with st.form(f"edit_ep_{episode.episode_number}"):
                title = st.text_input("Title", episode.title)
                storyline = st.text_area("Author storyline", episode.author_storyline, height=160)
                options = list(PACING)
                pacing = st.select_slider(
                    "Pacing",
                    options,
                    value=episode.pacing if episode.pacing in options else "normal",
                    key=f"pace_{episode.episode_number}",
                )
                components.hint(PACING[pacing])
                if st.form_submit_button("Save"):
                    project.update_episode(
                        episode.model_copy(
                            update={
                                "title": title,
                                "author_storyline": storyline,
                                "pacing": pacing,
                            }
                        )
                    )
                    state.save_project()
                    state.queue_toast("Episode saved")
                    st.rerun()

    st.divider()

    # --- Generation --------------------------------------------------------

    target_num = st.session_state.pop("target_episode_to_generate", None)

    if not project.episodes:
        components.hint("Nothing in the queue yet. Add an outline in the next tab.")
    elif not components.require_project(need_characters=True):
        pass
    else:
        st.subheader("Generate Episode")

        ep_numbers = [e.episode_number for e in project.episodes]
        default_index = 0
        if target_num is not None and target_num in ep_numbers:
            default_index = ep_numbers.index(target_num)
        else:
            first_queued = project.next_queued_episode()
            if first_queued is not None and first_queued.episode_number in ep_numbers:
                default_index = ep_numbers.index(first_queued.episode_number)
            elif ep_numbers:
                default_index = len(ep_numbers) - 1

        selected_ep_num = st.selectbox(
            "Select episode to generate",
            ep_numbers,
            index=default_index,
            format_func=lambda n: f"Episode {n}: {project.get_episode(n).title or '(untitled)'} [{project.get_episode(n).status}]",
        )

        target_episode = project.get_episode(selected_ep_num)

        if target_episode.status == "completed":
            components.hint("⚠️ This episode is already completed. Generating it again will overwrite the existing story text.")
            btn_label = f"🔄 Regenerate Episode {target_episode.episode_number}"
        else:
            btn_label = f"✨ Generate Episode {target_episode.episode_number}"

        columns = st.columns([2, 1])
        max_turns = columns[1].number_input(
            "Turns per scene", min_value=2, max_value=40, value=12,
            help="The cap. A scene usually ends earlier, when its objective is met.",
        )
        resumable = checkpoints.load(target_episode.episode_number)
        if resumable and resumable.matches(
            target_episode.episode_number, target_episode.author_storyline
        ):
            components.hint(
                f"Resuming from scene {resumable.current_scene_index + 1} — "
                f"{resumable.scenes_completed} scene(s) are already written."
            )

        triggered = columns[0].button(
            btn_label,
            type="primary",
            use_container_width=True,
        ) or st.session_state.pop("start_generation", False)

        if triggered:
            if target_episode.status == "completed":
                checkpoints.clear(target_episode.episode_number)

            memory = state.get_memory()
            progress = GenerationProgress(episode_number=target_episode.episode_number)
            st.session_state[state.PROGRESS] = progress

            project.update_episode(target_episode.model_copy(update={"status": "in_progress"}))
            state.save_project()

            with st.status(
                f"Generating Episode {target_episode.episode_number}…", expanded=True
            ) as status:
                checklist = st.empty()
                bar = st.progress(0.0)

                def show() -> None:
                    with checklist:
                        components.render_checklist(progress.lines(), progress.current_label())
                    bar.progress(progress.fraction())

                show()

                def on_event(node: str, pipeline_state: dict) -> None:
                    progress.update(node, pipeline_state)
                    show()

                label = f"episode {target_episode.episode_number}"
                # Outside the try, so a run that fails halfway still reports what
                # it spent getting there.
                with telemetry.record_usage(label) as usage:
                    try:
                        done, final = episode_runner.run_episode(
                            target_episode,
                            project.world,
                            project.character_map(),
                            style=project.style,
                            max_turns_per_scene=int(max_turns),
                            memory=memory,
                            checkpoints=checkpoints,
                            on_event=on_event,
                        )
                    except Exception as error:  # noqa: BLE001 — shown to the author
                        progress.note_failed(f"Generation failed: {error}")
                        show()
                        project.update_episode(
                            target_episode.model_copy(update={"status": "queued"})
                        )
                        state.save_project()
                        status.update(label="Generation failed", state="error")
                        if checkpoints.load(target_episode.episode_number):
                            st.info(
                                "The scenes finished before the failure are saved. "
                                "Generate again to pick up from there."
                            )
                        st.exception(error)
                    else:
                        if memory is not None and "episode_memory" in final:
                            progress.note_recorded()
                        show()
                        project.update_episode(done)
                        state.save_project()
                        st.session_state[state.LAST_GENERATED] = done.episode_number
                        status.update(
                            label=f"Episode {done.episode_number} written "
                            f"({len(done.final_text.split()):,} words)",
                            state="complete",
                        )

            if usage.calls:
                with st.expander(f"What this cost — {usage.total_tokens:,} tokens"):
                    st.code(usage.report(), language="text")

            if project.get_episode(target_episode.episode_number).status == "completed":
                if st.button("📖 Read it", type="primary"):
                    st.switch_page("pages/reading_room.py")

# --- Adding ----------------------------------------------------------------

with add_tab:
    with st.form("add_episode", clear_on_submit=True):
        st.markdown(f"**Episode {project.next_episode_number()}**")
        title = st.text_input("Title (optional)", key="new_episode_title")
        storyline = st.text_area(
            "Author storyline",
            key="new_episode_storyline",
            height=220,
            placeholder="이번 회차에서 일어날 이야기를 대략적으로 적어주세요...",
            help="Rough is fine. The Director fills in the connective tissue between your beats.",
        )
        new_pacing = st.select_slider(
            "Pacing", list(PACING), value="normal", key="new_episode_pacing"
        )
        components.hint(PACING[new_pacing])
        if st.form_submit_button("Add to queue", type="primary"):
            if not storyline.strip():
                st.error("An episode needs a storyline.")
            else:
                added = project.add_episode(storyline.strip(), title.strip())
                project.update_episode(added.model_copy(update={"pacing": new_pacing}))
                state.save_project()
                state.queue_toast("Added to the queue")
                st.rerun()

    st.divider()
    st.subheader("Batch add")
    components.hint("Upload or paste several outlines at once, separated by a line of `---`.")

    uploaded = st.file_uploader("Outlines (.txt / .md)", type=["txt", "md"])
    pasted = st.text_area("…or paste them here", height=160, key="batch_paste")

    if st.button("Add all"):
        text = ""
        if uploaded is not None:
            text = uploaded.getvalue().decode("utf-8")
        elif pasted.strip():
            text = pasted
        if not text.strip():
            st.error("Nothing to add.")
        else:
            added = project.add_episodes_from_text(text)
            state.save_project()
            state.queue_toast(f"Added {len(added)} episodes")
            st.rerun()
