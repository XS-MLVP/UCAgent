"""Register the Bug Review analysis workflow and its evidence tools."""
from pathlib import Path

from ucagent.plugins import Plugin, PluginContext, PluginWorkflow
from . import __version__
from .tools.events import ApplyWaveformEvent
from .tools.investigation import ReviewWorkQueue, ReviewCaseContext, ReviewSignalCatalog

from .checkers import BugReviewStageChecker
from .tools import (ApplyReceiptToCase, CaptureReplayReport, CommitAttribution,
                    CreateAttributionDraft, CreateCaseDraft, CreateDecisionDraft, DescribeReviewSchema,
                    PrepareReviewInventory, RenderBugReviewReport,
                    ResolveReviewCase, ReviewBugContext, ReviewCaseDiff, ReportClaimBlocks,
                    ReviewReceiptSummary, ReviewStageProgress,
                    ReviewRefCheck, ReviewRevisionHistory,
                    SubmitReviewDecisions, UpdateCaseRecords, UpdateReviewRecord, ValidateCaseRecords)


def create_tools(context: PluginContext) -> list[object]:
    """Expose indexed review lookup, schema, source and decision tools."""
    shared = {"workspace": str(context.workspace), "output_dir": context.output_dir}
    return [PrepareReviewInventory(**shared), CaptureReplayReport(**shared),
            ResolveReviewCase(**shared), CreateCaseDraft(**shared),
            ReviewWorkQueue(**shared), ReviewCaseContext(**shared), ReviewSignalCatalog(**shared), ReviewCaseDiff(**shared), ReportClaimBlocks(**shared),
            ReviewReceiptSummary(**shared), ReviewStageProgress(**shared),
            ValidateCaseRecords(**shared),
            ReviewBugContext(**shared), ReviewRefCheck(**shared), DescribeReviewSchema(),
            RenderBugReviewReport(**shared), CreateAttributionDraft(**shared),
            CommitAttribution(**shared), ReviewRevisionHistory(**shared),
            CreateDecisionDraft(**shared),
            ApplyReceiptToCase(**shared), ApplyWaveformEvent(**shared), UpdateReviewRecord(**shared),
            UpdateCaseRecords(**shared),
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
            guide_doc_paths=tuple(root / "Guide_Doc" / name for name in (
                "analysis.md", "bug_review_writing.md", "bug_review_investigation.md", "bug_review_example_rcmd.md",
                "bug_review_example_monitor.md", "bug_review_example_root.md", "bug_review_example_ptw.md")),
            template_dir=root / "templates" / "analysis",
            template_target="verification_review/notes",
            skill_paths=(root / "skills",),
        ),),
    )
