"""Central settings for StoryWeaver.

Values are read from the environment (loaded from `.env` when present) and fall
back to the defaults below.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
EXAMPLES_DIR = DATA_DIR / "examples"
# Memory persistence (Phase 4). Both are created on first use.
CHROMA_DIR = DATA_DIR / "chromadb"
STATE_DIR = DATA_DIR / "state"

load_dotenv(PROJECT_ROOT / ".env")

# --- Model -----------------------------------------------------------------
MODEL_NAME = os.getenv("STORYWEAVER_MODEL", "gemini-3.7-flash")
TEMPERATURE = float(os.getenv("STORYWEAVER_TEMPERATURE", "0.8"))  # creative writing benefits from higher temp
MAX_OUTPUT_TOKENS = int(os.getenv("STORYWEAVER_MAX_OUTPUT_TOKENS", "8192"))

# --- Memory ---
# How many past episode summaries to inject as "the story so far".
RECENT_EPISODE_CONTEXT = int(os.getenv("STORYWEAVER_RECENT_EPISODES", "3"))
# A plot thread untouched for this many episodes counts as stale.
STALE_THREAD_EPISODES = int(os.getenv("STORYWEAVER_STALE_THREAD_EPISODES", "5"))

# --- Credentials -----------------------------------------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


def require_api_key() -> str:
    """Return the Gemini API key, raising a helpful error if it is missing."""
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return GOOGLE_API_KEY
