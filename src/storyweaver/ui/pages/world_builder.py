"""🌍 World Builder — the rules the story cannot break."""

from __future__ import annotations

import json

import streamlit as st

from storyweaver.models import Location, Rule, WorldLore
from storyweaver.ui import components, state

components.load_styles()

project = state.get_project()
world = project.world

st.title("🌍 World Builder")
components.hint(
    "Everything here is handed to every agent on every turn. Rules in particular "
    "are what the Lore Checker validates against."
)

overview_tab, rules_tab, locations_tab, extras_tab, io_tab = st.tabs(
    ["Overview", "Rules", "Locations", "Factions & lore", "Import / export"]
)

# --- Overview --------------------------------------------------------------

with overview_tab:
    with st.form("world_overview"):
        title = st.text_input("Title", world.title)
        columns = st.columns(3)
        genre = columns[0].text_input("Genre", world.genre, placeholder="fantasy, sci-fi…")
        tone = columns[1].text_input("Tone", world.tone, placeholder="dark, lighthearted…")
        era = columns[2].text_input("Era", world.era or "", placeholder="1990s Britain")
        overview = st.text_area(
            "Overview",
            world.overview,
            height=220,
            help="A few paragraphs. This is the first thing every agent reads.",
        )
        if st.form_submit_button("Save world", type="primary"):
            project.world = world.model_copy(
                update={
                    "title": title,
                    "genre": genre,
                    "tone": tone,
                    "era": era or None,
                    "overview": overview,
                }
            )
            state.save_project()
            state.queue_toast("World saved")
            st.rerun()

# --- Rules -----------------------------------------------------------------

with rules_tab:
    st.subheader(f"Rules ({len(world.rules)})")
    components.hint(
        "A rule is a promise to the reader. The Lore Checker flags any scene that "
        "breaks one, and re-runs the offending turns."
    )

    for rule in list(world.rules):
        with st.expander(f"**{rule.category}** — {rule.statement[:70]}"):
            with st.form(f"rule_{rule.id}"):
                category = st.text_input("Category", rule.category, key=f"cat_{rule.id}")
                statement = st.text_area("Statement", rule.statement, key=f"stmt_{rule.id}")
                exceptions = st.text_area(
                    "Exceptions (one per line)",
                    "\n".join(rule.exceptions),
                    key=f"exc_{rule.id}",
                )
                save, delete = st.columns([3, 1])
                if save.form_submit_button("Save", type="primary"):
                    project.upsert_rule(
                        Rule(
                            id=rule.id,
                            category=category,
                            statement=statement,
                            exceptions=[e.strip() for e in exceptions.splitlines() if e.strip()],
                        )
                    )
                    state.save_project()
                    state.queue_toast("Rule saved")
                    st.rerun()
                if delete.form_submit_button("Delete"):
                    project.remove_rule(rule.id)
                    state.save_project()
                    state.queue_toast(f"Deleted rule {rule.id}", "🗑️")
                    st.rerun()

    with st.form("new_rule", clear_on_submit=True):
        st.markdown("**Add a rule**")
        columns = st.columns([1, 3])
        new_id = columns[0].text_input("Id", placeholder="rule-wand")
        new_category = columns[1].text_input("Category", placeholder="magic, politics, physics…")
        new_statement = st.text_area("Statement", placeholder="Deliberate magic requires a wand.")
        if st.form_submit_button("Add rule", type="primary"):
            if not new_id.strip() or not new_statement.strip():
                st.error("A rule needs an id and a statement.")
            elif any(r.id == new_id for r in world.rules):
                st.error(f"There is already a rule with id {new_id!r}.")
            else:
                project.upsert_rule(
                    Rule(
                        id=new_id.strip(),
                        category=new_category.strip() or "general",
                        statement=new_statement.strip(),
                    )
                )
                state.save_project()
                state.queue_toast("Rule added")
                st.rerun()

# --- Locations -------------------------------------------------------------

