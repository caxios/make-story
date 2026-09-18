"""Episode-level LangGraph pipeline: storyline in, finished chapter out.

    START -> director_plan_scenes -> simulate_scene -> check_lore
                                          ^               |
                                          |         failed |-> rerun_scene -+
                                          |               |                 |
                                          |               +<----------------+
                                          |        passed |
                                          |               v
                                          |          write_scene -> advance_scene
                                          |                              |
                                          +---------- yes ---------------+
                                                                         |
                                                              no -> assemble_episode -> END
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from storyweaver.agents import context, director, lore_checker, scene_runner, writer
from storyweaver.agents.checkpoint import CheckpointStore, EpisodeCheckpoint
from storyweaver.agents.prompts import render_prompt
from storyweaver import telemetry
from storyweaver.llm import get_llm
from storyweaver.models import (
    CharacterProfile,
    Episode,
    InteractionEntry,
    Scene,
    WorldLore,
    WritingStyle,
)

logger = logging.getLogger(__name__)

MAX_LORE_RETRIES = 2
SCENE_BREAK = "◇◇◇"


class EpisodeTitle(BaseModel):
    """Structured output for the auto-generated chapter title."""

    title: str = Field(description="A short chapter title, with no episode number")


class EpisodePipelineState(TypedDict, total=False):
    # --- Inputs ---
    world_lore: WorldLore
    characters: dict[str, CharacterProfile]
    episode: Episode
    writing_style: WritingStyle
    # --- Working ---
    current_scene_index: int
    scenes: list[Scene]
    scene_prose_outputs: list[str]
    transitions: list[str]          # bridge sentences, one per scene seam
    current_entries: list[dict]     # structured log for the scene being processed
    constraints: list[str]          # Lore Checker fixes for the current re-run
    retry_count: int                # re-runs spent on the current scene
    lore_reports: list[dict]        # one per scene, for the caller to inspect
    # --- Output ---
    final_episode_text: str


class PipelineModels(BaseModel):
    """Which model each stage uses. All optional; None means the shared default.

    Kept as one object so the seven nodes don't each need their own keyword.
    """

    model_config = {"arbitrary_types_allowed": True}

    director: Any = None
    character: Any = None
    supervisor: Any = None
    lore: Any = None
    writer: Any = None
    titler: Any = None
    summarizer: Any = None
    transition: Any = None


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

def director_plan_scenes(
    state: EpisodePipelineState, models: PipelineModels, memory=None
) -> dict:
    memory_context = ""
    if memory is not None:
        memory_context = memory.build_director_context(state["characters"], state["episode"])

    scenes = director.decompose_episode(
        state["episode"],
        state["world_lore"],
        state["characters"],
        llm=models.director,
        memory_context=memory_context,
    )
    if not scenes:
        raise RuntimeError("The Director produced no usable scenes for this episode")
    logger.info("Directed %d scenes", len(scenes))
    return {
        "scenes": scenes,
        "current_scene_index": 0,
        "scene_prose_outputs": [],
        "transitions": [],
        "lore_reports": [],
        "constraints": [],
        "retry_count": 0,
    }


def simulate_current_scene(
    state: EpisodePipelineState, models: PipelineModels, max_turns: int, memory=None
) -> dict:
    scene = state["scenes"][state["current_scene_index"]]
    final = scene_runner.simulate_scene(
        scene,
        state["world_lore"],
        state["characters"],
        llm=models.character,
        supervisor_llm=models.supervisor,
        max_turns=max_turns,
        memory=memory,
    )
    return {
        "current_entries": final["interaction_log"],
        "constraints": [],
        "retry_count": 0,
    }


def lore_check_current_scene(state: EpisodePipelineState, models: PipelineModels) -> dict:
    scene = state["scenes"][state["current_scene_index"]]
    entries = [InteractionEntry.model_validate(e) for e in state["current_entries"]]

    result = lore_checker.check(
        entries, state["world_lore"], state["characters"], scene=scene, llm=models.lore
    )
    if not result.passed:
        logger.info(
            "Scene %d: %d lore violation(s) on attempt %d",
            scene.scene_number,
            len(result.violations),
            state.get("retry_count", 0) + 1,
        )
    return {"constraints": result.constraints(), "lore_reports": _record(state, scene, result)}


def _record(state: EpisodePipelineState, scene: Scene, result) -> list[dict]:
    """Append this check's verdict to the running report, one entry per attempt."""
    return state.get("lore_reports", []) + [
        {
            "scene_number": scene.scene_number,
            "attempt": state.get("retry_count", 0) + 1,
            "passed": result.passed,
            "violations": [v.model_dump() for v in result.violations],
            "first_bad_turn": result.first_bad_turn,
        }
    ]


