"""World lore: the overview, its rules, and the location hierarchy."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from storyweaver.api import deps
from storyweaver.models import Location, Rule, WorldLore
from storyweaver.ui.project import Project

router = APIRouter(prefix="/api/world", tags=["world"])


class WorldUpdate(BaseModel):
    """A partial edit of the world header. Omitted fields are left alone."""

    title: str | None = None
    genre: str | None = None
    tone: str | None = None
    era: str | None = None
    overview: str | None = None
    factions: list[str] | None = None


@router.get("", response_model=WorldLore)
def read_world(project: Project = Depends(deps.get_project)) -> WorldLore:
    return project.world


@router.put("", response_model=WorldLore)
def update_world(update: WorldUpdate) -> WorldLore:
    with deps.write_lock():
        project = deps.get_project()
        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(project.world, field, value)
        deps.save_project(project)
    return project.world


# --- Rules -----------------------------------------------------------------


@router.post("/rules", response_model=WorldLore)
def upsert_rule(rule: Rule) -> WorldLore:
    """Add a rule, or replace the one with the same id."""
    with deps.write_lock():
        project = deps.get_project()
        project.upsert_rule(rule)
        deps.save_project(project)
    return project.world


@router.delete("/rules/{rule_id}", response_model=WorldLore)
def delete_rule(rule_id: str) -> WorldLore:
    with deps.write_lock():
        project = deps.get_project()
        if not any(r.id == rule_id for r in project.world.rules):
            raise HTTPException(status_code=404, detail=f"No rule with id {rule_id!r}")
        project.remove_rule(rule_id)
        deps.save_project(project)
    return project.world


# --- Locations -------------------------------------------------------------


@router.post("/locations", response_model=WorldLore)
def upsert_location(location: Location) -> WorldLore:
    """Add a location, or replace the one with the same id."""
    with deps.write_lock():
        project = deps.get_project()
        project.upsert_location(location)
        deps.save_project(project)
    return project.world


@router.delete("/locations/{location_id}", response_model=WorldLore)
def delete_location(location_id: str) -> WorldLore:
    """Delete a location; anything nested inside it moves up to the root."""
    with deps.write_lock():
        project = deps.get_project()
        if not any(l.id == location_id for l in project.world.locations):
            raise HTTPException(status_code=404, detail=f"No location with id {location_id!r}")
        project.remove_location(location_id)
        deps.save_project(project)
    return project.world


@router.get("/locations/tree")
def location_tree(project: Project = Depends(deps.get_project)) -> list[dict]:
    """Locations flattened parents-first, each with its nesting depth."""
    return [
        {"depth": depth, "location": location.model_dump()}
        for depth, location in project.location_tree()
    ]