with locations_tab:
    st.subheader(f"Locations ({len(world.locations)})")

    tree = project.location_tree()
    if tree:
        st.html(
            '<div class="sw-panel"><div class="sw-checklist">'
            + "".join(
                f'<div>{"&nbsp;" * (depth * 4)}{"└ " if depth else ""}'
                f"{location.name} <em>({location.id})</em></div>"
                for depth, location in tree
            )
            + "</div></div>"
        )

    location_ids = [""] + [l.id for l in world.locations]

    for location in list(world.locations):
        with st.expander(f"{location.name} ({location.id})"):
            with st.form(f"loc_{location.id}"):
                name = st.text_input("Name", location.name, key=f"lname_{location.id}")
                description = st.text_area(
                    "Description", location.description, key=f"ldesc_{location.id}"
                )
                # A location cannot be its own parent, so it is not on offer.
                options = [i for i in location_ids if i != location.id]
                current = location.parent_location_id or ""
                parent = st.selectbox(
                    "Inside",
                    options,
                    index=options.index(current) if current in options else 0,
                    format_func=lambda i: i or "— nothing —",
                    key=f"lparent_{location.id}",
                )
                features = st.text_area(
                    "Notable features (one per line)",
                    "\n".join(location.notable_features),
                    key=f"lfeat_{location.id}",
                )
                save, delete = st.columns([3, 1])
                if save.form_submit_button("Save", type="primary"):
                    project.upsert_location(
                        Location(
                            id=location.id,
                            name=name,
                            description=description,
                            parent_location_id=parent or None,
                            notable_features=[
                                f.strip() for f in features.splitlines() if f.strip()
                            ],
                        )
                    )
                    state.save_project()
                    state.queue_toast("Location saved")
                    st.rerun()
                if delete.form_submit_button("Delete"):
                    project.remove_location(location.id)
                    state.save_project()
                    state.queue_toast(f"Deleted {location.id}", "🗑️")
                    st.rerun()

    with st.form("new_location", clear_on_submit=True):
        st.markdown("**Add a location**")
        columns = st.columns([1, 2, 2])
        new_id = columns[0].text_input("Id", placeholder="great-hall")
        new_name = columns[1].text_input("Name", placeholder="The Great Hall")
        new_parent = columns[2].selectbox(
            "Inside", location_ids, format_func=lambda i: i or "— nothing —"
        )
        new_description = st.text_area("Description")
        if st.form_submit_button("Add location", type="primary"):
            if not new_id.strip() or not new_name.strip():
                st.error("A location needs an id and a name.")
            elif any(l.id == new_id for l in world.locations):
                st.error(f"There is already a location with id {new_id!r}.")
            else:
                project.upsert_location(
                    Location(
                        id=new_id.strip(),
                        name=new_name.strip(),
                        description=new_description.strip(),
                        parent_location_id=new_parent or None,
                    )
                )
                state.save_project()
                state.queue_toast("Location added")
                st.rerun()

# --- Factions and free-form lore -------------------------------------------

with extras_tab:
    with st.form("factions"):
        st.subheader("Factions")
        factions = st.text_area(
            "One per line", "\n".join(world.factions), height=140
        )
        if st.form_submit_button("Save factions", type="primary"):
            world.factions = [f.strip() for f in factions.splitlines() if f.strip()]
            state.save_project()
            state.queue_toast("Factions saved")
            st.rerun()

    with st.form("additional_lore"):
        st.subheader("Additional lore")
        components.hint("Free-form key/value entries — anything the other fields have no room for.")
        text = st.text_area(
            "One `key: value` per line",
            "\n".join(f"{k}: {v}" for k, v in world.additional_lore.items()),
            height=180,
        )
        if st.form_submit_button("Save lore", type="primary"):
            entries = {}
            for line in text.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key.strip():
                        entries[key.strip()] = value.strip()
            world.additional_lore = entries
            state.save_project()
            state.queue_toast("Lore saved")
            st.rerun()

# --- Import / export -------------------------------------------------------

with io_tab:
    st.subheader("Export")
    st.download_button(
        "⬇️ Download world as JSON",
        data=world.model_dump_json(indent=2),
        file_name=f"{world.title.lower().replace(' ', '_') or 'world'}.json",
        mime="application/json",
    )

    st.subheader("Import")
    st.warning("Importing replaces the current world entirely.")
    uploaded = st.file_uploader("World JSON", type="json", key="world_upload")
    if uploaded is not None and st.button("Replace world", type="primary"):
        try:
            raw = json.loads(uploaded.getvalue().decode("utf-8"))
            project.world = WorldLore.model_validate(raw.get("world", raw))
            state.save_project()
            state.queue_toast("World imported")
            st.rerun()
        except (ValueError, UnicodeDecodeError) as error:
            st.error(f"That file is not a world: {error}")
