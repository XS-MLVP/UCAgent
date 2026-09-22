"""Declare the RTL2Spec UCAgent plugin."""

from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginWorkflow

from . import __version__
from .checkers import RTL2SpecArtifactsChecker
from .documents import require_clean_output
from .tools import RTL2SpecCommandArgs, create_tools


def prepare_generation(cfg, context: dict) -> dict:
    """Check output before workflow initialization can expose tools or resume saved stages."""
    module = context["DUT"]
    RTL2SpecCommandArgs(action="preflight", module=module)
    require_clean_output(Path(context["WORKSPACE"]), module, context["OUT"])
    return {}


def get_plugin() -> Plugin:
    """Return the validated plugin descriptor and its bundled workflow."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="rtl2spec",
        version=__version__,
        description=(
            "Evidence-based XiangShan Chisel/Scala and elaborated RTL "
            "design-document generation."
        ),
        root=root,
        requires_ucagent=">=26.9.2.dev14",
        python_requirements=("markdown-it-py>=3,<5",),
        command_requirements=(
            CommandRequirement(name="Bash", alternatives=("bash",), version_args=("--version",)),
            CommandRequirement(name="Git", alternatives=("git",), version_args=("--version",)),
            CommandRequirement(name="Curl", alternatives=("curl",), version_args=("--version",)),
            CommandRequirement(name="GNU Make", alternatives=("make",), version_args=("--version",)),
        ),
        tool_factories=(create_tools,),
        checkers=(RTL2SpecArtifactsChecker,),
        assets=(root / "scripts",),
        workflows=(
            PluginWorkflow(
                name="design-document",
                config_file=root / "workflows" / "design-document.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=prepare_generation,
            ),
        ),
    )