def rerun_with_fixes(
    state: EpisodePipelineState, models: PipelineModels, max_turns: int, memory=None
) -> dict:
    """Re-simulate from the earliest offending turn, with the fixes injected.

    Only the tail is redone: everything before the first violation was already
    validated, and rerunning it would throw away good material and re-roll the
    dice on turns that were fine.
    """
    scene = state["scenes"][state["current_scene_index"]]
    report = state["lore_reports"][-1]
    first_bad_turn = report["first_bad_turn"] or 1

    keep = [e for e in state["current_entries"] if e["turn"] < first_bad_turn]
    logger.info(
        "Scene %d: re-running from turn %d, keeping %d earlier turn(s)",
        scene.scene_number,
        first_bad_turn,
        len(keep),
    )

    final = scene_runner.simulate_scene(
        scene,
        state["world_lore"],
        state["characters"],
        llm=models.character,
        supervisor_llm=models.supervisor,
        max_turns=max_turns,
        initial_log=keep,
        constraints=state["constraints"],
        memory=memory,
    )
    return {
        "current_entries": final["interaction_log"],
        "retry_count": state.get("retry_count", 0) + 1,
    }


def write_current_scene(
    state: EpisodePipelineState, models: PipelineModels, memory=None
) -> dict:
    index = state["current_scene_index"]
    scene = state["scenes"][index]
    entries = [InteractionEntry.model_validate(e) for e in state["current_entries"]]

    memory_context = ""
    if memory is not None:
        memory_context = memory.build_writer_context(scene)

    written = state.get("scene_prose_outputs", [])
    prose = writer.write_scene(
        scene,
        state["world_lore"],
        state["characters"],
        entries=entries,
        style=state["writing_style"],
        llm=models.writer,
        memory_context=memory_context,
        # The Writer is shown the previous scene so it can diverge from it.
        previous_prose=written[-1] if written else "",
        pacing=state["episode"].pacing,
    )

    scenes = list(state["scenes"])
    scenes[index] = scene.model_copy(
        update={"interaction_log": [e.render() for e in entries], "prose": prose}
    )
    return {
        "scenes": scenes,
        "scene_prose_outputs": written + [prose],
    }


def write_scene_transition(
    state: EpisodePipelineState, models: PipelineModels, enabled: bool
) -> dict:
    """Bridge the seam between the scene just written and the one before it.

    Runs after `write_scene` rather than before, so both sides of the seam
    exist: a transition written blind into a scene that has not happened yet
    tends to promise something the scene then does not deliver.
    """
    index = state["current_scene_index"]
    prose = state.get("scene_prose_outputs", [])
    if not enabled or index == 0 or len(prose) < 2:
        return {}

    try:
        bridge = writer.write_transition(
            previous_scene=state["scenes"][index - 1],
            next_scene=state["scenes"][index],
            world=state["world_lore"],
            previous_prose=prose[-2],
            next_prose=prose[-1],
            style=state["writing_style"],
            llm=models.transition or models.writer,
        )
    except Exception:  # noqa: BLE001 — a missing bridge is a scene break, not a failure
        logger.exception("Could not write a transition into scene %d", index + 1)
        return {}

    return {"transitions": state.get("transitions", []) + [bridge]}


def checkpoint_episode(state: EpisodePipelineState, store: CheckpointStore | None) -> None:
    """Persist the scenes finished so far, so a later failure is recoverable."""
    if store is None:
        return
    episode = state["episode"]
    store.save(
        EpisodeCheckpoint(
            episode_number=episode.episode_number,
            author_storyline=episode.author_storyline,
            scenes=state.get("scenes", []),
            scene_prose_outputs=state.get("scene_prose_outputs", []),
            transitions=state.get("transitions", []),
            current_scene_index=state.get("current_scene_index", 0) + 1,
            lore_reports=state.get("lore_reports", []),
        )
    )


