"""Streamlit workbench.

Run with:  streamlit run src/storyweaver/ui/app.py

`project.py` and `progress.py` hold the logic and import no Streamlit, so the
pages stay thin and the behaviour stays testable.
"""

from storyweaver.ui.progress import GenerationProgress, ProgressEvent, Stage
from storyweaver.ui.project import Project, ProjectStats, ProjectStore, load_sample_project

__all__ = [
    "Project",
    "ProjectStore",
    "ProjectStats",
    "load_sample_project",
    "GenerationProgress",
    "ProgressEvent",
    "Stage",
]
