"""FastAPI routers wrapping the StoryWeaver core.

Nothing in here knows about agents, LangGraph or ChromaDB directly: the routes
call the same `Project`, `episode_runner`, `MemoryManager` and `export` code the
Streamlit app calls, so the two front ends cannot drift apart.
"""

from storyweaver.api import (
    characters,
    episodes,
    export,
    generation,
    memory,
    project,
    telemetry,
    world,
)

ROUTERS = [
    project.router,
    world.router,
    characters.router,
    episodes.router,
    generation.router,
    memory.router,
    export.router,
    telemetry.router,
]

__all__ = ["ROUTERS"]
