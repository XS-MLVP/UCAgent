"""UCAgent plugin provider for DesignWithPPA."""

from pathlib import Path

from ucagent.plugins import (
    CommandRequirement,
    Plugin,
    PluginContext,
    PluginWorkflow,
)

from . import __version__
from .ppa import AnalyzePPA
from .consistency import RunDesignConsistency
from .rtl import build_rtl_template_context
from .checkers import (
    DesignAllPassBatchTestsChecker,
    DesignArchitectureChecker,
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignLineMapReferenceChecker,
    DesignMarkdownFileFormatChecker,
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    DesignDutApiChecker,
    DesignLabelStructureChecker,
    DesignPythonAllPassChecker,
    DesignRandomTestCasesChecker,
    DesignRefineTestCasesChecker,
    DesignLabelStructureRefineChecker,
    DesignSpecLineMapBatchChecker,
    DesignTestTemplateChecker,
    PPABaseCharacterizationChecker,
    PPABestVersionChecker,
    PPACandidateOptimizationChecker,
    PPAResultArtifactsChecker,
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    RTLSourceEvidenceChecker,
)


def create_tools(context: PluginContext) -> list[object]:
    """Create the plugin's analysis and full-consistency tools for one workspace."""

    return [
        AnalyzePPA(
            workspace=str(context.workspace),
            output_dir=context.output_dir,
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
        ),
        RunDesignConsistency(
            workspace=str(context.workspace),
            output_dir=context.output_dir,
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
            cfg=context.cfg,
        ),
    ]


def get_plugin() -> Plugin:
    """Return the validated UCAgent contribution descriptor for DesignWithPPA."""

    root = Path(__file__).resolve().parent
    return Plugin(
        name="design-with-ppa",
        version=__version__,
        description=(
            "Pre-layout area, timing, and waveform-driven power analysis for "
            "RTL design iterations."
        ),
        root=root,
        tool_factories=(create_tools,),
        checkers=(
            RTLSourceEvidenceChecker,
            DesignAllPassBatchTestsChecker,
            DesignInputContractChecker,
            DesignMarkdownFileFormatChecker,
            DesignLabelStructureChecker,
            DesignLineMapReferenceChecker,
            DesignObservationContractChecker,
            DesignObservationInstrumentationChecker,
            DesignFunctionalContractChecker,
            DesignArchitectureChecker,
            DesignSpecLineMapBatchChecker,
            DesignLabelStructureRefineChecker,
            DesignRefineTestCasesChecker,
            DesignCoverageStructureChecker,
            DesignCoverageGroupBatchChecker,
            DesignTestTemplateChecker,
            PythonReferenceContractChecker,
            DesignDutApiChecker,
            DesignPythonAllPassChecker,
            PythonAdapterContractChecker,
            PythonEnvFixtureContractChecker,
            PythonExecutableSpecChecker,
            PythonReferenceRegressionChecker,
            RTLBackendBuildChecker,
            RTLLineCoverageChecker,
            RTLAllPassRegressionChecker,
            DesignRandomTestCasesChecker,
            PerformanceContractChecker,
            PerformanceTestContractChecker,
            PerformanceArtifactChecker,
            PPABaseCharacterizationChecker,
            PPACandidateOptimizationChecker,
            PPABestVersionChecker,
            PPAResultArtifactsChecker,
            DesignDocumentationSyncChecker,
            DesignFinalDeliveryChecker,
        ),
        workflows=(
            PluginWorkflow(
                name="unit-design-tdd",
                config_file=root / "workflows" / "unit-design-tdd.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_dir=root / "templates" / "unit_design",
                template_target="{OUT}",
                template_context_factory=build_rtl_template_context,
                skill_paths=(root / "skills",),
                command_requirements=(
                    CommandRequirement(
                        name="Picker",
                        alternatives=("picker",),
                        version_args=("--version",),
                        required_subcommands=("export",),
                    ),
                ),
                runtime_config_keys=(
                    "design_with_ppa.min_optimization_iterations",
                    "design_with_ppa.max_optimization_iterations",
                    "design_with_ppa.no_improvement_patience",
                    "design_with_ppa.no_regression_metrics",
                    "design_with_ppa.score_weights.timing",
                    "design_with_ppa.score_weights.area",
                    "design_with_ppa.score_weights.power",
                    "design_with_ppa.rtl.language",
                    "design_with_ppa.rtl.source_glob",
                    "design_with_ppa.rtl.source_template",
                    "design_with_ppa.rtl.python_dut.interface",
                    "design_with_ppa.ppa.waveform_scope",
                    "design_with_ppa.ppa.liberty_file",
                    "design_with_ppa.ppa.sdc_file",
                    "design_with_ppa.ppa.clock_port",
                    "design_with_ppa.ppa.clock_period_ns",
                    "design_with_ppa.ppa.max_timing_paths",
                    "design_with_ppa.ppa.max_power_instances",
                ),
            ),
        ),
        requires_ucagent=">=26.9.2.dev6",
        python_requirements=(
            "vcdvcd>=2.3.5,<3.0.0",
            "pylibfst>=0.2.1,<0.3.0",
        ),
        command_requirements=(
            CommandRequirement(name="Yosys", alternatives=("yosys",)),
            CommandRequirement(name="OpenSTA", alternatives=("sta", "opensta")),
        ),
        assets=(
            root / "assets" / "NangateOpenCellLibrary_typical.lib",
            root / "assets" / "SOURCE.md",
        ),
    )
