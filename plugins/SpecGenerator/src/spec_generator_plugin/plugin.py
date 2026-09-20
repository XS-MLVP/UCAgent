"""Declare the XiangShan Spec Generator UCAgent plugin."""

from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginWorkflow

from . import __version__
from .checkers import SpecGeneratorArtifactsChecker
from .tools import create_tools


def get_plugin() -> Plugin:
    """Return the validated plugin descriptor and its bundled workflow."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="xiangshan-spec-generator",
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
        checkers=(SpecGeneratorArtifactsChecker,),
        assets=(root / "scripts",),
        workflows=(
            PluginWorkflow(
                name="design-document",
                config_file=root / "workflows" / "design-document.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
            ),
        ),
    )
