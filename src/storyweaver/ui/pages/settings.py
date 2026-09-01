"""⚙️ Settings — how the prose should sound, which model writes it, and the project itself."""

from __future__ import annotations

import streamlit as st

from storyweaver import config, storage, telemetry
from storyweaver.agents.checkpoint import CheckpointStore
from storyweaver.models import WritingStyle
from storyweaver.models.style import PERSPECTIVES, PROSE_DENSITIES
from storyweaver.ui import components, state
from storyweaver.ui.project import load_sample_project

components.load_styles()

project = state.get_project()
style = project.style

st.title("⚙️ Settings")

style_tab, model_tab, project_tab, safety_tab = st.tabs(
    ["Writing style", "Model & cost", "Project", "Backups & recovery"]
)

# --- Writing style ---------------------------------------------------------

with style_tab:
    components.hint("These reach the Writer, and only the Writer. They never change what happens.")

    with st.form("writing_style"):
        columns = st.columns(2)

        perspectives = list(PERSPECTIVES)
        perspective = columns[0].selectbox(
            "Perspective",
            perspectives,
            index=perspectives.index(style.perspective)
            if style.perspective in perspectives
            else 0,
            format_func=lambda p: p.replace("_", " ").title(),
        )

        character_ids = [""] + [c.id for c in project.characters]
        pov = columns[1].selectbox(
            "Point-of-view character",
            character_ids,
            index=character_ids.index(style.pov_character_id or "")
            if (style.pov_character_id or "") in character_ids
            else 0,
            format_func=lambda i: project.get_character(i).name
            if project.get_character(i)
            else "— whoever opens the scene —",
            help="Ignored for omniscient. If they are not in a scene, the scene's opener is used.",
        )

        densities = list(PROSE_DENSITIES)
        density = st.select_slider(
            "Prose density",
            densities,
            value=style.prose_density if style.prose_density in densities else "moderate",
        )
        components.hint(PROSE_DENSITIES[density])

        dialogue_ratio = st.slider(
            "Dialogue vs. narration", 0.0, 1.0, style.dialogue_ratio, 0.05,
            help="A target, not a quota — roughly this share of the text as dialogue.",
        )
        target_words = st.number_input(
            "Target words per scene", min_value=200, max_value=6000,
            value=style.target_word_count_per_scene, step=100,
        )

        languages = {"ko": "한국어", "en": "English", "ja": "日本語", "es": "Español"}
        language = st.selectbox(
            "Output language",
            list(languages),
            index=list(languages).index(style.language) if style.language in languages else 0,
            format_func=lambda code: f"{languages[code]} ({code})",
        )
        notes = st.text_area(
            "Author style notes",
            style.author_style_notes,
            placeholder="e.g. Write like Diana Wynne Jones. Short paragraphs. No adverbs in dialogue tags.",
            height=110,
        )

        if st.form_submit_button("Save style", type="primary"):
            project.style = WritingStyle(
                perspective=perspective,
                pov_character_id=pov or None,
                prose_density=density,
                dialogue_ratio=dialogue_ratio,
                target_word_count_per_scene=int(target_words),
                language=language,
                author_style_notes=notes,
            )
            state.save_project()
            state.queue_toast("Style saved")
            st.rerun()

# --- Model -----------------------------------------------------------------

with model_tab:
    st.markdown("#### Current configuration")
    components.panel(
        f"<strong>Model</strong> — <code>{config.MODEL_NAME}</code><br>"
        f"<strong>Temperature</strong> — {config.TEMPERATURE}<br>"
        f"<strong>Max output tokens</strong> — {config.MAX_OUTPUT_TOKENS:,}<br>"
        f"<strong>API key</strong> — {'set' if config.GOOGLE_API_KEY else 'MISSING'}"
    )

    if not config.GOOGLE_API_KEY:
        st.error(
            "`GOOGLE_API_KEY` is not set, so generation will fail. Put it in `.env` at the "
            "project root and restart the app."
        )

    st.markdown("#### What an episode costs")
    components.hint(
        "Rates are USD per million tokens for a Flash-class model. Every generation "
        "reports its own measured breakdown in the Episode Queue; this is the pricing "
        "those numbers are converted with."
    )
    components.panel(
        f"<strong>Input</strong> — ${telemetry.DEFAULT_INPUT_COST_PER_MTOK:.2f} / Mtok<br>"
        f"<strong>Output</strong> — ${telemetry.DEFAULT_OUTPUT_COST_PER_MTOK:.2f} / Mtok<br>"
        "A four-scene episode with three characters runs roughly 150k–250k tokens."
    )

    st.markdown("#### Resilience")
    components.panel(
        "Every model call retries up to 3 times. Malformed output is retried at a "
        "higher temperature and then repaired; rate limits are backed off "
        "exponentially with jitter, up to 60 seconds."
    )

    components.hint(
        "Model settings are read from the environment at startup, so that a long "
        "generation cannot have the model changed underneath it. To change them, edit "
        "`.env` and restart:"
    )
    st.code(
        "GOOGLE_API_KEY=...\n"
        f"STORYWEAVER_MODEL={config.MODEL_NAME}\n"
        f"STORYWEAVER_TEMPERATURE={config.TEMPERATURE}\n"
        f"STORYWEAVER_MAX_OUTPUT_TOKENS={config.MAX_OUTPUT_TOKENS}\n"
        f"STORYWEAVER_RECENT_EPISODES={config.RECENT_EPISODE_CONTEXT}\n"
        f"STORYWEAVER_STALE_THREAD_EPISODES={config.STALE_THREAD_EPISODES}",
        language="bash",
    )

