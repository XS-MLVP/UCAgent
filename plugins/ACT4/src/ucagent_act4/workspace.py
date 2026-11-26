"""Validate the workflow's read-only specification input before initialization."""

from pathlib import Path
from typing import Any, Mapping
import json
import os
import sys

from ucagent.plugins import PluginError
from .resources import input_path
from .suite_catalog import validate_suite_target
from .run_config import run_settings, resolve_run_config


def validate_input_paths(cfg: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the catalog target and isolate specification and generated paths."""

    suite_context = validate_suite_target(context.get("DUT"))
    settings = run_settings(cfg)
    if not settings:
        raise PluginError("Generation requires one run YAML; start with act4-run <run.yaml>")
    try:
        raw = {**settings, "assets": {name: ({"mode": "regenerate"} if item["mode"] == "regenerate" else
                                           {key: value for key, value in item.items() if value is not None})
                                     for name, item in settings["assets"].items()}}
        checked = resolve_run_config(raw, Path(settings["workspace"]).parent)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise PluginError(f"Invalid ACT generation configuration: {error}") from error
    if checked != settings or (settings["suite"], settings["workspace"], settings["output"]) != (context["DUT"], str(Path(context["WORKSPACE"]).resolve()), context["OUT"]):
        raise PluginError("Run YAML must match the resolved workflow workspace, suite and output")
    project = cfg.get_value("template_overwrite.PROJECT")
    expected = {"privileged-suite-generation": "act4_priv_suite_generate", "unprivileged-suite-generation": "act4_unprivileged_generate"}
    if project != expected[settings["workflow"]]:
        raise PluginError("Selected workflow conflicts with run YAML workflow")
    if os.environ.get("ACT4_ANNOUNCED_CONFIG") != str(Path(settings["workspace"]) / ".ucagent/act4-run.yaml"):
        arguments = {"DUT": settings["suite"], "WORKSPACE": settings["workspace"], "OUT": settings["output"]}
        for index, token in enumerate(sys.argv[1:], 1):
            flag, separator, value = token.partition("=")
            if flag in {"--loop", "--exit-on-completion", "--mcp-server-no-file-tools", "--no-history"}:
                arguments[flag] = True
            elif flag in {"--backend", "--plugin", "--plugin-workflow", "--config", "--mcp-server-port"} and (separator or index + 1 < len(sys.argv)):
                arguments[flag] = value if separator else sys.argv[index + 1]
        print(json.dumps({"configuration": settings, "arguments": arguments}, ensure_ascii=False, indent=2), flush=True)
    setting = settings["upstream"]["manual_root"]
    if not isinstance(setting, str) or not setting.strip():
        raise PluginError("ACT4_MANUAL_ROOT must be a non-empty manual repository path")
    workspace = Path(context["WORKSPACE"]).resolve()
    output_setting = context["OUT"]
    if not isinstance(output_setting, str) or not output_setting.strip():
        raise PluginError("ACT4 output must be a non-empty workspace-relative directory")
    output = Path(output_setting)
    if output.is_absolute():
        raise PluginError("ACT4 output must be a workspace-relative directory")
    output = (workspace / output).resolve()
    act4_root = (workspace / "riscv-arch-test").resolve()
    for label, directory in (("output", output), ("ACT4 checkout", act4_root)):
        if directory == workspace or not directory.is_relative_to(workspace):
            raise PluginError(f"ACT4 {label} must remain inside the workspace: {directory}")
    if output.is_relative_to(act4_root) or act4_root.is_relative_to(output):
        raise PluginError("ACT4 output must be separate from the ACT4 checkout")
    manual = Path(setting).expanduser()
    if not manual.is_absolute():
        manual = workspace / manual
    manual = manual.resolve()
    for directory in (output, act4_root):
        if manual.is_relative_to(directory) or directory.is_relative_to(manual):
            raise PluginError(
                f"Read-only ACT4_MANUAL_ROOT {manual} overlaps writable directory {directory}; "
                "use a separate manual checkout."
            )
    return {**suite_context, "ACT4_MANUAL_ROOT": setting, "ACT4_ACT_ROOT": settings["upstream"]["act4_root"],
            "ACT4_ACT_REF": settings["upstream"]["act4_ref"], "ACT4_MANUAL_REF": settings["upstream"]["manual_ref"],
            "ACT4_RESOURCE_ROOT": settings["upstream"]["cache_root"], "ACT4_TARGET_CONTEXT": settings["target_context"],
            "ACT4_EXPERIMENTS": settings["limits"]["experiments"], "ACT4_EXPERIMENT_SECONDS": settings["limits"]["experiment_seconds"]}


def validate_xiangshan_paths(cfg: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep V3 handoff writes separate from the source assets and both source checkouts."""
    from .xiangshan_bundle import safe_path

    workspace = Path(context["WORKSPACE"]).resolve()
    try:
        output = safe_path(workspace, context["OUT"])
        for field in ("ACT4_INPUT_ROOT", "ACT4_FRAMEWORK_ROOT", "ACT4_XIANGSHAN_ROOT", "ACT4_MANUAL_ROOT"):
            source = input_path(workspace, cfg.get_value(f"template_overwrite.{field}"))
            if output.is_relative_to(source) or source.is_relative_to(output):
                raise ValueError(f"Handoff output must be separate from read-only {field}")
    except (ValueError, TypeError) as error:
        raise PluginError(str(error)) from error
    return {}
