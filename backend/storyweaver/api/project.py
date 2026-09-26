"""Project state, metadata, and the dashboard numbers."""

from __future__ import annotations

import logging
import shutil
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.ui.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project", tags=["project"])


@router.get("", response_model=Project)
def read_project(project: Project = Depends(deps.get_project)) -> Project:
    """Everything the author has authored: world, cast, queue and style."""
    return project


@router.put("", response_model=Project)
def replace_project(incoming: Project) -> Project:
    """Overwrite the project wholesale and write it to disk."""
    return deps.save_project(incoming)


@router.post("/reset", response_model=Project)
def reset_project() -> Project:
    """Start a new work: an empty project, and nothing remembered from the old one.

    Clears the world, cast, queue, wiki and memory. The one thing kept is the
    concept session, because the usual reason to reset is that a new concept is
    waiting to be committed, and wiping it here would throw away exactly what
    the author reset *for*.

    Refused while a chapter is being written — pulling the memory out from
    under a running generation would leave it writing into nothing.
    """
    from storyweaver.api.generation import running_generations

    if running_generations():
        raise HTTPException(
            status_code=409,
            detail="회차를 집필하는 중에는 초기화할 수 없습니다. 끝나거나 멈춘 뒤에 해 주세요.",
        )

    with deps.write_lock():
        store = deps.get_store()
        concepts = ConceptStore(store.state_dir)
        session = concepts.load()
        # How the author writes is theirs, not the old story's.
        previous = store.load()

        memory = deps.get_memory()
        if memory is None:
            project = store.reset(keep_memory=False)
        else:
            # ChromaDB's files are open while the server runs, and on Windows an
            # open file cannot be deleted — removing the folder would fail
            # quietly and leave the old story's memories in place. So the
            # collections are emptied through the client that holds them.
            memory.vector_store.reset()
            project = store.reset(keep_memory=True)
            shutil.rmtree(store.state_dir, ignore_errors=True)
            memory.plot_tracker.load()  # it caches threads in memory

        project.style = previous.style
        project.review_chronicle = previous.review_chronicle
        store.save(project)

        if session is not None:
            if session.status == "committed":
                session.status = "refining" if session.chosen else "proposing"
                session.committed_at = None
            concepts.save(session)

    logger.info("Project reset; concept session %s", "kept" if session else "absent")
    return project


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
