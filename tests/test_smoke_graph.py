"""The smoke-test graph must be importable and compilable without an API key."""

from __future__ import annotations


def test_graph_compiles_without_api_key():
    from storyweaver.smoke_test import app

    assert {"__start__", "llm", "__end__"} <= set(app.get_graph().nodes)
