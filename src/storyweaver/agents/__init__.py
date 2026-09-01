"""Story agents.

The Director casts scenes, Character agents play them out, the Lore Checker
guards continuity, and the Writer turns the result into prose. `episode_runner`
wires all four into one pipeline.
"""

from storyweaver.agents.character import CharacterTurn, act, build_system_prompt
from storyweaver.agents.director import (
    DirectorOutput,
    DraftScene,
    decompose_episode,
    direct_episode,
)
from storyweaver.agents.episode_runner import (
    EpisodePipelineState,
    PipelineModels,
    build_episode_graph,
    run_episode,
)
from storyweaver.agents.lore_checker import ValidationResult, Violation, check
from storyweaver.agents.scene_runner import (
    SceneSimulationState,
    SupervisorVerdict,
    build_scene_graph,
    run_scene,
    simulate_scene,
)
from storyweaver.agents.writer import write_scene

__all__ = [
    # Director
    "decompose_episode",
    "direct_episode",
    "DirectorOutput",
    "DraftScene",
    # Character simulation
    "act",
    "build_system_prompt",
    "CharacterTurn",
    "build_scene_graph",
    "run_scene",
    "simulate_scene",
    "SceneSimulationState",
    "SupervisorVerdict",
    # Lore checking
    "check",
    "ValidationResult",
    "Violation",
    # Writing
    "write_scene",
    # Episode pipeline
    "build_episode_graph",
    "run_episode",
    "EpisodePipelineState",
    "PipelineModels",
]
