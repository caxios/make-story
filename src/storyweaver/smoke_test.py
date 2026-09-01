"""Minimal test: call Gemini via LangGraph.

Run with:  python -m storyweaver.smoke_test
Requires GOOGLE_API_KEY in the environment or .env.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from storyweaver.llm import get_llm


class SimpleState(TypedDict):
    prompt: str
    response: str


def call_llm(state: SimpleState) -> dict:
    result = get_llm(stage="smoke_test").invoke(state["prompt"])
    return {"response": result.content}


graph = StateGraph(SimpleState)
graph.add_node("llm", call_llm)
graph.add_edge(START, "llm")
graph.add_edge("llm", END)
app = graph.compile()


if __name__ == "__main__":
    out = app.invoke({"prompt": "Write one sentence about a wizard.", "response": ""})
    print(out["response"])
