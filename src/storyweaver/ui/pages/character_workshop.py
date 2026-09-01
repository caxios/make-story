"""👤 Character Workshop — who these people are, and how they feel about each other."""

from __future__ import annotations

import json

import streamlit as st

from storyweaver.models import CharacterProfile, Relationship, Trait
from storyweaver.ui import components, state

components.load_styles()

project = state.get_project()

st.title("👤 Character Workshop")

if not project.characters:
    components.hint("No characters yet. Create one below — a name and a voice is enough to start.")

# --- Selection -------------------------------------------------------------

with st.sidebar:
    st.markdown("#### Cast")
    options = [c.id for c in project.characters] + ["➕ New character"]
    selected = st.radio(
        "Character",
        options,
        format_func=lambda i: project.get_character(i).name if project.get_character(i) else i,
        label_visibility="collapsed",
    )

character = project.get_character(selected)


def _relationship_graph(project) -> str:
    """A Mermaid graph of who feels what about whom.

    Edge labels carry the sentiment, because the number is the part an author
    actually tunes — the type alone ("rival") hides whether it is warming.
    """
    lines = ["graph LR"]
    for person in project.characters:
        lines.append(f'  {_node(person.id)}["{person.name}"]')
    for person in project.characters:
        for relationship in person.relationships:
            target = project.get_character(relationship.target_character_id)
            if target is None:
                continue
            lines.append(
                f"  {_node(person.id)} -->|{relationship.type} "
                f"{relationship.sentiment:+.1f}| {_node(target.id)}"
            )
    return "\n".join(lines)


def _node(character_id: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in character_id)


# --- New character ---------------------------------------------------------

if character is None:
    st.subheader("New character")

    if project.characters:
        with st.form("clone_character"):
            st.markdown("**Clone an existing one**")
            columns = st.columns(3)
            source = columns[0].selectbox(
                "Based on",
                [c.id for c in project.characters],
                format_func=lambda i: project.get_character(i).name,
            )
            clone_id = columns[1].text_input("New id", placeholder="draco-malfoy")
            clone_name = columns[2].text_input("New name", placeholder="Draco Malfoy")
            if st.form_submit_button("Clone"):
                try:
                    project.clone_character(source, clone_id.strip(), clone_name.strip())
                    state.save_project()
                    state.queue_toast(f"Cloned into {clone_id}")
                    st.rerun()
                except (KeyError, ValueError) as error:
                    st.error(str(error))

    with st.form("new_character", clear_on_submit=True):
        st.markdown("**From scratch**")
        columns = st.columns(2)
        new_id = columns[0].text_input("Id", placeholder="harry-potter")
        new_name = columns[1].text_input("Name", placeholder="Harry Potter")
        appearance = st.text_area("Appearance", placeholder="What someone would notice first.")
        personality = st.text_area("Personality summary", placeholder="A short paragraph.")
        speech = st.text_area(
            "Speech style",
            placeholder="Dialect, formality, verbal tics — how you would recognise them unlabelled.",
        )
        if st.form_submit_button("Create character", type="primary"):
            if not new_id.strip() or not new_name.strip():
                st.error("A character needs an id and a name.")
            elif project.get_character(new_id.strip()):
                st.error(f"There is already a character with id {new_id!r}.")
            else:
                project.upsert_character(
                    CharacterProfile(
                        id=new_id.strip(),
                        name=new_name.strip(),
                        appearance=appearance.strip(),
                        personality_summary=personality.strip(),
                        speech_style=speech.strip(),
                    )
                )
                state.save_project()
                state.queue_toast(f"Created {new_name}")
                st.rerun()

    if project.characters:
        st.subheader("Relationships")
        st.markdown(f"```mermaid\n{_relationship_graph(project)}\n```")

    st.stop()

# --- Edit ------------------------------------------------------------------

st.subheader(character.name)

identity_tab, traits_tab, relations_tab, secrets_tab, io_tab = st.tabs(
    ["Identity", "Traits & goals", "Relationships", "Secrets", "Import / export"]
)