def advance_to_next_scene(
    state: EpisodePipelineState, store: CheckpointStore | None = None
) -> dict:
    checkpoint_episode(state, store)
    return {
        "current_scene_index": state["current_scene_index"] + 1,
        "current_entries": [],
        "constraints": [],
        "retry_count": 0,
    }


def assemble_final_text(
    state: EpisodePipelineState, models: PipelineModels, auto_title: bool
) -> dict:
    episode = state["episode"]
    scenes = state["scenes"]
    style = state["writing_style"]

    title = episode.title
    if not title and auto_title:
        try:
            title = _generate_title(state, models)
        except Exception:  # noqa: BLE001 — see below
            # The title is the least important thing in the chapter and the
            # last thing made: every scene is already written by the time we
            # get here. Losing all of that to a failed title call is the wrong
            # trade, so the chapter is saved untitled — the author can name it.
            logger.exception(
                "Could not title episode %d; saving it untitled", episode.episode_number
            )
            title = ""

    body = _weave(state.get("scene_prose_outputs", []), state.get("transitions", []))
    header = f"[Episode {episode.episode_number}"
    header += f": {title}]" if title else "]"
    final_text = f"{header}\n\n{body}\n"

    logger.info("Assembled episode %d: %d words", episode.episode_number, len(body.split()))
    return {
        "final_episode_text": final_text,
        "episode": episode.model_copy(
            update={
                "title": title,
                "scenes": scenes,
                "final_text": final_text,
                "status": "completed",
            }
        ),
    }


def _weave(prose: list[str], transitions: list[str]) -> str:
    """Join the scenes, using a bridge sentence where one was written.

    A seam with a transition gets a paragraph break; a seam without one gets the
    scene-break divider, which is what the reader expects when time or place
    jumps without comment.
    """
    if not prose:
        return ""
    parts = [prose[0]]
    for index, scene_prose in enumerate(prose[1:]):
        bridge = transitions[index] if index < len(transitions) else ""
        if bridge:
            parts.append(f"{bridge}\n\n{scene_prose}")
        else:
            parts.append(f"{SCENE_BREAK}\n\n{scene_prose}")
    return "\n\n".join(parts)


def _generate_title(state: EpisodePipelineState, models: PipelineModels) -> str:
    episode = state["episode"]
    world = state["world_lore"]
    prompt = render_prompt(
        "episode_title",
        genre=world.genre,
        tone=world.tone,
        author_storyline=episode.author_storyline,
        scene_titles=context.format_bullets(s.title for s in state["scenes"]),
        language=state["writing_style"].language,
    )
    model = telemetry.meter(models.titler or get_llm(stage="titler"), "titler")
    return model.with_structured_output(EpisodeTitle).invoke(prompt).title.strip()


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------

def lore_check_result(state: EpisodePipelineState) -> str:
    """Route on the last verdict, giving up after MAX_LORE_RETRIES attempts."""
    report = state["lore_reports"][-1]
    if report["passed"]:
        return "passed"
    if state.get("retry_count", 0) >= MAX_LORE_RETRIES:
        logger.warning(
            "Scene %d: accepting %d unresolved violation(s) after %d retries",
            report["scene_number"],
            len(report["violations"]),
            MAX_LORE_RETRIES,
        )
        return "passed"
    return "failed"


def more_scenes(state: EpisodePipelineState) -> str:
    return "yes" if state["current_scene_index"] < len(state["scenes"]) else "no"


