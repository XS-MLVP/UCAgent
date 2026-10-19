"""UCAgent plugin provider for ACT4 privileged-suite asset generation."""

from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginWorkflow

from . import __version__
from .checkers.act4_ai_review_checker import ACT4AIReviewChecker
from .checkers.act4_asset_checker import ACT4AssetChecker
from .checkers.act4_ctp_reference_checker import ACT4CTPReferenceChecker
from .checkers.act4_file_manifest_checker import ACT4FileManifestChecker
from .checkers.act4_final_report_checker import ACT4FinalReportChecker
from .checkers.act4_manual_reference_checker import ACT4ManualReferenceChecker
from .checkers.act4_switch_capability_checker import ACT4SwitchCapabilityChecker
from .checkers.act4_test_asset_checker import ACT4TestAssetChecker
from .workspace import validate_input_paths


def get_plugin() -> Plugin:
    """Return the ACT4 privileged-suite plugin descriptor."""

    root = Path(__file__).resolve().parent
    return Plugin(
        name="act4-privileged-suite",
        version=__version__,
        description=(
            "Evidence-driven generation and validation of RISC-V ACT4 "
            "privileged-suite test assets."
        ),
        root=root,
        checkers=(
            ACT4AIReviewChecker,
            ACT4AssetChecker,
            ACT4CTPReferenceChecker,
            ACT4FileManifestChecker,
            ACT4FinalReportChecker,
            ACT4ManualReferenceChecker,
            ACT4SwitchCapabilityChecker,
            ACT4TestAssetChecker,
        ),
        workflows=(
            PluginWorkflow(
                name="privileged-suite-generation",
                config_file=root / "workflows" / "privileged-suite-generation.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=validate_input_paths,
                command_requirements=(
                    CommandRequirement(name="Bash", alternatives=("bash",), version_args=("--version",)),
                    CommandRequirement(name="Git", alternatives=("git",), version_args=("--version",)),
                    CommandRequirement(name="Curl", alternatives=("curl",), version_args=("--version",)),
                    CommandRequirement(name="GNU Make", alternatives=("make",), version_args=("--version",)),
                ),
            ),
        ),
        requires_ucagent=">=26.9.2.dev25",
        python_requirements=("PyYAML>=6,<7",),
    )