with identity_tab:
    with st.form("identity"):
        columns = st.columns(3)
        name = columns[0].text_input("Name", character.name)
        age = columns[1].number_input(
            "Age", value=character.age if character.age is not None else 0, min_value=0
        )
        gender = columns[2].text_input("Gender", character.gender or "")
        aliases = st.text_input("Aliases (comma separated)", ", ".join(character.aliases))
        appearance = st.text_area("Appearance", character.appearance, height=110)
        personality = st.text_area("Personality summary", character.personality_summary, height=140)
        speech = st.text_area("Speech style", character.speech_style, height=110)
        if speech.strip():
            components.hint(f"The Writer is told to preserve this exactly: “{speech.strip()}”")
        backstory = st.text_area("Backstory", character.backstory, height=140)
        notes = st.text_area(
            "Author notes",
            character.author_notes,
            height=90,
            help="Guidance for the system. Never shown as story text.",
        )
        if st.form_submit_button("Save", type="primary"):
            project.upsert_character(
                character.model_copy(
                    update={
                        "name": name,
                        "age": int(age) or None,
                        "gender": gender or None,
                        "aliases": [a.strip() for a in aliases.split(",") if a.strip()],
                        "appearance": appearance,
                        "personality_summary": personality,
                        "speech_style": speech,
                        "backstory": backstory,
                        "author_notes": notes,
                    }
                )
            )
            state.save_project()
            state.queue_toast("Character saved")
            st.rerun()

    st.divider()
    if st.button(f"🗑️ Delete {character.name}"):
        project.remove_character(character.id)
        state.save_project()
        state.queue_toast(f"Deleted {character.name}", "🗑️")
        st.rerun()

with traits_tab:
    with st.form("traits"):
        st.markdown("**Traits**")
        components.hint("Intensity reaches the prompt as a number, so 0.9 really does read louder than 0.4.")
        traits = []
        for index, trait in enumerate(character.traits):
            columns = st.columns([2, 2, 3, 1])
            trait_name = columns[0].text_input("Name", trait.name, key=f"tn_{index}")
            intensity = columns[1].slider(
                "Intensity", 0.0, 1.0, trait.intensity, 0.05, key=f"ti_{index}"
            )
            description = columns[2].text_input(
                "Description", trait.description or "", key=f"td_{index}"
            )
            keep = not columns[3].checkbox("Drop", key=f"tx_{index}")
            if keep and trait_name.strip():
                traits.append(
                    Trait(
                        name=trait_name.strip(),
                        intensity=intensity,
                        description=description.strip() or None,
                    )
                )

        st.markdown("**Add a trait**")
        columns = st.columns([2, 2, 3])
        add_name = columns[0].text_input("Name", key="new_trait_name")
        add_intensity = columns[1].slider("Intensity", 0.0, 1.0, 0.8, 0.05, key="new_trait_int")
        add_description = columns[2].text_input("Description", key="new_trait_desc")

        values = st.text_area("What they value (one per line)", "\n".join(character.values))
        goals = st.text_area("Current goals (one per line)", "\n".join(character.goals))

        if st.form_submit_button("Save", type="primary"):
            if add_name.strip():
                traits.append(
                    Trait(
                        name=add_name.strip(),
                        intensity=add_intensity,
                        description=add_description.strip() or None,
                    )
                )
            project.upsert_character(
                character.model_copy(
                    update={
                        "traits": traits,
                        "values": [v.strip() for v in values.splitlines() if v.strip()],
                        "goals": [g.strip() for g in goals.splitlines() if g.strip()],
                    }
                )
            )
            state.save_project()
            state.queue_toast("Traits saved")
            st.rerun()