# --- Project ---------------------------------------------------------------

with project_tab:
    with st.form("project_name"):
        name = st.text_input("Project name", project.name)
        if st.form_submit_button("Rename"):
            project.name = name.strip() or "Untitled Story"
            state.save_project()
            state.queue_toast("Renamed")
            st.rerun()

    st.divider()
    st.subheader("Export")
    components.hint("World, cast, episodes, style, and everything the story remembers.")
    include_memory = st.checkbox("Include memory", value=True)
    st.download_button(
        "⬇️ Download project (.zip)",
        data=state.get_store().export_zip(project, include_memory=include_memory),
        file_name=f"{project.name.lower().replace(' ', '_') or 'storyweaver'}.zip",
        mime="application/zip",
    )

    st.divider()
    st.subheader("Import")
    st.warning("Importing replaces the current project.")
    uploaded = st.file_uploader("Project ZIP", type="zip")
    if uploaded is not None and st.button("Import project", type="primary"):
        try:
            imported = state.get_store().import_zip(uploaded.getvalue())
            state.set_project(imported, save=False)
            st.session_state.pop(state.MEMORY, None)  # rebuilt against the restored files
            state.queue_toast(f"Imported {imported.name}")
            st.rerun()
        except (ValueError, OSError) as error:
            st.error(f"Could not import that archive: {error}")

    st.divider()
    st.subheader("Start over")

    components.hint("Two bundled starting points, either of which replaces the current project.")
    columns = st.columns(2)
    if columns[0].button("📗 Small sample (3 characters, 1 episode)"):
        state.set_project(load_sample_project())
        state.queue_toast("Sample loaded")
        st.rerun()
    if columns[1].button("📚 The Wizarding World (8 characters, 10 episodes)"):
        state.set_project(load_sample_project(config.EXAMPLES_DIR / "wizarding_world.json"))
        state.queue_toast("Wizarding World loaded")
        st.rerun()

    keep_memory = st.checkbox("Keep what the story remembers", value=False, key="keep_memory")
    confirm = st.text_input(
        "Type NEW PROJECT to confirm", key="confirm_new", placeholder="NEW PROJECT"
    )
    if st.button("🗑️ New empty project", disabled=confirm != "NEW PROJECT"):
        state.set_project(state.get_store().reset(keep_memory=keep_memory), save=False)
        st.session_state.pop(state.MEMORY, None)
        state.queue_toast("Started a new project", "🗑️")
        st.rerun()


# --- Backups and recovery --------------------------------------------------

with safety_tab:
    store = state.get_store()
    checkpoints = CheckpointStore(store.state_dir)

    st.subheader("Unfinished episodes")
    components.hint(
        "A generation that fails partway leaves its finished scenes here. Generating "
        "that episode again picks up from where it stopped."
    )
    pending = checkpoints.pending()
    if not pending:
        components.hint("Nothing is part-written.")
    for entry in pending:
        columns = st.columns([4, 1])
        columns[0].markdown(
            f"**Episode {entry.episode_number}** — {entry.scenes_completed} of "
            f"{len(entry.scenes)} scenes written"
        )
        if columns[1].button("Discard", key=f"drop_ckpt_{entry.episode_number}"):
            checkpoints.clear(entry.episode_number)
            state.queue_toast(f"Discarded the partial episode {entry.episode_number}", "🗑️")
            st.rerun()

    st.divider()
    st.subheader("Backups")
    components.hint(
        "Snapshots the memory directory — character state, story memory and plot "
        "threads. The prose lives in the project file, which the export covers."
    )

    backup_root = store.data_dir / "backups"
    if st.button("📦 Back up memory now"):
        snapshot = storage.backup_directory(store.state_dir, backup_root)
        if snapshot is None:
            st.warning("There is nothing in the memory directory to back up yet.")
        else:
            storage.prune_backups(backup_root, keep=5)
            state.queue_toast(f"Backed up to {snapshot.name}")
            st.rerun()

    if backup_root.is_dir():
        snapshots = sorted((p for p in backup_root.iterdir() if p.is_dir()), reverse=True)
        components.hint(f"{len(snapshots)} snapshot(s) kept, newest first (the last 5 are kept).")
        for snapshot in snapshots[:5]:
            st.markdown(f"- `{snapshot.name}`")
