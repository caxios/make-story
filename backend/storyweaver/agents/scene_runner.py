"""LangGraph workflow that simulates one scene, turn by turn.

    START -> select_next_character -> character_act -> check_scene_complete
                     ^                                        |
                     +-------------- "continue" --------------+
                                                              |
                                                        "done" -> END
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from storyweaver.agents import character as character_agent
from storyweaver.agents import context
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import CharacterProfile, InteractionEntry, Scene, WorldLore
from storyweaver.wiki import free_sections_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 20
# Don't let the supervisor cut a scene off before every participant has spoken
# at least twice — objectives read as "met" suspiciously early otherwise.
MIN_ROUNDS_BEFORE_CHECK = 2


class SceneSimulationState(TypedDict, total=False):
    # --- Inputs (set before the graph starts) ---
    world_lore: WorldLore
    characters: dict[str, CharacterProfile]  # id -> profile
    scene: Scene
    # --- Working state ---
    current_turn: int            # which interaction turn we're on
    max_turns: int               # cap to prevent infinite loops
    next_character_id: str       # chosen by select_next_character
    rota_index: int              # position in the round-robin, kept across detours
    interaction_log: list[dict]  # accumulated log entries
    constraints: list[str]       # Lore Checker fixes to honour on a re-run
    # --- Outputs ---
    completed: bool
    stop_reason: str


class SupervisorVerdict(BaseModel):
    """The scene supervisor's read on whether the scene can end."""

    objective_met: bool = Field(
        description="True only if the objective is genuinely accomplished"
    )
    reason: str = Field(default="", description="One short sentence of justification")


def _entries(state: SceneSimulationState) -> list[InteractionEntry]:
    return [InteractionEntry.model_validate(e) for e in state.get("interaction_log", [])]


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

def select_next_character(state: SceneSimulationState) -> dict:
    """Round-robin through the participants, with one exception.

    If the previous turn was directed at a specific character, that character
    answers next — a question deserves a reply more than the rota does. The
    rota position is *not* advanced for such a reply, so a character who was
    pulled forward to answer does not lose their own place in line; without
    that, whoever sat between the speaker and the addressee would be starved.
    """
    participants = state["scene"].participating_character_ids
    log = state.get("interaction_log", [])
    rota_index = state.get("rota_index", 0)

    last = log[-1] if log else None
    directed_at = last.get("directed_at") if last else None

    if last is not None and directed_at in participants and directed_at != last["character_id"]:
        return {
            "next_character_id": directed_at,
            "rota_index": rota_index,
            "current_turn": state.get("current_turn", 0) + 1,
        }

    chosen = participants[rota_index % len(participants)]
    # A detour may have left the rota pointing at whoever just spoke; nobody
    # answers themselves, so step over them.
    if last is not None and chosen == last["character_id"] and len(participants) > 1:
        rota_index += 1
        chosen = participants[rota_index % len(participants)]

    return {
        "next_character_id": chosen,
        "rota_index": rota_index + 1,
        "current_turn": state.get("current_turn", 0) + 1,
    }


def character_act(state: SceneSimulationState, llm=None, memory=None) -> dict:
    """Let the selected character take their turn and append it to the log."""
    characters = state["characters"]
    character = characters[state["next_character_id"]]

    memory_context = ""
    extra_sections = ""
    if memory is not None:
        memory_context = memory.build_character_context(character, state["scene"], characters)
        # Sections the author added to this character's wiki page — 능력,
        # 과거사 and the like. They have no typed field to land in, so this is
        # the only path by which they reach the model.
        extra_sections = free_sections_text(memory.chronicle, "character", character.id)

    entry = character_agent.act(
        character=character,
        scene=state["scene"],
        world=state["world_lore"],
        characters=characters,
        interaction_log=_entries(state),
        turn=state["current_turn"],
        llm=llm,
        constraints=state.get("constraints", []),
        memory_context=memory_context,
        extra_sections=extra_sections,
    )
    return {"interaction_log": state.get("interaction_log", []) + [entry.model_dump()]}


def check_scene_complete(state: SceneSimulationState, llm=None) -> dict:
    """Stop on the turn cap; otherwise ask the supervisor once per full round."""
    scene = state["scene"]
    turn = state["current_turn"]
    max_turns = state.get("max_turns", DEFAULT_MAX_TURNS)

    if turn >= max_turns:
        return {"completed": True, "stop_reason": f"max_turns ({max_turns}) reached"}

    participants = len(scene.participating_character_ids)
    if turn < participants * MIN_ROUNDS_BEFORE_CHECK or turn % participants != 0:
        return {"completed": False, "stop_reason": ""}

    prompt = render_prompt(
        "scene_supervisor",
        objective=scene.objective,
        beats=context.format_beats(scene.beats),
        interaction_log=context.format_interaction_log(
            _entries(state), characters=state["characters"]
        ),
    )
    model = telemetry.meter(llm or get_llm(stage="supervisor"), "supervisor")
    verdict: SupervisorVerdict = model.with_structured_output(SupervisorVerdict).invoke(prompt)

    if verdict.objective_met:
        reason = verdict.reason.strip() or "no reason given"
        return {"completed": True, "stop_reason": f"objective met: {reason}"}
    return {"completed": False, "stop_reason": ""}