with relations_tab:
    others = [c.id for c in project.characters if c.id != character.id]

    if not others:
        components.hint("Relationships need somebody else in the cast.")
    else:
        with st.form("relationships"):
            st.markdown(f"**How {character.name} sees the others**")
            components.hint("Sentiment runs from −1.0 (hatred) to +1.0 (love).")
            relationships = []
            for index, relationship in enumerate(character.relationships):
                columns = st.columns([2, 2, 3, 3, 1])
                target = columns[0].selectbox(
                    "Toward",
                    others,
                    index=others.index(relationship.target_character_id)
                    if relationship.target_character_id in others
                    else 0,
                    format_func=lambda i: project.get_character(i).name,
                    key=f"rt_{index}",
                )
                kind = columns[1].text_input("Type", relationship.type, key=f"rk_{index}")
                sentiment = columns[2].slider(
                    "Sentiment", -1.0, 1.0, relationship.sentiment, 0.05, key=f"rs_{index}"
                )
                description = columns[3].text_input(
                    "Nuance", relationship.description or "", key=f"rd_{index}"
                )
                keep = not columns[4].checkbox("Drop", key=f"rx_{index}")
                if keep:
                    relationships.append(
                        Relationship(
                            target_character_id=target,
                            type=kind.strip() or "acquaintance",
                            sentiment=sentiment,
                            description=description.strip() or None,
                        )
                    )

            st.markdown("**Add a relationship**")
            columns = st.columns([2, 2, 3, 3])
            add_target = columns[0].selectbox(
                "Toward",
                [""] + others,
                format_func=lambda i: project.get_character(i).name if i else "— pick one —",
                key="new_rel_target",
            )
            add_kind = columns[1].text_input("Type", key="new_rel_kind", placeholder="friend, rival…")
            add_sentiment = columns[2].slider("Sentiment", -1.0, 1.0, 0.0, 0.05, key="new_rel_sent")
            add_description = columns[3].text_input("Nuance", key="new_rel_desc")

            if st.form_submit_button("Save", type="primary"):
                if add_target:
                    relationships.append(
                        Relationship(
                            target_character_id=add_target,
                            type=add_kind.strip() or "acquaintance",
                            sentiment=add_sentiment,
                            description=add_description.strip() or None,
                        )
                    )
                project.upsert_character(
                    character.model_copy(update={"relationships": relationships})
                )
                state.save_project()
                state.queue_toast("Relationships saved")
                st.rerun()

    st.subheader("Relationship graph")
    components.hint("Arrows point from the character who holds the feeling.")
    st.markdown(f"```mermaid\n{_relationship_graph(project)}\n```")

with secrets_tab:
    components.hint(
        "Secrets go into the character's own prompt with an instruction not to reveal them "
        "unless the story demands it. They never reach the other characters' prompts."
    )
    with st.form("secrets"):
        secrets = st.text_area(
            "Secrets (one per line)", "\n".join(character.secrets), height=180
        )
        if st.form_submit_button("Save", type="primary"):
            project.upsert_character(
                character.model_copy(
                    update={"secrets": [s.strip() for s in secrets.splitlines() if s.strip()]}
                )
            )
            state.save_project()
            state.queue_toast("Secrets saved")
            st.rerun()

with io_tab:
    st.download_button(
        "⬇️ Download all characters as JSON",
        data=json.dumps(
            [c.model_dump(mode="json") for c in project.characters], indent=2, ensure_ascii=False
        ),
        file_name="characters.json",
        mime="application/json",
    )

    st.subheader("Import")
    components.hint("Characters with matching ids are replaced; the rest are added.")
    uploaded = st.file_uploader("Characters JSON", type="json", key="chars_upload")
    if uploaded is not None and st.button("Import characters", type="primary"):
        try:
            raw = json.loads(uploaded.getvalue().decode("utf-8"))
            incoming = raw.get("characters", raw) if isinstance(raw, dict) else raw
            for entry in incoming:
                project.upsert_character(CharacterProfile.model_validate(entry))
            state.save_project()
            state.queue_toast(f"Imported {len(incoming)} characters")
            st.rerun()
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            st.error(f"That file is not a character list: {error}")
