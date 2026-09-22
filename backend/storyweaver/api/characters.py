"""Character profiles, cloning, and the relationship graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from storyweaver.api import deps
from storyweaver.wiki import record_character_edit
from storyweaver.models import CharacterProfile
from storyweaver.ui.project import Project

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CloneRequest(BaseModel):
    new_id: str
    new_name: str


@router.get("", response_model=list[CharacterProfile])
def list_characters(project: Project = Depends(deps.get_project)) -> list[CharacterProfile]:
    return project.characters


@router.get("/graph")
def relationship_graph(project: Project = Depends(deps.get_project)) -> dict:
    """The cast as a network, shaped for a node-link view.

    A character with no `role` set falls back to their strongest trait, so a
    node imported from an older project still has something to label it with.
    """
    nodes = []
    for character in project.characters:
        strongest = max(character.traits, key=lambda t: t.intensity, default=None)
        nodes.append(
            {
                "id": character.id,
                "label": character.name,
                "role": character.role or (strongest.name if strongest else ""),
                "degree": len(character.relationships),
            }
        )

    known = {c.id for c in project.characters}
    edges = [
        {
            "source": character.id,
            "target": relationship.target_character_id,
            "type": relationship.type,
            "sentiment": relationship.sentiment,
            "description": relationship.description or "",
        }
        for character in project.characters
        for relationship in character.relationships
        # An edge to someone who is not in the cast has nothing to draw to.
        if relationship.target_character_id in known
    ]
    return {"nodes": nodes, "edges": edges}


@router.post("", response_model=CharacterProfile)
def upsert_character(character: CharacterProfile) -> CharacterProfile:
    """Add a character, or replace the one with the same id.

    An edit to a field the story has already changed becomes the next entry in
    that field's history. Without that the save would appear to work and the
    next chapter would still use the chronicle's value — the edit silently
    thrown away.
    """
    with deps.write_lock():
        project = deps.get_project()
        project.upsert_character(character)
        deps.save_project(project)
        memory = deps.get_memory()
        if memory is not None:
            record_character_edit(memory.chronicle, character)
    return character


@router.delete("/{character_id}", response_model=list[CharacterProfile])
def delete_character(character_id: str) -> list[CharacterProfile]:
    """Delete a character, and every relationship pointing at them.

    Leaving dangling targets behind would put ids into prompts that no longer
    resolve to anyone.
    """
    with deps.write_lock():
        project = deps.get_project()
        deps.require_character(project, character_id)
        project.remove_character(character_id)
        deps.save_project(project)
    return project.characters


@router.post("/{character_id}/clone", response_model=CharacterProfile)
def clone_character(character_id: str, request: CloneRequest) -> CharacterProfile:
    """Duplicate a character as the starting point for a new one."""
    with deps.write_lock():
        project = deps.get_project()
        deps.require_character(project, character_id)
        try:
            clone = project.clone_character(character_id, request.new_id, request.new_name)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        deps.save_project(project)
    return clone
