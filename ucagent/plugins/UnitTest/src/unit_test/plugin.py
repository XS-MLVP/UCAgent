"""UCAgent plugin provider for the UnitTest chip verification workflow."""

from pathlib import Path

from ucagent.core.plugins import Plugin, PluginContext, PluginWorkflow
from ucagent.util.config import Config
from .preparation import prepare_unittest, UnitTestPreparationOptions
from .operations.waveform_replay import waveform_commands
from unit_test.report_store import TestProtocolRuntimeHook
from unit_test.test_runner import RunTestCasesManagerTool
from .waveform import (
    ApplyWaveInfoEvidence,
    ReviewWaveInfoEvidenceBatch,
    WaveInfo,
)
from unit_test.waveform_formats import (
    DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY,
    DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY,
)

from .checkers import (
    GitNotDirtyChecker,
    MustHaveCKs,
    RandomTestCasesChecker,
    Recorder,
    UnityChipBatchCheckerFileLineMap,
    UnityChipBatchCheckerStaticBug,
    UnityChipCheckerBaseFixture,
    UnityChipCheckerBatchTestsImplementation,
    UnityChipCheckerBundleWrapper,
    UnityChipCheckerCoverageGroup,
    UnityChipCheckerCoverageGroupBatchImplementation,
    UnityChipCheckerDutApi,
    UnityChipCheckerDutApiTest,
    UnityChipCheckerDutCreation,
    UnityChipCheckerDutFixture,
    UnityChipCheckerEnvFixture,
    UnityChipCheckerLabelStructure,
    UnityChipCheckerLabelStructureRefine,
    UnityChipCheckerMarkdownFileFormat,
    UnityChipCheckerMockComponent,
    UnityChipCheckerMockFixture,
    UnityChipCheckerRefineTestCases,
    UnityChipCheckerStaticBugFormat,
    UnityChipCheckerStaticBugValidation,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
    UnityChipCheckerTestFree,
    UnityChipCheckerTestMockTestBatch,
    UnityChipCheckerTestMustPass,
    UnityChipCheckerTestTemplate,
    UnityChipCheckerWaveformBugAnalysis,
    VibeWorkSpaceInit,
)

root = Path(__file__).resolve().parent


def create_waveform_tools(context: PluginContext) -> list:
    """Build the UnitTest waveform analysis tools for one workspace.

    Returns an empty list when the config declares no
    ``tools.RunTestCases.test_dir`` so workflows without a pytest test dir
    assemble no waveform tools instead of failing on the missing key.
    """
    try:
        test_dir = context.cfg.get_value("tools.RunTestCases.test_dir", None)
    except AttributeError:
        test_dir = None
    if not isinstance(test_dir, str) or not test_dir.strip():
        return []
    try:
        format_priority = context.cfg.get_value(
            "runtime_options.waveform_analysis_format_priority",
            DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY,
        )
    except AttributeError:
        format_priority = DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY
    tool_waveinfo = WaveInfo(
        workspace=str(context.workspace),
        test_dir=test_dir,
        dut_name=context.dut_name,
        format_priority=format_priority,
        write_dirs=context.cfg.get_value("write_dirs", None),
        un_write_dirs=context.cfg.get_value("un_write_dirs", []),
    )
    tool_apply_waveinfo_evidence = ApplyWaveInfoEvidence(
        waveinfo=tool_waveinfo,
        workspace=str(context.workspace),
        write_dirs=context.cfg.get_value("write_dirs", None),
        un_write_dirs=context.cfg.get_value("un_write_dirs", []),
    )
    return [
        tool_waveinfo,
        tool_apply_waveinfo_evidence,
        ReviewWaveInfoEvidenceBatch(
            evidence_writer=tool_apply_waveinfo_evidence
        ),
    ]


def get_plugin() -> Plugin:
    """Return the UnitTest workflow plugin descriptor."""
    return Plugin(
        name="unittest",
        version="0.1.0",
        description="UnitTest chip verification workflows (unit test, incremental, vibe)",
        root=root,
        tool_factories=(create_waveform_tools,),
        manager_tools=(RunTestCasesManagerTool,),
        runtime_hooks=(TestProtocolRuntimeHook,),
        command_factories=(waveform_commands,),
        checkers=(
            GitNotDirtyChecker,
            MustHaveCKs,
            RandomTestCasesChecker,
            Recorder,
            UnityChipBatchCheckerFileLineMap,
            UnityChipBatchCheckerStaticBug,
            UnityChipCheckerBaseFixture,
            UnityChipCheckerBatchTestsImplementation,
            UnityChipCheckerBundleWrapper,
            UnityChipCheckerCoverageGroup,
            UnityChipCheckerCoverageGroupBatchImplementation,
            UnityChipCheckerDutApi,
            UnityChipCheckerDutApiTest,
            UnityChipCheckerDutCreation,
            UnityChipCheckerDutFixture,
            UnityChipCheckerEnvFixture,
            UnityChipCheckerLabelStructure,
            UnityChipCheckerLabelStructureRefine,
            UnityChipCheckerMarkdownFileFormat,
            UnityChipCheckerMockComponent,
            UnityChipCheckerMockFixture,
            UnityChipCheckerRefineTestCases,
            UnityChipCheckerStaticBugFormat,
            UnityChipCheckerStaticBugValidation,
            UnityChipCheckerTestCase,
            UnityChipCheckerTestCaseWithLineCoverage,
            UnityChipCheckerTestFree,
            UnityChipCheckerTestMockTestBatch,
            UnityChipCheckerTestMustPass,
            UnityChipCheckerTestTemplate,
            UnityChipCheckerWaveformBugAnalysis,
            VibeWorkSpaceInit,
        ),
        workflows=(
            PluginWorkflow(
                name="unittest",
                prepare_workspace=prepare_unittest,
                preparation_schema=UnitTestPreparationOptions,
                config_file=root / "workflows" / "unittest.yaml",
                purpose="Generate and execute unit tests, then produce verified coverage and bug analysis.",
                template_dir=root / "templates" / "unit_test",
                skill_paths=(root / "skills",),
                guide_doc_paths=(root / "Guide_Doc",),
            ),
            PluginWorkflow(
                name="incremental",
                config_file=root / "workflows" / "incremental.yaml",
                purpose="Incrementally add or refine verification against an existing test workspace.",
                template_dir=root / "templates" / "unit_test",
                skill_paths=(root / "skills",),
                guide_doc_paths=(root / "Guide_Doc",),
            ),
            PluginWorkflow(
                name="vibe",
                config_file=root / "workflows" / "vibe.yaml",
                purpose="Perform a lightweight general-purpose coding or investigation task.",
                skill_paths=(root / "skills",),
                guide_doc_paths=(root / "Guide_Doc",),
            ),
        ),
    )
