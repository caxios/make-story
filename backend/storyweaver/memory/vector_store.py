"""ChromaDB wrapper: three collections, one semantic-search surface.

Chroma metadata values must be scalars, but the things worth filtering on here
are lists (participants, locations) and maps (emotional impact). Non-scalars are
stored as tagged JSON and decoded on the way out, so callers deal in real
Python values and never see the encoding.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storyweaver.models import InteractionRecord, WorldLore

logger = logging.getLogger(__name__)

EPISODE_SUMMARIES = "episode_summaries"
INTERACTION_RECORDS = "interaction_records"
WORLD_LORE = "world_lore"
COLLECTIONS = (EPISODE_SUMMARIES, INTERACTION_RECORDS, WORLD_LORE)

_JSON_TAG = "__json__:"
# Post-filtering by participant happens in Python (Chroma cannot match inside a
# list), so ask for more candidates than we intend to keep.
OVERFETCH = 4


@dataclass(frozen=True)
class Memory:
    """One retrieved memory, with enough context to be quoted in a prompt."""

    id: str
    document: str
    metadata: dict[str, Any]
    collection: str
    distance: float | None = None

    @property
    def episode_number(self) -> int:
        return int(self.metadata.get("episode_number", 0))

    def render(self) -> str:
        episode = self.episode_number
        prefix = f"(Episode {episode}) " if episode else ""
        return f"{prefix}{self.document}"


def _encode(value: Any) -> Any:
    """Scalars pass through; anything else becomes tagged JSON."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _JSON_TAG + json.dumps(value, ensure_ascii=False)


def _decode(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_JSON_TAG):
        try:
            return json.loads(value[len(_JSON_TAG):])
        except json.JSONDecodeError:
            logger.warning("Could not decode stored metadata value; returning it raw")
    return value


def encode_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _encode(v) for k, v in metadata.items() if v is not None}


def decode_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: _decode(v) for k, v in (metadata or {}).items()}