def should_continue(state: SceneSimulationState) -> str:
    return "done" if state.get("completed") else "continue"


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def seed_rota_index(participants: list[str], log: list[dict]) -> int:
    """Where the rota should resume after a partial log.

    Used when a scene is re-run from a specific turn: the prefix that survives
    already fixed who spoke last, so the rota picks up just past them.
    """
    if not log:
        return 0
    try:
        return participants.index(log[-1]["character_id"]) + 1
    except ValueError:
        return 0


def build_scene_graph(llm=None, supervisor_llm=None, memory=None):
    """Compile the scene-simulation graph.

    `llm` drives the characters, `supervisor_llm` the completion check (which
    defaults to a temperature-0 model, since that call is a judgement rather
    than creative writing). `memory` is an optional `MemoryManager` supplying
    each character with what they personally remember. All three are bound at
    build time so the nodes stay pure functions of state.
    """

    def _act(state: SceneSimulationState) -> dict:
        return character_act(state, llm=llm, memory=memory)

    def _check(state: SceneSimulationState) -> dict:
        chosen = supervisor_llm if supervisor_llm is not None else llm
        return check_scene_complete(state, llm=chosen)

    graph = StateGraph(SceneSimulationState)
    graph.add_node("select_next_character", select_next_character)
    graph.add_node("character_act", _act)
    graph.add_node("check_scene_complete", _check)

    graph.add_edge(START, "select_next_character")
    graph.add_edge("select_next_character", "character_act")
    graph.add_edge("character_act", "check_scene_complete")
    graph.add_conditional_edges(
        "check_scene_complete",
        should_continue,
        {"continue": "select_next_character", "done": END},
    )
    return graph.compile()


def simulate_scene(
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    supervisor_llm=None,
    max_turns: int = DEFAULT_MAX_TURNS,
    initial_log: Sequence[dict] | None = None,
    constraints: Sequence[str] = (),
    memory=None,
) -> dict[str, Any]:
    """Run the scene to completion and return the final graph state.

    `initial_log` seeds the simulation with turns that already happened, so a
    scene can be re-run from the point where the Lore Checker objected instead
    of from the top; `constraints` are the fixes the characters must honour.
    """
    char_map = context.as_character_map(characters)
    if not scene.participating_character_ids:
        raise ValueError(f"Scene {scene.scene_number} has no participants to simulate")
    missing = [cid for cid in scene.participating_character_ids if cid not in char_map]
    if missing:
        raise KeyError(f"Scene {scene.scene_number} references unknown characters: {missing}")
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")

    seed = [dict(entry) for entry in (initial_log or [])]
    if len(seed) >= max_turns:
        raise ValueError(
            f"initial_log already holds {len(seed)} turns, which meets max_turns={max_turns}"
        )

    app = build_scene_graph(llm=llm, supervisor_llm=supervisor_llm, memory=memory)
    initial: SceneSimulationState = {
        "world_lore": world,
        "characters": char_map,
        "scene": scene,
        "current_turn": len(seed),
        "rota_index": seed_rota_index(scene.participating_character_ids, seed),
        "max_turns": max_turns,
        "interaction_log": seed,
        "constraints": list(constraints),
        "completed": False,
        "stop_reason": "",
    }
    # Three nodes run per turn, so LangGraph's default recursion limit of 25
    # would trip long before max_turns does.
    return app.invoke(initial, config={"recursion_limit": max_turns * 3 + 10})


def run_scene(
    scene: Scene,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    llm=None,
    supervisor_llm=None,
    max_turns: int = DEFAULT_MAX_TURNS,
    initial_log: Sequence[dict] | None = None,
    constraints: Sequence[str] = (),
    memory=None,
) -> tuple[Scene, list[InteractionEntry]]:
    """Simulate a scene and return it with `interaction_log` filled in.

    The structured entries come back alongside it because `Scene.interaction_log`
    holds rendered strings; downstream agents that need turn numbers and speaker
    ids should work from the entries.
    """
    final = simulate_scene(
        scene,
        world,
        characters,
        llm=llm,
        supervisor_llm=supervisor_llm,
        max_turns=max_turns,
        initial_log=initial_log,
        constraints=constraints,
        memory=memory,
    )
    entries = [InteractionEntry.model_validate(e) for e in final["interaction_log"]]
    logger.info(
        "Scene %d finished after %d turns (%s)",
        scene.scene_number,
        final.get("current_turn", 0),
        final.get("stop_reason") or "unknown reason",
    )
    updated = scene.model_copy(update={"interaction_log": [e.render() for e in entries]})
    return updated, entries