def entry_point(state: EpisodePipelineState) -> str:
    """Where a run starts: planning, a scene part-way through, or assembly.

    A resumed run skips the Director. And a run that died after its last scene
    was written — the typical case when the title call fails — has nothing left
    to simulate at all: sending it to `simulate_scene` would index a scene that
    does not exist. It goes straight to assembly instead.
    """
    scenes = state.get("scenes")
    if not scenes:
        return "plan"
    if state.get("current_scene_index", 0) >= len(scenes):
        return "assemble"
    return "resume"


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def build_episode_graph(
    models: PipelineModels | None = None,
    max_turns_per_scene: int = scene_runner.DEFAULT_MAX_TURNS,
    auto_title: bool = True,
    memory=None,
    checkpoints: CheckpointStore | None = None,
    transitions: bool = True,
):
    """Compile the full episode pipeline with its models and memory bound."""
    models = models or PipelineModels()

    graph = StateGraph(EpisodePipelineState)
    graph.add_node("director_plan_scenes", lambda s: director_plan_scenes(s, models, memory))
    graph.add_node(
        "simulate_scene",
        lambda s: simulate_current_scene(s, models, max_turns_per_scene, memory),
    )
    graph.add_node("check_lore", lambda s: lore_check_current_scene(s, models))
    graph.add_node(
        "rerun_scene", lambda s: rerun_with_fixes(s, models, max_turns_per_scene, memory)
    )
    graph.add_node("write_scene", lambda s: write_current_scene(s, models, memory))
    graph.add_node("write_transition", lambda s: write_scene_transition(s, models, transitions))
    graph.add_node("advance_scene", lambda s: advance_to_next_scene(s, checkpoints))
    graph.add_node("assemble_episode", lambda s: assemble_final_text(s, models, auto_title))

    # A resumed run arrives with its scenes already planned, so it re-enters at
    # the simulation step rather than paying the Director a second time.
    graph.add_conditional_edges(
        START,
        entry_point,
        {
            "plan": "director_plan_scenes",
            "resume": "simulate_scene",
            "assemble": "assemble_episode",
        },
    )
    graph.add_edge("director_plan_scenes", "simulate_scene")
    graph.add_edge("simulate_scene", "check_lore")
    graph.add_conditional_edges(
        "check_lore", lore_check_result, {"passed": "write_scene", "failed": "rerun_scene"}
    )
    graph.add_edge("rerun_scene", "check_lore")  # retry loop
    graph.add_edge("write_scene", "write_transition")
    graph.add_edge("write_transition", "advance_scene")
    graph.add_conditional_edges(
        "advance_scene", more_scenes, {"yes": "simulate_scene", "no": "assemble_episode"}
    )
    graph.add_edge("assemble_episode", END)
    return graph.compile()