class VectorStore:
    """The three semantic collections, wrapped in one object.

    `client` and `embedding_function` are injectable: tests use an in-memory
    client and a deterministic embedder so the suite never downloads a model or
    touches the network.
    """

    def __init__(self, path: Path | str | None = None, client=None, embedding_function=None):
        if client is None:
            import chromadb

            if path is None:
                from storyweaver import config

                path = config.CHROMA_DIR
            Path(path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(path))

        self.client = client
        self.embedding_function = embedding_function
        self._collections: dict[str, Any] = {}

    def collection(self, name: str):
        if name not in self._collections:
            kwargs = {}
            if self.embedding_function is not None:
                kwargs["embedding_function"] = self.embedding_function
            self._collections[name] = self.client.get_or_create_collection(name, **kwargs)
        return self._collections[name]

    def count(self, name: str) -> int:
        return self.collection(name).count()

    # --- writes ------------------------------------------------------------

    def add(
        self,
        collection: str,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]],
    ) -> None:
        """Upsert documents, so re-recording an episode corrects it rather than duplicating it."""
        if not ids:
            return
        self.collection(collection).upsert(
            ids=list(ids),
            documents=list(documents),
            metadatas=[encode_metadata(m) for m in metadatas],
        )

    def add_episode_summary(
        self,
        episode_number: int,
        summary: str,
        characters_involved: Sequence[str] = (),
        locations: Sequence[str] = (),
        key_events: Sequence[str] = (),
        mood: str = "",
    ) -> None:
        self.add(
            EPISODE_SUMMARIES,
            ids=[f"episode_{episode_number}"],
            documents=[summary],
            metadatas=[
                {
                    "episode_number": episode_number,
                    "characters_involved": list(characters_involved),
                    "locations": list(locations),
                    "key_events": list(key_events),
                    "mood": mood,
                }
            ],
        )

    def add_interaction_records(
        self, records: Iterable[InteractionRecord], types: Mapping[int, str] | None = None
    ) -> int:
        """Store one document per meaningful interaction. Returns how many landed."""
        ids, documents, metadatas = [], [], []
        for index, record in enumerate(records):
            ids.append(
                f"ep{record.episode_number}_scene{record.scene_number}_interaction_{index}"
            )
            documents.append(record.summary)
            metadatas.append(
                {
                    "episode_number": record.episode_number,
                    "scene_number": record.scene_number,
                    "participants": list(record.participants),
                    "type": (types or {}).get(index, "interaction"),
                    "emotional_impact": dict(record.emotional_impact),
                    "plot_threads": list(record.plot_threads_opened)
                    + list(record.plot_threads_resolved),
                }
            )
        self.add(INTERACTION_RECORDS, ids, documents, metadatas)
        return len(ids)

    def seed_world_lore(self, world: WorldLore, episode_introduced: int = 0) -> int:
        """Load the author's world into the lore collection. Safe to re-run."""
        ids, documents, metadatas = [], [], []

        ids.append("world_overview")
        documents.append(f"{world.title} ({world.genre}, {world.tone}). {world.overview}")
        metadatas.append({"category": "overview", "source": "author_defined",
                          "episode_introduced": episode_introduced})

        for rule in world.rules:
            text = rule.statement
            if rule.exceptions:
                text += " Exceptions: " + "; ".join(rule.exceptions)
            ids.append(f"rule_{rule.id}")
            documents.append(text)
            metadatas.append({"category": rule.category, "source": "author_defined",
                              "episode_introduced": episode_introduced})

        for location in world.locations:
            text = f"{location.name}: {location.description}"
            if location.notable_features:
                text += " Notable: " + ", ".join(location.notable_features)
            ids.append(f"location_{location.id}")
            documents.append(text)
            metadatas.append({"category": "location", "source": "author_defined",
                              "location_id": location.id,
                              "episode_introduced": episode_introduced})

        for faction in world.factions:
            ids.append(f"faction_{faction.lower().replace(' ', '_')}")
            documents.append(f"{faction} is a faction in {world.title}.")
            metadatas.append({"category": "faction", "source": "author_defined",
                              "episode_introduced": episode_introduced})

        for key, value in world.additional_lore.items():
            ids.append(f"lore_{key}")
            documents.append(f"{key}: {value}")
            metadatas.append({"category": key, "source": "author_defined",
                              "episode_introduced": episode_introduced})

        self.add(WORLD_LORE, ids, documents, metadatas)
        return len(ids)

    def add_lore(
        self, entry_id: str, text: str, category: str = "revealed",
        episode_introduced: int = 0, source: str = "generated",
    ) -> None:
        """Record lore the story itself revealed."""
        self.add(
            WORLD_LORE,
            ids=[entry_id],
            documents=[text],
            metadatas=[{"category": category, "source": source,
                        "episode_introduced": episode_introduced}],
        )

    # --- reads -------------------------------------------------------------

    def search(
        self,
        query: str,
        collections: Sequence[str] = COLLECTIONS,
        top_k: int = 10,
        character_id: str | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> list[Memory]:
        """Semantic search across collections, nearest first.

        `character_id` keeps only memories that character was part of. Chroma
        cannot filter inside a stored list, so this is applied in Python over an
        over-fetched candidate set.
        """
        if not query.strip() or top_k < 1:
            return []

        fetch = top_k * OVERFETCH if character_id else top_k
        results: list[Memory] = []

        for name in collections:
            try:
                collection = self.collection(name)
                available = collection.count()
                if not available:
                    continue
                raw = collection.query(
                    query_texts=[query],
                    n_results=min(fetch, available),
                    where=dict(where) if where else None,
                )
            except Exception:  # noqa: BLE001 — see below
                # Retrieval is context enrichment, not correctness: a collection
                # whose index is unreadable should cost the prompt some recall,
                # not cost the author the episode. Every caller handles an empty
                # result already, because episode 1 has no memories either.
                logger.exception("Could not search the %s collection; skipping it", name)
                continue
            results.extend(self._to_memories(name, raw))

        if character_id:
            results = [m for m in results if _mentions(m, character_id)]

        results.sort(key=lambda m: (m.distance is None, m.distance))
        return results[:top_k]

    def get_episode_summary(self, episode_number: int) -> Memory | None:
        raw = self.collection(EPISODE_SUMMARIES).get(ids=[f"episode_{episode_number}"])
        if not raw.get("ids"):
            return None
        return Memory(
            id=raw["ids"][0],
            document=raw["documents"][0],
            metadata=decode_metadata(raw["metadatas"][0]),
            collection=EPISODE_SUMMARIES,
        )

    def _to_memories(self, name: str, raw: Mapping[str, Any]) -> list[Memory]:
        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0] or [None] * len(ids)
        return [
            Memory(
                id=ids[i],
                document=documents[i],
                metadata=decode_metadata(metadatas[i]),
                collection=name,
                distance=distances[i],
            )
            for i in range(len(ids))
        ]

    def reset(self) -> None:
        """Drop every collection. Used by tests and by a deliberate re-run."""
        for name in COLLECTIONS:
            try:
                self.client.delete_collection(name)
            except Exception:  # noqa: BLE001 — absent collections are fine
                pass
        self._collections.clear()


def _mentions(memory: Memory, character_id: str) -> bool:
    """Whether a character appears in the fields that name participants."""
    for key in ("participants", "characters_involved", "linked_characters"):
        value = memory.metadata.get(key)
        if isinstance(value, list) and character_id in value:
            return True
    impact = memory.metadata.get("emotional_impact")
    return isinstance(impact, dict) and character_id in impact
