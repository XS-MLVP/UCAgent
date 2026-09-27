"""Register the Bug Review analysis workflow and its evidence tools."""
from pathlib import Path

from ucagent.plugins import Plugin, PluginContext, PluginWorkflow
from . import __version__

from .checkers import BugReviewStageChecker
from .tools import (ApplyReceiptToCase, CaptureReplayReport, CommitAttribution,
                    CreateAttributionDraft, CreateDecisionDraft, DescribeReviewSchema,
                    PrepareReviewInventory, RenderBugReviewReport,
                    ResolveReviewCase, ReviewBugContext, ReviewRefCheck, ReviewRevisionHistory,
                    SubmitReviewDecisions, UpdateReviewRecord, ValidateCaseRecords)


def create_tools(context: PluginContext) -> list[object]:
    """Expose indexed review lookup, schema, source and decision tools."""
    shared = {"workspace": str(context.workspace), "output_dir": context.output_dir}
    return [PrepareReviewInventory(**shared), CaptureReplayReport(**shared),
            ResolveReviewCase(**shared), ValidateCaseRecords(**shared),
            ReviewBugContext(**shared), ReviewRefCheck(**shared), DescribeReviewSchema(),
            RenderBugReviewReport(**shared), CreateAttributionDraft(**shared),
            CommitAttribution(**shared), ReviewRevisionHistory(**shared),
            CreateDecisionDraft(**shared),
            ApplyReceiptToCase(**shared), UpdateReviewRecord(**shared),
            SubmitReviewDecisions(**shared)]


def get_plugin() -> Plugin:
    """Expose the six-stage workflow and its artifact Checker."""
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
            template_dir=root / "templates" / "analysis",
            template_target="notes",
            skill_paths=(root / "skills",),
        ),),
    )
