"""Phase 4, Tests 2 & 3: plot thread lifecycle and stale detection."""

from __future__ import annotations

import pytest

from storyweaver.memory.plot_tracker import PlotThread, PlotThreadTracker


def _thread(thread_id="whats_under_trapdoor", episode=1, **kwargs) -> PlotThread:
    return PlotThread(
        id=thread_id,
        name=kwargs.pop("name", "What is under the trapdoor?"),
        description=kwargs.pop("description", "A three-headed dog guards something."),
        opened_in_episode=episode,
        **kwargs,
    )


# --------------------------------------------------------------------------
# Test 2: lifecycle
# --------------------------------------------------------------------------

def test_open_progress_resolve(tracker):
    tracker.open(_thread(episode=1))

    assert [t.id for t in tracker.get_active()] == ["whats_under_trapdoor"]

    tracker.progress("whats_under_trapdoor", "Hermione names Nicolas Flamel.", 3)
    thread = tracker.get("whats_under_trapdoor")
    assert thread.status == "progressing"
    assert thread.last_referenced_episode == 3
    assert "Episode 3" in thread.events[0]
    assert tracker.get_active()  # still awaiting a payoff

    tracker.resolve("whats_under_trapdoor", "It is the Philosopher's Stone.", 5)
    thread = tracker.get("whats_under_trapdoor")
    assert thread.status == "resolved"
    assert thread.resolved_in_episode == 5
    assert thread.resolution == "It is the Philosopher's Stone."
    assert tracker.get_active() == []  # gone from active after resolution


def test_a_new_thread_counts_as_referenced_when_it_opens(tracker):
    thread = tracker.open(_thread(episode=7))
    assert thread.last_referenced_episode == 7


def test_reopening_an_existing_id_keeps_the_original(tracker, caplog):
    tracker.open(_thread(episode=1))
    tracker.open(_thread(episode=4, description="A different description."))

    assert len(tracker.all()) == 1
    assert tracker.get("whats_under_trapdoor").opened_in_episode == 1


def test_progressing_a_resolved_thread_reopens_it(tracker):
    tracker.open(_thread(episode=1))
    tracker.resolve("whats_under_trapdoor", "Solved.", 5)

    tracker.progress("whats_under_trapdoor", "It turns out there was more.", 8)

    thread = tracker.get("whats_under_trapdoor")
    assert thread.status == "progressing"
    assert thread.resolved_in_episode is None
    assert thread.resolution is None
    assert thread in tracker.get_active()


def test_touching_an_unknown_thread_raises(tracker):
    with pytest.raises(KeyError, match="ghost"):
        tracker.progress("ghost", "event", 1)
    with pytest.raises(KeyError, match="ghost"):
        tracker.resolve("ghost", "resolution", 1)


def test_a_later_reference_never_moves_backwards(tracker):
    tracker.open(_thread(episode=1))
    tracker.progress("whats_under_trapdoor", "late", 6)
    tracker.progress("whats_under_trapdoor", "an aside about episode 2", 2)

    assert tracker.get("whats_under_trapdoor").last_referenced_episode == 6


# --------------------------------------------------------------------------
# Test 3: stale detection
# --------------------------------------------------------------------------

def test_a_thread_opened_and_never_referenced_goes_stale(tracker):
    tracker.open(_thread("fluffy_the_dog", episode=1))
    tracker.open(_thread("nicolas_flamel", episode=6, name="Who is Flamel?"))

    stale = tracker.get_stale(episodes_since_last_ref=5)

    assert [t.id for t in stale] == ["fluffy_the_dog"]


def test_current_episode_defaults_to_the_latest_reference(tracker):
    tracker.open(_thread("fluffy_the_dog", episode=1))

    assert tracker.get_stale(5) == []  # nothing has happened since episode 1

    tracker.open(_thread("nicolas_flamel", episode=6, name="Who is Flamel?"))
    assert [t.id for t in tracker.get_stale(5)] == ["fluffy_the_dog"]


def test_current_episode_can_be_supplied(tracker):
    tracker.open(_thread("fluffy_the_dog", episode=1))

    assert tracker.get_stale(5, current_episode=4) == []
    assert [t.id for t in tracker.get_stale(5, current_episode=6)] == ["fluffy_the_dog"]


def test_progressing_a_thread_clears_its_staleness(tracker):
    tracker.open(_thread("fluffy_the_dog", episode=1))
    tracker.progress("fluffy_the_dog", "Ron mentions the dog again.", 6)

    assert tracker.get_stale(5, current_episode=7) == []


def test_resolved_threads_are_never_stale(tracker):
    tracker.open(_thread("fluffy_the_dog", episode=1))
    tracker.resolve("fluffy_the_dog", "The dog was guarding the Stone.", 2)

    assert tracker.get_stale(5, current_episode=20) == []


def test_stale_threads_come_back_quietest_first(tracker):
    tracker.open(_thread("oldest", episode=1, name="Oldest"))
    tracker.open(_thread("newer", episode=3, name="Newer"))

    assert [t.id for t in tracker.get_stale(2, current_episode=10)] == ["oldest", "newer"]


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def test_threads_survive_a_restart(tmp_path):
    first = PlotThreadTracker(tmp_path)
    first.open(_thread(episode=1))
    first.progress("whats_under_trapdoor", "Flamel.", 3)

    second = PlotThreadTracker(tmp_path)
    thread = second.get("whats_under_trapdoor")

    assert thread is not None
    assert thread.status == "progressing"
    assert thread.events == ["Episode 3: Flamel."]


def test_an_empty_directory_loads_cleanly(tmp_path):
    assert PlotThreadTracker(tmp_path / "does-not-exist-yet").all() == []


def test_summary_line_carries_status_and_history(tracker):
    tracker.open(_thread(episode=1))
    tracker.progress("whats_under_trapdoor", "Hermione names Flamel.", 3)

    line = tracker.get("whats_under_trapdoor").summary_line()

    assert "What is under the trapdoor?" in line
    assert "progressing" in line
    assert "opened in episode 1" in line
    assert "last touched in 3" in line
    assert "Hermione names Flamel." in line
