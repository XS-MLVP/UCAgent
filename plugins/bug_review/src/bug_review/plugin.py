"""Register the Bug Review analysis workflow and its evidence tools."""
from pathlib import Path

from ucagent.plugins import Plugin, PluginContext, PluginWorkflow
from . import __version__

from .adapter import (
    BugReviewRunStage, BugReviewTasks, BugReviewSubmitResponse,
    BugReviewStatus, BugReviewWaveInfo,
)
from .checkers import BugReviewStageChecker


def create_tools(context: PluginContext) -> list[object]:
    """Create workspace-scoped tools with UCAgent's resolved write policy."""
    common = {
        "workspace": str(context.workspace),
        "output_dir": context.output_dir,
        "write_dirs": list(context.write_dirs),
        "un_write_dirs": list(context.un_write_dirs),
    }
    tool_types = (
        BugReviewRunStage,
        BugReviewTasks,
        BugReviewSubmitResponse,
        BugReviewStatus,
        BugReviewWaveInfo,
    )
    return [tool_type(**common) for tool_type in tool_types]


def get_plugin() -> Plugin:
    """Expose the five-stage analysis workflow and workspace-scoped tools."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="bug_review", version=__version__,
        description="BugReview evidence analysis for one or more DUT workspaces",
        root=root,
        requires_ucagent=">=26.9.2.dev6",
        tool_factories=(create_tools,), checkers=(BugReviewStageChecker,),
        workflows=(PluginWorkflow(
            name="analysis", config_file=root / "workflows" / "analysis.yaml",
            guide_doc_paths=(root / "Guide_Doc" / "analysis.md",),
            template_dir=root / "templates",
            template_target="notes",
            skill_paths=(root / "skills",),
        ),),
    )
