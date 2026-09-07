"""The HTTP API, exercised through FastAPI's TestClient.

Every test points the API at a temp-directory `ProjectStore`, so the author's
real `data/` is never touched, and none of these make a model call: the one
test that drives a generation swaps `run_episode` for a stand-in that reports
the same node events the real pipeline does.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from storyweaver.api import deps, generation
from storyweaver.models import Relationship
from storyweaver.ui.project import Project, ProjectStore, project_from_sample


@pytest.fixture
def project_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def client(project_store):
    from storyweaver.server import app

    deps.set_store(project_store)
    deps.set_memory(None, "disabled for tests")
    with TestClient(app) as test_client:
        yield test_client
    deps.set_store(None)


@pytest.fixture
def loaded(project_store, sample_data) -> Project:
    """The sample project, saved to disk: episode 1 written, 2 and 3 queued."""
    project = project_from_sample(sample_data)
    project.add_episode("Harry is fitted for a wand.", "Ollivanders")
    project.add_episode("The first flying lesson goes wrong.", "Flying")
    project.update_episode(
        project.episodes[0].model_copy(
            update={
                "status": "completed",
                "title": "The Sorting",
                "final_text": "The ceiling churned with cloud.",
            }
        )
    )
    project_store.save(project)
    return project


def _sse(response) -> list[tuple[str, dict]]:
    """Parse an SSE body into `(event, payload)` pairs."""
    events = []
    body = response.text.replace("\r\n", "\n")
    for block in body.split("\n\n"):
        name, data = "", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        if name and data:
            events.append((name, json.loads(data)))
    return events


# ==========================================================================
# Meta
# ==========================================================================


def test_health_reports_what_the_backend_has(client, project_store):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["memory_available"] is False
    assert body["data_dir"] == str(project_store.data_dir)


def test_cors_allows_the_vite_dev_server(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# ==========================================================================
# Project
# ==========================================================================


def test_an_absent_project_reads_back_as_an_empty_one(client):
    body = client.get("/api/project").json()

    assert body["episodes"] == []
    assert body["characters"] == []


def test_a_project_can_be_replaced_wholesale(client, project_store, loaded):
    edited = loaded.model_copy(update={"name": "Renamed"})

    response = client.put("/api/project", json=json.loads(edited.model_dump_json()))

    assert response.status_code == 200
    assert project_store.load().name == "Renamed"


def test_stats_count_what_is_written(client, loaded):
    body = client.get("/api/project/stats").json()

    assert body["episodes_completed"] == 1
    assert body["character_count"] == len(loaded.characters)
    assert body["total_words"] == 5
    # Without the memory layer the thread count is unknown, not wrong.
    assert body["memory_available"] is False
    assert body["open_thread_count"] == 0


# ==========================================================================
# World
# ==========================================================================


def test_the_world_header_is_patched_not_replaced(client, project_store, loaded):
    response = client.put("/api/world", json={"tone": "bleak"})

    assert response.status_code == 200
    saved = project_store.load().world
    assert saved.tone == "bleak"
    assert saved.title == loaded.world.title  # untouched
    assert saved.rules  # and the rules survived the edit


def test_a_rule_can_be_added_and_deleted(client, project_store, loaded):
    rule = {"id": "gamps-law", "category": "magic", "statement": "Food cannot be conjured."}

    client.post("/api/world/rules", json=rule)
    assert any(r.id == "gamps-law" for r in project_store.load().world.rules)

    assert client.delete("/api/world/rules/gamps-law").status_code == 200
    assert not any(r.id == "gamps-law" for r in project_store.load().world.rules)


def test_deleting_a_rule_that_does_not_exist_is_a_404(client, loaded):
    assert client.delete("/api/world/rules/nope").status_code == 404


def test_deleting_a_location_reparents_what_was_inside_it(client, project_store):
    client.post(
        "/api/world/locations",
        json={"id": "castle", "name": "Castle", "description": "Stone."},
    )
    client.post(
        "/api/world/locations",
        json={
            "id": "hall",
            "name": "Great Hall",
            "description": "Long tables.",
            "parent_location_id": "castle",
        },
    )

    client.delete("/api/world/locations/castle")

    locations = {l.id: l for l in project_store.load().world.locations}
    assert "castle" not in locations
    # The hall did not vanish with its parent; it moved up to the root.
    assert locations["hall"].parent_location_id is None


# ==========================================================================
# Characters
# ==========================================================================


def test_deleting_a_character_takes_the_relationships_pointing_at_them(
    client, project_store, loaded
):
    target = loaded.characters[0]
    referrers = [
        c.id
        for c in loaded.characters
        if any(r.target_character_id == target.id for r in c.relationships)
    ]
    assert referrers, "the sample needs a relationship to make this test mean anything"

    assert client.delete(f"/api/characters/{target.id}").status_code == 200

    saved = project_store.load()
    assert saved.get_character(target.id) is None
    for character in saved.characters:
        assert all(r.target_character_id != target.id for r in character.relationships)


def test_a_character_can_be_cloned_and_a_clashing_id_is_refused(client, loaded):
    source = loaded.characters[0].id

    body = client.post(
        f"/api/characters/{source}/clone", json={"new_id": "twin", "new_name": "Twin"}
    )
    assert body.status_code == 200
    assert body.json()["name"] == "Twin"

    again = client.post(
        f"/api/characters/{source}/clone", json={"new_id": "twin", "new_name": "Twin"}
    )
    assert again.status_code == 409


def test_the_graph_only_draws_edges_to_characters_that_exist(client, project_store, loaded):
    stranger = loaded.characters[0].model_copy(
        deep=True,
        update={
            "id": "ghost",
            "name": "Ghost",
            "relationships": [Relationship(target_character_id="not-in-the-cast", type="rival")],
        },
    )
    loaded.upsert_character(stranger)
    project_store.save(loaded)

    graph = client.get("/api/characters/graph").json()

    ids = {node["id"] for node in graph["nodes"]}
    assert "ghost" in ids
    assert all(edge["target"] in ids for edge in graph["edges"])


# ==========================================================================
# Episodes
# ==========================================================================


def test_a_queued_episode_takes_the_next_number(client, project_store, loaded):
    response = client.post(
        "/api/episodes", json={"author_storyline": "Harry meets Ron.", "title": "The Train"}
    )

    assert response.status_code == 201
    assert response.json()["episode_number"] == len(loaded.episodes) + 1
    assert project_store.load().episodes[-1].author_storyline == "Harry meets Ron."


def test_an_unknown_pacing_is_refused(client, loaded):
    response = client.post(
        "/api/episodes", json={"author_storyline": "Something.", "pacing": "breakneck"}
    )

    assert response.status_code == 422


def test_deleting_an_episode_closes_the_gap(client, project_store, loaded):
    original = len(loaded.episodes)

    assert client.delete("/api/episodes/1").status_code == 200

    saved = project_store.load()
    assert len(saved.episodes) == original - 1
    # Numbers follow position, so nothing is left numbered 0 or duplicated.
    assert [e.episode_number for e in saved.episodes] == list(range(1, original))


def test_moving_an_episode_renumbers_the_queue(client, project_store, loaded):
    second = loaded.episodes[1].author_storyline

    assert client.post("/api/episodes/2/move", json={"offset": -1}).status_code == 200

    saved = project_store.load()
    assert saved.episodes[0].author_storyline == second
    assert saved.episodes[0].episode_number == 1


def test_moving_past_the_end_of_the_queue_changes_nothing(client, project_store, loaded):
    before = [e.author_storyline for e in loaded.episodes]

    assert client.post("/api/episodes/1/move", json={"offset": -1}).status_code == 200

    assert [e.author_storyline for e in project_store.load().episodes] == before


def test_a_batch_of_outlines_becomes_a_queue(client, project_store):
    text = "Chapter one happens.\n---\nChapter two happens.\n---\nChapter three happens."

    response = client.post("/api/episodes/batch", json={"text": text})

    assert response.status_code == 201
    assert len(response.json()) == 3
    saved = project_store.load()
    assert [e.episode_number for e in saved.episodes] == [1, 2, 3]
    assert saved.episodes[2].author_storyline == "Chapter three happens."


def test_a_batch_with_nothing_in_it_is_refused(client):
    assert client.post("/api/episodes/batch", json={"text": "  \n---\n  "}).status_code == 422


def test_an_episode_can_be_edited_in_place(client, project_store, loaded):
    response = client.put("/api/episodes/2", json={"title": "The Train", "pacing": "fast"})

    assert response.status_code == 200
    saved = project_store.load().get_episode(2)
    assert saved.title == "The Train"
    assert saved.pacing == "fast"
    assert saved.author_storyline == loaded.episodes[1].author_storyline  # untouched


def test_an_unknown_episode_is_a_404(client, loaded):
    assert client.get("/api/episodes/99").status_code == 404
    assert client.put("/api/episodes/99", json={"title": "x"}).status_code == 404
    assert client.delete("/api/episodes/99").status_code == 404


# ==========================================================================
# Generation
# ==========================================================================


def test_generation_refuses_a_story_with_no_world(client, project_store):
    project = Project()
    project.add_episode("Something happens.")
    project_store.save(project)

    response = client.get("/api/generation/stream/1")

    assert response.status_code == 409
    assert "world" in response.json()["detail"]


def test_generation_refuses_an_unknown_episode(client, loaded):
    assert client.get("/api/generation/stream/99").status_code == 404


def test_a_generation_streams_progress_and_saves_the_chapter(
    client, project_store, loaded, monkeypatch
):
    def fake_run_episode(episode, world, characters, *, on_event=None, **kwargs):
        from storyweaver.models import Scene

        scenes = [
            Scene(
                scene_number=1,
                title="Arrival",
                participating_character_ids=[],
                objective="Arrive.",
            )
        ]
        on_event("director_plan_scenes", {"scenes": scenes})
        on_event("write_scene", {"current_scene_index": 0, "scenes": scenes,
                                 "scene_prose_outputs": ["Two words here."]})
        on_event("assemble_episode", {"final_episode_text": "Two words here."})
        done = episode.model_copy(
            update={"status": "completed", "final_text": "Two words here.", "title": "Arrival"}
        )
        return done, {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", fake_run_episode)

    events = _sse(client.get("/api/generation/stream/2"))
    names = [name for name, _ in events]

    assert names[0] == "start"
    assert names[-1] == "complete"
    assert "progress" in names

    completed = events[-1][1]
    assert completed["words"] == 3
    assert completed["episode"]["status"] == "completed"
    assert project_store.load().get_episode(2).final_text == "Two words here."


def test_a_failed_generation_reports_the_error_and_requeues_the_episode(
    client, project_store, loaded, monkeypatch
):
    def explode(*args, **kwargs):
        raise RuntimeError("the model refused")

    monkeypatch.setattr(generation.episode_runner, "run_episode", explode)

    events = _sse(client.get("/api/generation/stream/2"))
    name, payload = events[-1]

    assert name == "error"
    assert payload["message"] == "the model refused"
    assert payload["type"] == "RuntimeError"
    # The chapter is back in the queue rather than stuck reading "in progress".
    assert project_store.load().get_episode(2).status == "queued"


def test_nothing_is_generating_to_begin_with(client, loaded):
    assert client.get("/api/generation/running").json() == []
    assert client.get("/api/generation/pending").json() == []


# ==========================================================================
# Memory
# ==========================================================================


def test_memory_endpoints_say_so_when_the_layer_is_down(client):
    assert client.get("/api/memory/status").json()["available"] is False
    assert client.get("/api/memory/threads").status_code == 503
    assert client.post("/api/memory/query", json={"query": "wand"}).status_code == 503


def test_plot_threads_are_split_by_where_they_stand(client, memory):
    deps.set_memory(memory)
    memory.open_plot_thread("The Stone", "Something is hidden on the third floor.", 1)
    memory.open_plot_thread("The Mirror", "It shows what you want.", 1)
    memory.resolve_plot_thread("The Mirror", "Harry sees his parents.", 2)

    body = client.get("/api/memory/threads").json()

    assert [t["name"] for t in body["active"]] == ["The Stone"]
    assert [t["name"] for t in body["resolved"]] == ["The Mirror"]


def test_a_semantic_query_comes_back_ranked(client, memory, world):
    deps.set_memory(memory)
    memory.seed_world(world)

    body = client.post("/api/memory/query", json={"query": "wand", "top_k": 3}).json()

    assert body["results"]
    assert len(body["results"]) <= 3
    relevances = [r["relevance"] for r in body["results"]]
    assert relevances == sorted(relevances, reverse=True)


# ==========================================================================
# Export
# ==========================================================================


def test_a_written_chapter_downloads_as_markdown(client, loaded):
    response = client.get("/api/export/episode/1/markdown")

    assert response.status_code == 200
    assert "The Sorting" in response.text
    assert "attachment" in response.headers["content-disposition"]


def test_an_unwritten_chapter_has_nothing_to_export(client, loaded):
    assert client.get("/api/export/episode/2/markdown").status_code == 409


def test_a_chapter_downloads_as_a_word_document(client, loaded):
    response = client.get("/api/export/episode/1/docx")

    assert response.status_code == 200
    # A .docx is a ZIP; this is its magic number.
    assert response.content[:2] == b"PK"


def test_the_project_downloads_as_an_archive(client, loaded):
    response = client.get("/api/export/project/zip")

    assert response.status_code == 200
    assert response.content[:2] == b"PK"


def test_a_korean_project_name_survives_the_download_header(client, project_store, loaded):
    project_store.save(loaded.model_copy(update={"name": "마법사의 돌"}))

    response = client.get("/api/export/story/markdown")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    # The ASCII fallback is safe to send, and the real name rides along encoded.
    disposition.encode("latin-1")
    assert "filename*=UTF-8''" in disposition


def test_a_role_survives_the_round_trip_and_labels_the_graph(client, loaded):
    character = loaded.characters[0].model_copy(update={"role": "protagonist"})

    client.post("/api/characters", json=json.loads(character.model_dump_json()))

    stored = client.get("/api/characters").json()
    assert next(c for c in stored if c["id"] == character.id)["role"] == "protagonist"

    graph = client.get("/api/characters/graph").json()
    assert next(n for n in graph["nodes"] if n["id"] == character.id)["role"] == "protagonist"


def test_a_character_with_no_role_falls_back_to_their_strongest_trait(client, loaded):
    """Projects authored before `role` existed still get a labelled node."""
    character = loaded.characters[0]
    assert character.role == ""
    assert character.traits, "the sample needs traits to make this test mean anything"
    strongest = max(character.traits, key=lambda t: t.intensity).name

    graph = client.get("/api/characters/graph").json()

    assert next(n for n in graph["nodes"] if n["id"] == character.id)["role"] == strongest


def test_a_progress_frame_says_what_the_scene_in_flight_is_about(
    client, project_store, loaded, monkeypatch
):
    """The live view needs more than a scene number to show anything useful."""
    from storyweaver.models import Scene

    cast = loaded.characters[0]

    def fake_run_episode(episode, world, characters, *, on_event=None, **kwargs):
        scenes = [
            Scene(
                scene_number=1,
                title="The Chamber of Echoes",
                participating_character_ids=[cast.id, "not-in-the-cast"],
                objective="Discover the cipher.",
            )
        ]
        on_event(
            "simulate_scene",
            {
                "scenes": scenes,
                "current_scene_index": 0,
                "current_entries": [{}, {}, {}],
                "retry_count": 0,
            },
        )
        return episode.model_copy(update={"status": "completed", "final_text": "Done."}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", fake_run_episode)

    events = _sse(client.get("/api/generation/stream/2?max_turns=9"))
    progress = next(payload for name, payload in events if name == "progress")

    assert progress["stage"] == "simulating"
    assert progress["scene"]["title"] == "The Chamber of Echoes"
    assert progress["scene"]["objective"] == "Discover the cipher."
    # Names, not ids — and an id with no character behind it stays as it is.
    assert progress["scene"]["characters"] == [cast.name, "not-in-the-cast"]
    assert progress["turns"] == 3
    assert progress["max_turns"] == 9
    assert progress["tokens"] == 0  # nothing was actually spent by the stand-in


def test_a_progress_frame_carries_no_scene_before_the_director_has_planned_one(
    client, loaded, monkeypatch
):
    def fake_run_episode(episode, world, characters, *, on_event=None, **kwargs):
        on_event("director_plan_scenes", {"scenes": []})
        return episode.model_copy(update={"status": "completed"}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", fake_run_episode)

    events = _sse(client.get("/api/generation/stream/2"))
    progress = next(payload for name, payload in events if name == "progress")

    assert progress["stage"] == "planning"
    assert progress["scene"] is None


# ==========================================================================
# Telemetry
# ==========================================================================


def test_telemetry_starts_empty_but_still_reports_the_model(client):
    body = client.get("/api/telemetry").json()

    assert body["runs"] == 0
    assert body["total_tokens"] == 0
    assert body["model"]
    assert body["input_cost_per_mtok"] > 0


def test_a_generation_adds_to_the_cumulative_total(client, loaded, monkeypatch):
    """The per-run log dies with the run, so the total has to be written down."""
    from storyweaver import telemetry as core

    def fake_run_episode(episode, world, characters, *, on_event=None, **kwargs):
        # Spend something, the way a real stage would.
        log = core.active_log()
        assert log is not None, "the stream should have opened a usage log"
        log.add(
            core.CallRecord(
                stage="writer", input_tokens=1000, output_tokens=500, seconds=1.0
            )
        )
        return episode.model_copy(update={"status": "completed", "final_text": "Done."}), {}

    monkeypatch.setattr(generation.episode_runner, "run_episode", fake_run_episode)

    before = client.get("/api/telemetry").json()
    _sse(client.get("/api/generation/stream/2"))
    after = client.get("/api/telemetry").json()

    assert before["runs"] == 0
    assert after["runs"] == 1
    assert after["input_tokens"] == 1000
    assert after["output_tokens"] == 500
    assert after["total_tokens"] == 1500
    assert after["cost"] > 0
    assert after["by_stage"]["writer"] == 1500
    assert after["recent"][0]["episode_number"] == 2


def test_a_failed_generation_still_records_what_it_spent(client, loaded, monkeypatch):
    from storyweaver import telemetry as core

    def explode(episode, world, characters, *, on_event=None, **kwargs):
        log = core.active_log()
        assert log is not None
        log.add(
            core.CallRecord(
                stage="director", input_tokens=800, output_tokens=200, seconds=1.0
            )
        )
        raise RuntimeError("the model refused")

    monkeypatch.setattr(generation.episode_runner, "run_episode", explode)

    _sse(client.get("/api/generation/stream/2"))

    body = client.get("/api/telemetry").json()
    assert body["total_tokens"] == 1000
    assert body["by_stage"]["director"] == 1000
