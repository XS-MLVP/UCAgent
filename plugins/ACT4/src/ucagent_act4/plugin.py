"""UCAgent plugin provider for ACT4 generation, extension review, and target handoff."""

from pathlib import Path

from ucagent.plugins import Plugin, PluginWorkflow

from . import __version__
from .checkers.act4_ai_review_checker import ACT4AIReviewChecker
from .checkers.act4_asset_checker import ACT4AssetChecker
from .checkers.act4_file_manifest_checker import ACT4FileManifestChecker
from .checkers.act4_final_report_checker import ACT4FinalReportChecker
from .checkers.act4_switch_capability_checker import ACT4SwitchCapabilityChecker
from .checkers.act4_test_asset_checker import ACT4TestAssetChecker
from .checkers.act4_review_checker import ACT4ReviewChecker
from .checkers.act4_xiangshan_checker import ACT4XiangShanChecker
from .checkers.act4_environment_checker import ACT4EnvironmentChecker
from .workspace import validate_input_paths, validate_xiangshan_paths
from .review_tools import create_review_tools
from .resource_tools import create_resource_tools
from .checkers.act4_resource_checker import ACT4ResourceChecker
from .checkers.act4_generation_inputs_checker import ACT4GenerationInputsChecker
from .checkers.act4_native_assets_checker import ACT4NativeAssetsChecker
from .checkers.act4_native_validation_checker import ACT4NativeValidationChecker
from .checkers.act4_generation_completion_checker import ACT4GenerationCompletionChecker
from .checkers.act4_asset_checklist_checker import ACT4AssetChecklistChecker
from .checkers.act4_generation_run_checker import ACT4GenerationRunChecker


def get_plugin() -> Plugin:
    """Return the ACT4 plugin descriptor and its independent workflows."""

    root = Path(__file__).resolve().parent
    return Plugin(
        name="act4",
        version=__version__,
        description=(
            "Evidence-driven generation, review, validation, and XiangShan handoff of RISC-V ACT4 test assets."
        ),
        root=root,
        tool_factories=(create_review_tools, create_resource_tools),
        checkers=(
            ACT4AIReviewChecker,
            ACT4AssetChecker,
            ACT4FileManifestChecker,
            ACT4FinalReportChecker,
            ACT4SwitchCapabilityChecker,
            ACT4TestAssetChecker,
            ACT4ReviewChecker,
            ACT4XiangShanChecker,
            ACT4EnvironmentChecker,
            ACT4ResourceChecker,
            ACT4GenerationInputsChecker,
            ACT4NativeAssetsChecker,
            ACT4NativeValidationChecker,
            ACT4GenerationCompletionChecker,
            ACT4AssetChecklistChecker,
            ACT4GenerationRunChecker,
        ),
        workflows=(
            PluginWorkflow(
                name="privileged-suite-generation",
                config_file=root / "workflows" / "privileged-suite-generation.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_input_paths,
            ),
            PluginWorkflow(
                name="xiangshan-v3-handoff",
                config_file=root / "workflows" / "xiangshan-v3-handoff.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_xiangshan_paths,
            ),
            PluginWorkflow(
                name="unprivileged-suite-generation",
                config_file=root / "workflows" / "unprivileged-suite-generation.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_input_paths,
            ),
        ),
        requires_ucagent=">=26.9.2.dev25",
        python_requirements=("PyYAML>=6,<7", "jsonschema>=4.18,<5"),
    )
