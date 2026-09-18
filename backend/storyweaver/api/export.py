"""Downloads: one chapter, the whole book, or the project archive."""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from storyweaver import export as exporters
from storyweaver.api import deps
from storyweaver.ui.project import Project

router = APIRouter(prefix="/api/export", tags=["export"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attachment(content: bytes | str, filename: str, media_type: str) -> Response:
    """A download, with a filename that survives non-Latin characters.

    A Korean chapter title in a bare `filename=` is mojibake in most browsers,
    so the ASCII fallback is spelled out and the real name goes in `filename*`.
    """
    body = content.encode("utf-8") if isinstance(content, str) else content
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "download"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


def _completed_or_404(project: Project, episode_number: int):
    episode = deps.require_episode(project, episode_number)
    if not episode.final_text.strip():
        raise HTTPException(
            status_code=409, detail=f"Episode {episode_number} has not been written yet"
        )
    return episode


@router.get("/episode/{episode_number}/markdown")
def episode_markdown(
    episode_number: int, project: Project = Depends(deps.get_project)
) -> Response:
    episode = _completed_or_404(project, episode_number)
    return _attachment(
        exporters.to_markdown(episode), f"episode_{episode_number}.md", "text/markdown"
    )


@router.get("/episode/{episode_number}/text")
def episode_text(episode_number: int, project: Project = Depends(deps.get_project)) -> Response:
    episode = _completed_or_404(project, episode_number)
    return _attachment(
        exporters.to_text(episode), f"episode_{episode_number}.txt", "text/plain"
    )


@router.get("/episode/{episode_number}/docx")
def episode_docx(episode_number: int, project: Project = Depends(deps.get_project)) -> Response:
    episode = _completed_or_404(project, episode_number)
    return _attachment(
        exporters.to_docx(episode), f"episode_{episode_number}.docx", DOCX_MIME
    )


def _book_name(project: Project) -> str:
    return (project.name.strip().lower().replace(" ", "_") or "story")


@router.get("/story/markdown")
def story_markdown(
    appendices: bool = Query(default=True),
    project: Project = Depends(deps.get_project),
) -> Response:
    """The whole book as one Markdown file, with contents and appendices."""
    document = exporters.assemble_story(
        project.name,
        project.completed_episodes(),
        project.characters,
        project.world,
        include_appendices=appendices,
    )
    return _attachment(document, f"{_book_name(project)}.md", "text/markdown")


@router.get("/story/docx")
def story_docx(
    appendices: bool = Query(default=True),
    project: Project = Depends(deps.get_project),
) -> Response:
    document = exporters.story_to_docx(
        project.name,
        project.completed_episodes(),
        project.characters,
        project.world,
        include_appendices=appendices,
    )
    return _attachment(document, f"{_book_name(project)}.docx", DOCX_MIME)


@router.get("/project/zip")
def project_zip(
    include_memory: bool = Query(default=True),
    project: Project = Depends(deps.get_project),
) -> Response:
    """The project itself: the authored JSON plus everything it remembers."""
    archive = deps.get_store().export_zip(project, include_memory=include_memory)
    return _attachment(archive, f"{_book_name(project)}.zip", "application/zip")
