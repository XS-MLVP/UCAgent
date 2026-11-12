"""Declare the RTL2Spec UCAgent plugin."""

from pathlib import Path

from ucagent.plugins import CommandRequirement, Plugin, PluginWorkflow

from . import __version__
from .checkers import RTL2SpecArtifactsChecker, RTL2SpecGenericArtifactsChecker
from .documents import require_clean_output
from .fmagent_checker import RTL2SpecFMAgentPrepareChecker, RTL2SpecFMAgentExportChecker
from .fmagent_workflow import settings_from_cfg, workflow_paths
from .tools import RTL2SpecCommandArgs, create_tools


def prepare_generation(cfg, context: dict) -> dict:
    """Check output before workflow initialization can expose tools or resume saved stages."""
    validate_fmagent_selection(cfg, context, "xiangshan", False)
    module = context["DUT"]
    RTL2SpecCommandArgs(action="preflight", module=module)
    require_clean_output(Path(context["WORKSPACE"]), context["OUT"])
    return {}


def validate_fmagent_selection(cfg, context: dict, kind: str, enabled: bool) -> None:
    """Enforce explicit workflow selection and protect native outputs only when enabled."""
    settings = settings_from_cfg(cfg)
    if settings.enabled != enabled:
        raise ValueError("fmagent.enabled must match the selected -fmagent workflow; use the original workflow when disabled")
    if enabled:
        workflow_paths(Path(context["WORKSPACE"]), context["DUT"], context["OUT"], kind)


def prepare_fmagent_generation(cfg, context: dict) -> dict:
    """Protect enabled XiangShan outputs before runtime initialization."""
    validate_fmagent_selection(cfg, context, "xiangshan", True)
    RTL2SpecCommandArgs(action="preflight", module=context["DUT"])
    require_clean_output(Path(context["WORKSPACE"]), context["OUT"])
    return {}


def prepare_generic_fmagent_generation(cfg, context: dict) -> dict:
    """Protect enabled generic outputs before runtime initialization."""
    validate_fmagent_selection(cfg, context, "generic", True)
    RTL2SpecCommandArgs(action="generic_preflight", module=context["DUT"])
    require_clean_output(Path(context["WORKSPACE"]), context["OUT"])
    return {}


def prepare_generic_generation(cfg, context: dict) -> dict:
    """Protect generic module outputs before workflow resources are copied."""

    validate_fmagent_selection(cfg, context, "generic", False)
    module = context["DUT"]
    RTL2SpecCommandArgs(action="generic_preflight", module=module)
    require_clean_output(Path(context["WORKSPACE"]), context["OUT"])
    return {}


def get_plugin() -> Plugin:
    """Return the validated plugin descriptor and its bundled workflow."""
    from dataclasses import replace

    root = Path(__file__).resolve().parent
    plugin = Plugin(
        name="rtl2spec",
        version=__version__,
        description=(
            "Evidence-backed XiangShan or user-supplied generic RTL "
            "design-document generation with auditable source evidence."
        ),
        root=root,
        requires_ucagent=">=26.9.2.dev14",
        python_requirements=("markdown-it-py>=3,<5", "pyslang>=9.1,<10"),
        tool_factories=(create_tools,),
        checkers=(RTL2SpecArtifactsChecker, RTL2SpecGenericArtifactsChecker,
                  RTL2SpecFMAgentPrepareChecker, RTL2SpecFMAgentExportChecker),
        assets=(root / "scripts",),
        workflows=(
            PluginWorkflow(
                name="xiangshan-design-document",
                config_file=root / "workflows" / "xiangshan-design-document.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=prepare_generation,
                command_requirements=(
                    CommandRequirement(
                        name="Bash", alternatives=("bash",), version_args=("--version",)
                    ),
                    CommandRequirement(
                        name="Git", alternatives=("git",), version_args=("--version",)
                    ),
                    CommandRequirement(
                        name="Curl", alternatives=("curl",), version_args=("--version",)
                    ),
                    CommandRequirement(
                        name="GNU Make",
                        alternatives=("make",),
                        version_args=("--version",),
                    ),
                ),
            ),
            PluginWorkflow(
                name="generic-design-document",
                config_file=root / "workflows" / "generic-design-document.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
                template_context_factory=prepare_generic_generation,
            ),
        ),
    )
    enabled = tuple(replace(workflow, name=workflow.name + "-fmagent",
                            config_file=root / "workflows" / (workflow.name + "-fmagent.yaml"),
                            template_context_factory=(prepare_generic_fmagent_generation if workflow.name.startswith("generic")
                                                      else prepare_fmagent_generation))
                    for workflow in plugin.workflows)
    return replace(plugin, workflows=plugin.workflows + enabled)