def stream_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    style: WritingStyle | None = None,
    models: PipelineModels | None = None,
    max_turns_per_scene: int = scene_runner.DEFAULT_MAX_TURNS,
    max_scenes: int = director.DEFAULT_MAX_SCENES,
    auto_title: bool = True,
    memory=None,
    checkpoints: CheckpointStore | None = None,
    transitions: bool = True,
    resume_from: EpisodeCheckpoint | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Run the pipeline, yielding `(node_name, accumulated_state)` after each node.

    Streaming both modes at once gives the node that just ran *and* the state it
    left behind, which is what a progress display needs: a stage name plus
    enough state to say how far through the scenes it is.
    """
    char_map = context.as_character_map(characters)
    _validate(episode, char_map)

    app = build_episode_graph(
        models, max_turns_per_scene, auto_title, memory, checkpoints, transitions
    )
    initial = _initial_state(episode, world, char_map, style, resume_from)

    latest_node: str | None = None
    # Worst case per scene: simulate + (check + rerun) * (MAX_LORE_RETRIES + 1)
    # + write + advance. Plus the director and assembly nodes at either end.
    per_scene = 4 + 2 * (MAX_LORE_RETRIES + 1)
    config = {"recursion_limit": per_scene * max_scenes + 25}

    for mode, chunk in app.stream(initial, stream_mode=["updates", "values"], config=config):
        if mode == "updates":
            latest_node = next(iter(chunk), None)
        elif latest_node is not None:
            yield latest_node, chunk


def _validate(episode: Episode, char_map: Mapping[str, CharacterProfile]) -> None:
    if not char_map:
        raise ValueError("run_episode needs at least one character profile")
    if not episode.author_storyline.strip():
        raise ValueError("run_episode needs an author_storyline to work from")


def _initial_state(
    episode: Episode,
    world: WorldLore,
    char_map: dict[str, CharacterProfile],
    style: WritingStyle | None,
    resume_from: EpisodeCheckpoint | None = None,
) -> EpisodePipelineState:
    resumed: dict[str, Any] = {}
    if resume_from is not None:
        logger.info(
            "Resuming episode %d from scene %d",
            episode.episode_number,
            resume_from.current_scene_index + 1,
        )
        resumed = {
            "scenes": resume_from.scenes,
            "scene_prose_outputs": resume_from.scene_prose_outputs,
            "transitions": resume_from.transitions,
            "current_scene_index": resume_from.current_scene_index,
            "lore_reports": resume_from.lore_reports,
        }

    return {
        "world_lore": world,
        "characters": char_map,
        "episode": episode,
        "writing_style": style or WritingStyle(),
        "current_scene_index": 0,
        "scenes": [],
        "scene_prose_outputs": [],
        "current_entries": [],
        "constraints": [],
        "retry_count": 0,
        "transitions": [],
        "lore_reports": [],
        "final_episode_text": "",
        **resumed,
    }


def run_episode(
    episode: Episode,
    world: WorldLore,
    characters: Mapping[str, CharacterProfile] | Iterable[CharacterProfile],
    style: WritingStyle | None = None,
    models: PipelineModels | None = None,
    max_turns_per_scene: int = scene_runner.DEFAULT_MAX_TURNS,
    max_scenes: int = director.DEFAULT_MAX_SCENES,
    auto_title: bool = True,
    memory=None,
    record_memory: bool = True,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    checkpoints: CheckpointStore | None = None,
    resume: bool = True,
    transitions: bool = True,
    clear_checkpoint: bool = True,
) -> tuple[Episode, dict[str, Any]]:
    """Run an episode end to end.

    Returns the completed `Episode` (scenes, prose and `final_text` filled in)
    alongside the final pipeline state, which carries the Lore Checker's report
    for every scene and attempt.

    With a `MemoryManager`, every stage is given what the story has already
    established, and the finished episode is summarized back into memory —
    which is what makes episode 12 able to refer to episode 3.

    `on_event(node_name, state)` fires after each pipeline node, for progress
    reporting. With a `CheckpointStore`, finished scenes are written to disk as
    they land and a later run picks up where an interrupted one stopped.
    """
    char_map = context.as_character_map(characters)
    _validate(episode, char_map)

    resume_from = None
    if checkpoints is not None and resume:
        candidate = checkpoints.load(episode.episode_number)
        if candidate is None:
            pass
        elif candidate.matches(episode.episode_number, episode.author_storyline):
            resume_from = candidate
        else:
            # The storyline changed, so the saved scenes are the wrong scenes.
            logger.info(
                "Discarding the checkpoint for episode %d: its storyline has changed",
                episode.episode_number,
            )
            checkpoints.clear(episode.episode_number)

    final: dict[str, Any] = _initial_state(episode, world, char_map, style, resume_from)
    for node, state in stream_episode(
        episode,
        world,
        char_map,
        style=style,
        models=models,
        max_turns_per_scene=max_turns_per_scene,
        max_scenes=max_scenes,
        auto_title=auto_title,
        memory=memory,
        checkpoints=checkpoints,
        transitions=transitions,
        resume_from=resume_from,
    ):
        final = state
        if on_event is not None:
            on_event(node, state)

    done = final["episode"]
    if checkpoints is not None and clear_checkpoint:
        # The episode is assembled; the partial record has done its job.
        #
        # A caller that persists the chapter itself should pass
        # `clear_checkpoint=False` and clear it after saving: until the chapter
        # is on disk, the checkpoint is the only copy of the prose, and the
        # summarization below is a slow model call that can outlive the process.
        checkpoints.clear(done.episode_number)

    if memory is not None and record_memory:
        # After the graph, not inside it: a failed summarization should not cost
        # the caller the chapter that was already written.
        try:
            episode_memory = memory.summarize_and_record(
                done,
                world,
                char_map,
                language=final["writing_style"].language,
                llm=(models or PipelineModels()).summarizer,
            )
            final["episode_memory"] = episode_memory
            # The summary also lives on the episode itself, so it is saved with
            # the project, shown to the author, and editable by them — the
            # memory stores hold a copy, not the only copy.
            done = done.model_copy(update={"summary": episode_memory.summary})
            final["episode"] = done
        except Exception:  # noqa: BLE001 — the episode itself is still good
            logger.exception(
                "Episode %d was written but could not be recorded to memory",
                done.episode_number,
            )

    return done, final
