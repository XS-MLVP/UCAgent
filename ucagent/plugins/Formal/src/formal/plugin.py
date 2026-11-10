"""UCAgent plugin provider for the Formal (SVA) verification workflow."""

from pathlib import Path

from ucagent.core.plugins import Plugin, PluginContext, PluginWorkflow

from .execution import ExecutionPolicy
from .tools import RunFormal

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


def create_tools(context: PluginContext) -> list[object]:
    """Bind the managed formal tool to the active resolved workflow context."""
    ExecutionPolicy.from_cfg(context.cfg)
    if not context.dut_name:
        raise ValueError("RunFormal requires a resolved DUT name")
    return [RunFormal(
        workspace=str(context.workspace),
        output_dir=context.output_dir,
        dut=context.dut_name,
        cfg=context.cfg,
        write_dirs=list(context.write_dirs),
        un_write_dirs=list(context.un_write_dirs),
    )]


def get_plugin() -> Plugin:
    """Return the Formal workflow plugin descriptor."""
    return Plugin(
        name="formal",
        version="0.1.0",
        description="Formal (SVA) verification workflow",
        root=root,
        tool_factories=(create_tools,),
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
