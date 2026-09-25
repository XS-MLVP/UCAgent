"""Register the Bug Review analysis workflow and its evidence tools."""
from pathlib import Path

from ucagent.plugins import Plugin, PluginWorkflow
from . import __version__

from .checkers import BugReviewStageChecker


def get_plugin() -> Plugin:
    """Expose the five-stage workflow and its artifact Checker."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="bug_review", version=__version__,
        description="BugReview evidence analysis for one or more DUT workspaces",
        root=root,
        requires_ucagent=">=26.9.2.dev6",
        checkers=(BugReviewStageChecker,),
        workflows=(PluginWorkflow(
            name="analysis", config_file=root / "workflows" / "analysis.yaml",
            guide_doc_paths=(root / "Guide_Doc" / "analysis.md",),
            template_dir=root / "templates" / "analysis",
            template_target="notes",
            skill_paths=(root / "skills",),
        ),),
    )
