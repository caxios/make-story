"""The chronicle has to follow the queue when the queue renumbers itself.

Episode numbers here are positions, not identities: `delete_episode` and
`move_episode` both renumber every chapter after the one that moved. The
chronicle stamps its entries with that number, so without this an entry
recorded in "3화" quietly comes to name a different chapter — and this history
is precisely what the author reads when auditing a finished arc.

The entries' own order must not move. Reordering the queue does not reorder
what already happened, which is why a chain sorts by `sequence`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps
from storyweaver.memory.manager import MemoryManager
from storyweaver.ui.project import Project, ProjectStore


class InertVectors:
    def add_episode_summary(self, *a, **k):
        return None

    def add_interaction_records(self, records):
        return 0

    def add_lore(self, *a, **k):
        return None

    def seed_world_lore(self, world):
        return 0


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def memory(tmp_path) -> MemoryManager:
    return MemoryManager(vector_store=InertVectors(), data_dir=tmp_path / "state")


@pytest.fixture
def client(project_store, memory):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(memory)
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)
    deps.set_memory(None, "disabled for tests")


@pytest.fixture
def queue(project_store) -> Project:
    """Five queued episodes, numbered 1 to 5."""
    project = Project(name="테스트")
    for number in range(1, 6):
        project.add_episode(f"{number}화의 줄거리")
    project_store.save(project)
    return project


def _record(memory: MemoryManager, episode_number: int, value: str) -> None:
    memory.chronicle.record(
        "character", "박동혁", "appearance", value,
        source="episode", episode_number=episode_number, reason="테스트",
    )


def _numbers(memory: MemoryManager) -> list[int | None]:
    return [e.episode_number for e in memory.chronicle.chain("character", "박동혁", "appearance")]


def _values(memory: MemoryManager) -> list[str]:
    return [e.value for e in memory.chronicle.chain("character", "박동혁", "appearance")]


# ==========================================================================
# Deleting
# ==========================================================================


def test_deleting_an_episode_takes_its_entries_with_it(client, queue, memory):
    _record(memory, 2, "2화의 변화")
    _record(memory, 4, "4화의 변화")

    assert client.delete("/api/episodes/2").status_code == 200

    assert _values(memory) == ["4화의 변화"]


def test_later_entries_move_down_with_the_queue(client, queue, memory):
    _record(memory, 3, "3화의 변화")
    _record(memory, 5, "5화의 변화")

    client.delete("/api/episodes/2")

    # 3 and 5 became 2 and 4 when the queue closed the gap.
    assert _numbers(memory) == [2, 4]


def test_entries_before_the_gap_are_left_alone(client, queue, memory):
    _record(memory, 1, "1화의 변화")

    client.delete("/api/episodes/4")

    assert _numbers(memory) == [1]


def test_an_authors_own_entry_has_no_episode_to_renumber(client, queue, memory):
    memory.chronicle.record("character", "박동혁", "appearance", "작가가 정한 모습")
    _record(memory, 3, "3화의 변화")

    client.delete("/api/episodes/1")

    entries = memory.chronicle.chain("character", "박동혁", "appearance")
    assert [e.episode_number for e in entries] == [None, 2]


# ==========================================================================
# Moving
# ==========================================================================


def test_moving_an_episode_swaps_the_numbers_on_its_entries(client, queue, memory):
    _record(memory, 2, "먼저 기록된 것")
    _record(memory, 3, "나중에 기록된 것")

    assert client.post("/api/episodes/2/move", json={"offset": 1}).status_code == 200

    # Episode 2 became 3 and episode 3 became 2.
    assert _numbers(memory) == [3, 2]


def test_moving_does_not_reorder_history(client, queue, memory):
    """What already happened happened in that order, whatever the queue says."""
    _record(memory, 2, "먼저 기록된 것")
    _record(memory, 3, "나중에 기록된 것")
    before = [e.sequence for e in memory.chronicle.chain("character", "박동혁", "appearance")]

    client.post("/api/episodes/2/move", json={"offset": 1})

    chain = memory.chronicle.chain("character", "박동혁", "appearance")
    assert [e.value for e in chain] == ["먼저 기록된 것", "나중에 기록된 것"]
    assert [e.sequence for e in chain] == before


def test_a_move_that_falls_off_the_end_moves_nothing(client, queue, memory):
    """`move_episode` declines it, so the chronicle must decline it too."""
    _record(memory, 1, "1화의 변화")

    client.post("/api/episodes/1/move", json={"offset": -1})

    assert _numbers(memory) == [1]


def test_a_move_past_the_last_episode_moves_nothing(client, queue, memory):
    _record(memory, 5, "5화의 변화")

    client.post("/api/episodes/5/move", json={"offset": 1})

    assert _numbers(memory) == [5]


# ==========================================================================
# Without a memory layer
# ==========================================================================


def test_the_queue_still_works_when_memory_is_switched_off(project_store, queue):
    """Memory is optional; reordering must not require it."""
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled")
    with TestClient(app) as client:
        assert client.delete("/api/episodes/2").status_code == 200
        assert client.post("/api/episodes/1/move", json={"offset": 1}).status_code == 200
    deps.set_store(None)
