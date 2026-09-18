"""Project state, metadata, and the dashboard numbers."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from storyweaver.api import deps
from storyweaver.ui.project import Project

router = APIRouter(prefix="/api/project", tags=["project"])


@router.get("", response_model=Project)
def read_project(project: Project = Depends(deps.get_project)) -> Project:
    """Everything the author has authored: world, cast, queue and style."""
    return project


@router.put("", response_model=Project)
def replace_project(incoming: Project) -> Project:
    """Overwrite the project wholesale and write it to disk."""
    return deps.save_project(incoming)


@router.get("/stats")
def read_stats(project: Project = Depends(deps.get_project)) -> dict:
    """The dashboard counters.

    The open-thread count needs the memory layer; without it the rest of the
    numbers are still worth having, so it reports zero rather than failing.
    """
    memory = deps.get_memory()
    open_threads = len(memory.get_active_plot_threads()) if memory else 0
    stats = asdict(project.stats(open_thread_count=open_threads))
    stats["memory_available"] = memory is not None
    stats["memory_error"] = deps.memory_error()
    return stats
