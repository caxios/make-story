"""Shared fixtures: sample story data and a stand-in for the Gemini model.

Nothing in the test suite touches the network. `FakeLLM` is duck-typed against
the only surface the agents use — `.with_structured_output(schema).invoke(prompt)`
— so it needs no LangChain machinery and no API key.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from chromadb.api.types import EmbeddingFunction
from pydantic import BaseModel

from storyweaver.memory import (
    MemoryManager,
    PlotThreadTracker,
    StructuredStore,
    VectorStore,
)

from storyweaver.agents.character import CharacterTurn
from storyweaver.agents.scene_runner import SupervisorVerdict
from storyweaver.models import (
    CharacterProfile,
    Episode,
    InteractionEntry,
    Scene,
    StoryBeat,
    WorldLore,
)

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "examples" / "harry_potter_sample.json"


# --------------------------------------------------------------------------
# Fake model
# --------------------------------------------------------------------------

class _BoundFake:
    def __init__(self, parent: "FakeLLM", schema: type[BaseModel]):
        self.parent = parent
        self.schema = schema

    def invoke(self, prompt, **_kwargs) -> BaseModel:
        text = prompt if isinstance(prompt, str) else str(prompt)
        index = len(self.parent.calls)
        self.parent.calls.append((self.schema, text))
        result = self.parent.handler(self.schema, text, index)
        if not isinstance(result, self.schema):
            raise TypeError(f"handler returned {type(result)!r}, expected {self.schema!r}")
        return result


class _FakeMessage:
    """Stands in for an AIMessage — the Writer only ever reads `.content`."""

    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """Records every prompt it is given and returns whatever `handler` decides.

    Structured calls go through `with_structured_output(Schema)`; the Writer
    calls `invoke` directly and gets a message back, so the handler is asked
    for `str` in that case.
    """

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[type[BaseModel] | type[str], str]] = []

    def with_structured_output(self, schema: type[BaseModel], **_kwargs) -> _BoundFake:
        return _BoundFake(self, schema)

    def invoke(self, prompt, **_kwargs) -> _FakeMessage:
        text = prompt if isinstance(prompt, str) else str(prompt)
        index = len(self.calls)
        self.calls.append((str, text))
        return _FakeMessage(self.handler(str, text, index))

    def prompts_for(self, schema) -> list[str]:
        return [text for got, text in self.calls if got is schema]

    @property
    def last_prompt(self) -> str:
        return self.calls[-1][1]


@pytest.fixture
def scripted_llm():
    """Build a FakeLLM from a `{schema: callable(prompt, index)}` routing table."""

    def factory(**by_schema_name):
        def handler(schema, prompt, index):
            fn = by_schema_name.get(schema.__name__)  # `str` routes unstructured calls
            if fn is None:
                raise AssertionError(f"no scripted response for schema {schema.__name__}")
            return fn(prompt, index)

        return FakeLLM(handler)

    return factory


@pytest.fixture
def never_done_supervisor():
    """A supervisor that always says the scene should keep going."""
    return FakeLLM(
        lambda schema, prompt, index: SupervisorVerdict(
            objective_met=False, reason="still building"
        )
    )


# --------------------------------------------------------------------------
# Story data
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_data() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def world(sample_data) -> WorldLore:
    return WorldLore.model_validate(sample_data["world"])


@pytest.fixture
def harry(sample_data) -> CharacterProfile:
    return CharacterProfile.model_validate(sample_data["characters"][0])


@pytest.fixture
def hermione(sample_data) -> CharacterProfile:
    return CharacterProfile.model_validate(sample_data["characters"][1])


@pytest.fixture
def ron(sample_data) -> CharacterProfile:
    return CharacterProfile.model_validate(sample_data["characters"][2])


@pytest.fixture
def characters(harry, hermione, ron) -> dict[str, CharacterProfile]:
    return {c.id: c for c in (harry, hermione, ron)}


@pytest.fixture
def episode(sample_data) -> Episode:
    return Episode.model_validate(sample_data["episodes"][0])


@pytest.fixture
def two_character_scene() -> Scene:
    """Phase 2, Test 2: Harry and Ron meet on the Hogwarts Express."""
    return Scene(
        scene_number=1,
        title="A Compartment on the Hogwarts Express",
        location_id=None,
        participating_character_ids=["harry-potter", "ron-weasley"],
        objective="Harry and Ron meet and begin an unlikely friendship.",
        beats=[
            StoryBeat(
                description="Ron asks to share the compartment.",
                involved_character_ids=["ron-weasley"],
                mood="awkward",
            ),
            StoryBeat(
                description="Harry asks about the wizarding world he knows nothing about.",
                involved_character_ids=["harry-potter"],
            ),
        ],
    )


@pytest.fixture
def three_character_scene() -> Scene:
    return Scene(
        scene_number=2,
        title="The Great Hall",
        location_id="great-hall",
        participating_character_ids=["harry-potter", "ron-weasley", "hermione-granger"],
        objective="The three are sorted and size each other up for the first time.",
        beats=[StoryBeat(description="Hermione corrects Ron and he bristles.", mood="prickly")],
    )


@pytest.fixture
def sample_entries() -> list[InteractionEntry]:
    """A short, clean four-turn log for the Lore Checker and the Writer."""
    return [
        InteractionEntry(
            turn=1,
            character_id="ron-weasley",
            type="dialogue",
            content="Anyone sitting there? Everywhere else is full.",
            directed_at="harry-potter",
        ),
        InteractionEntry(
            turn=2, character_id="harry-potter", type="action", content="He shook his head."
        ),
        InteractionEntry(
            turn=3,
            character_id="harry-potter",
            type="dialogue",
            content="Are all your family wizards?",
            directed_at="ron-weasley",
        ),
        InteractionEntry(
            turn=4,
            character_id="ron-weasley",
            type="thought",
            content="He does not know anything. Blimey.",
        ),
    ]


# --------------------------------------------------------------------------
# Memory (Phase 4)
# --------------------------------------------------------------------------

class DeterministicEmbedding(EmbeddingFunction):
    """A bag-of-words embedder: no model download, no network, stable ordering.

    Real embeddings are not the thing under test here — retrieval plumbing is.
    Documents sharing vocabulary with the query land closer, which is all the
    memory tests need to assert against. Vectors are L2-normalised, without
    which a raw count vector makes long documents *farther* from a short query
    no matter how much vocabulary they share.
    """

    VOCAB = (
        "trapdoor dog corridor stone flamel promise wand library forbidden "
        "harry ron hermione hogwarts express sorting hall friend secret "
        "letter hagrid vernon owl chess troll mirror"
    ).split()

    def __init__(self, vocab: tuple[str, ...] | None = None):
        self.vocab = list(vocab) if vocab else list(self.VOCAB)

    @staticmethod
    def name() -> str:
        return "deterministic-test-embedding"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "DeterministicEmbedding":
        return DeterministicEmbedding()

    def __call__(self, input):  # noqa: A002 — Chroma dictates this parameter name
        vectors = []
        for document in input:
            words = re.findall(r"[a-z0-9']+", document.lower())
            counts = [float(words.count(term)) for term in self.vocab]
            # A small constant tail keeps an all-zero vector from being degenerate.
            counts.append(0.1)
            norm = math.sqrt(sum(value * value for value in counts))
            vectors.append([value / norm for value in counts])
        return vectors


@pytest.fixture
def chroma_client(tmp_path):
    """A Chroma instance isolated to this test.

    Not `EphemeralClient`: Chroma caches its system by settings, so every
    ephemeral client in a process hands back the *same* store and tests leak
    documents into one another. A per-test directory is genuinely isolated and
    still touches no network.
    """
    import chromadb

    return chromadb.PersistentClient(path=str(tmp_path / "chroma"))


@pytest.fixture
def vector_store(chroma_client) -> VectorStore:
    return VectorStore(client=chroma_client, embedding_function=DeterministicEmbedding())


@pytest.fixture
def memory(tmp_path, vector_store) -> MemoryManager:
    """A MemoryManager backed by a temp directory and an in-memory vector store."""
    return MemoryManager(vector_store=vector_store, data_dir=tmp_path / "state")


@pytest.fixture
def tracker(tmp_path) -> PlotThreadTracker:
    return PlotThreadTracker(tmp_path / "state")


@pytest.fixture
def store(tmp_path) -> StructuredStore:
    return StructuredStore(tmp_path / "state")


# --------------------------------------------------------------------------
# No test may reach the real model
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_live_model_calls(monkeypatch):
    """Fail loudly instead of quietly spending the author's Gemini quota.

    Agents take an optional `llm=`, and the suite passes a stub everywhere it
    remembers to. "Everywhere it remembers to" is the problem: a test that
    forgets — or that reaches a code path binding `summarize_episode` at import
    time, so a `monkeypatch` on the module misses it — will happily make a real
    API call, because a developer's `.env` has a real key in it.

    `build_model` is the one place a real client is constructed, so blocking it
    here closes the hole for every caller at once.
    """
    from storyweaver import llm

    def refuse(*args, **kwargs):
        raise AssertionError(
            "A test tried to build a real Gemini model. Pass a stub `llm=`, or "
            "patch the agent that is calling out — the suite must never spend "
            "the author's quota."
        )

    llm.build_model.cache_clear()
    monkeypatch.setattr(llm, "build_model", refuse)
