"""Memory inspector: plot threads, and semantic search over what the story remembers."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from storyweaver import config
from storyweaver.api import deps
from storyweaver.memory import vector_store as vs

router = APIRouter(prefix="/api/memory", tags=["memory"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    character_id: str | None = None
    collections: list[str] | None = None


@router.get("/status")
def memory_status() -> dict:
    """Whether the memory layer came up, and how much is in it."""
    memory = deps.get_memory()
    if memory is None:
        return {"available": False, "error": deps.memory_error(), "collections": {}}
    return {
        "available": True,
        "error": "",
        "collections": {name: memory.vector_store.count(name) for name in vs.COLLECTIONS},
        "is_empty": memory.is_empty(),
    }


@router.get("/threads")
def plot_threads(current_episode: int | None = Query(default=None)) -> dict:
    """Every 떡밥 the story has raised, split by where it stands.

    `stale` is a subset of the open ones: threads quiet long enough that a
    reader would start to think they were dropped.
    """
    memory = deps.require_memory()
    threads = memory.plot_tracker.all()
    stale_ids = {
        thread.id
        for thread in memory.get_stale_plot_threads(current_episode=current_episode)
    }
    return {
        "active": [t.model_dump() for t in threads if t.status != "resolved"],
        "resolved": [t.model_dump() for t in threads if t.status == "resolved"],
        "stale": [t.model_dump() for t in threads if t.id in stale_ids],
        "stale_after_episodes": config.STALE_THREAD_EPISODES,
    }


@router.post("/query")
def search_memory(request: QueryRequest) -> dict:
    """Semantic search across the vector store, nearest first.

    Distance is what Chroma returns — smaller is closer. `relevance` is that
    turned the way round a reader expects, so 1.0 is a perfect match.
    """
    memory = deps.require_memory()
    found = memory.search(
        request.query,
        collections=request.collections or vs.COLLECTIONS,
        top_k=request.top_k,
        character_id=request.character_id,
    )
    return {
        "query": request.query,
        "results": [
            {
                "id": item.id,
                "document": item.document,
                "rendered": item.render(),
                "collection": item.collection,
                "episode_number": item.episode_number,
                "metadata": item.metadata,
                "distance": item.distance,
                "relevance": None if item.distance is None else 1.0 / (1.0 + item.distance),
            }
            for item in found
        ],
    }


@router.get("/characters/{character_id}")
def character_state(character_id: str) -> dict:
    """What the story remembers about one character, as opposed to what the
    author wrote down: goals, mood and relationships as of the last episode."""
    memory = deps.require_memory()
    return memory.get_character_state(character_id).model_dump()


@router.get("/episodes/{episode_number}/summary")
def episode_summary(episode_number: int) -> dict:
    memory = deps.require_memory()
    return {
        "episode_number": episode_number,
        "summary": memory.get_episode_summary(episode_number),
    }
