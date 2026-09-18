"""The StoryWeaver HTTP API.

Run it with:

    uvicorn storyweaver.server:app --reload --port 8000

and read the generated docs at http://localhost:8000/docs.

This is a wrapper, not a rewrite: every route calls the same `Project`,
`episode_runner`, `MemoryManager` and `export` code the Streamlit workbench
calls, against the same `data/` directory.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from storyweaver import __version__, config
from storyweaver.api import ROUTERS, deps, generation

logger = logging.getLogger(__name__)

# The Vite dev server, on the two hosts it answers to, plus the port a
# `next dev` or `vite preview` setup usually takes.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Make sure the data directory exists, and say what came up."""
    store = deps.get_store()
    store.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("StoryWeaver API serving %s", store.data_dir)

    # Nothing can be generating in a process that has only just started, so an
    # episode still marked "in progress" was stranded by a previous one — a
    # crash, a Ctrl+C, a reload. Put it back in the queue; its checkpoint, if
    # any, is kept, so generating it again resumes rather than starts over.
    recovered = generation.recover_interrupted()
    if recovered:
        logger.warning(
            "Episode(s) %s were left in progress by a previous run; back in the queue",
            ", ".join(str(n) for n in recovered),
        )

    # Probed once at boot rather than on the first request that needs it:
    # ChromaDB downloads an embedding model the first time, and an author
    # should not meet that delay in the middle of a search.
    if deps.get_memory() is None:
        logger.warning("The memory layer did not start: %s", deps.memory_error())

    if not config.GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY is unset — generation will fail until it is filled in")

    yield


app = FastAPI(
    title="StoryWeaver API",
    version="0.2.0",
    description="Multi-agent long-form fiction generation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in ROUTERS:
    app.include_router(router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Is the backend up, and does it have what it needs to write anything?"""
    return {
        "status": "ok",
        "version": __version__,
        "api_version": app.version,
        "model": config.MODEL_NAME,
        "api_key_configured": bool(config.GOOGLE_API_KEY),
        "memory_available": deps.get_memory() is not None,
        "memory_error": deps.memory_error(),
        "data_dir": str(deps.get_store().data_dir),
    }
