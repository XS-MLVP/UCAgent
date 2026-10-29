"""Validate the workflow's read-only specification input before initialization."""

from pathlib import Path
from typing import Any, Mapping

from ucagent.plugins import PluginError


def validate_input_paths(cfg: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the manual separate from generated assets and the ACT4 checkout."""

    setting = cfg.get_value("template_overwrite.ACT4_MANUAL_ROOT")
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
    return {}
