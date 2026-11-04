"""UCAgent plugin provider for the Formal (SVA) verification workflow."""

from pathlib import Path

from ucagent.plugins import Plugin, PluginWorkflow

from .checkers import (
    BasicInfoStructureChecker,
    BugReportConsistencyChecker,
    CounterexampleTestgenChecker,
    CoverageAnalysisChecker,
    EnvironmentAnalysisChecker,
    FormalSpecJsonChecker,
    FormalSummaryChecker,
    PlanningStructureChecker,
    PropertyStructureChecker,
    ScriptGenerationChecker,
    StaticFormalBugLinkageChecker,
)

root = Path(__file__).resolve().parent


def get_plugin() -> Plugin:
    """Return the Formal workflow plugin descriptor."""
    return Plugin(
        name="formal",
        version="0.1.0",
        description="Formal (SVA) verification workflow",
        root=root,
        checkers=(
            PlanningStructureChecker,
            BasicInfoStructureChecker,
            FormalSpecJsonChecker,
            PropertyStructureChecker,
            ScriptGenerationChecker,
            EnvironmentAnalysisChecker,
            CoverageAnalysisChecker,
            CounterexampleTestgenChecker,
            BugReportConsistencyChecker,
            FormalSummaryChecker,
            StaticFormalBugLinkageChecker,
        ),
        workflows=(
            PluginWorkflow(
                name="formal",
                config_file=root / "workflows" / "formal.yaml",
                template_dir=root / "templates" / "formal_test",
                skill_paths=(root / "skills",),
                guide_doc_paths=(root / "Guide_Doc",),
            ),
        ),
    )
