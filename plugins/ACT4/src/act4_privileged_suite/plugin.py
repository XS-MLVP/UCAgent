"""UCAgent plugin provider for ACT4 generation, extension review, and target handoff."""

from pathlib import Path

from ucagent.plugins import Plugin, PluginWorkflow

from . import __version__
from .checkers.act4_ai_review_checker import ACT4AIReviewChecker
from .checkers.act4_asset_checker import ACT4AssetChecker
from .checkers.act4_ctp_reference_checker import ACT4CTPReferenceChecker
from .checkers.act4_file_manifest_checker import ACT4FileManifestChecker
from .checkers.act4_final_report_checker import ACT4FinalReportChecker
from .checkers.act4_manual_reference_checker import ACT4ManualReferenceChecker
from .checkers.act4_switch_capability_checker import ACT4SwitchCapabilityChecker
from .checkers.act4_test_asset_checker import ACT4TestAssetChecker
from .checkers.act4_review_checker import ACT4ReviewChecker
from .checkers.act4_xiangshan_checker import ACT4XiangShanChecker
from .checkers.act4_environment_checker import ACT4EnvironmentChecker
from .workspace import validate_input_paths, validate_review_paths, validate_xiangshan_paths
from .review_tools import create_review_tools


def get_plugin() -> Plugin:
    """Return the ACT4 privileged-suite plugin descriptor."""

    root = Path(__file__).resolve().parent
    return Plugin(
        name="act4-privileged-suite",
        version=__version__,
        description=(
            "Evidence-driven generation, review, validation, and XiangShan handoff of RISC-V ACT4 test assets."
        ),
        root=root,
        tool_factories=(create_review_tools,),
        checkers=(
            ACT4AIReviewChecker,
            ACT4AssetChecker,
            ACT4CTPReferenceChecker,
            ACT4FileManifestChecker,
            ACT4FinalReportChecker,
            ACT4ManualReferenceChecker,
            ACT4SwitchCapabilityChecker,
            ACT4TestAssetChecker,
            ACT4ReviewChecker,
            ACT4XiangShanChecker,
            ACT4EnvironmentChecker,
        ),
        workflows=(
            PluginWorkflow(
                name="privileged-suite-generation",
                config_file=root / "workflows" / "privileged-suite-generation.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_input_paths,
            ),
            PluginWorkflow(
                name="extension-review",
                config_file=root / "workflows" / "extension-review.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_review_paths,
            ),
            PluginWorkflow(
                name="xiangshan-v3-handoff",
                config_file=root / "workflows" / "xiangshan-v3-handoff.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_xiangshan_paths,
            ),
        ),
        requires_ucagent=">=26.9.2.dev25",
        python_requirements=("PyYAML>=6,<7",),
    )
