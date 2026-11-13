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


def validate_review_paths(cfg: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a selected local or Git review input separate from writable output and ISA sources."""
    workspace = Path(context["WORKSPACE"]).resolve()
    directories = []
    for label, value in (("input", cfg.get_value("template_overwrite.ACT4_REVIEW_ROOT")), ("output", context["OUT"])):
        if not isinstance(value, str) or not value.strip() or Path(value).is_absolute() or ".." in Path(value).parts:
            raise PluginError(f"ACT4 review {label} must be a nonempty workspace-relative directory")
        path = workspace / value
        directory = path.resolve()
        if path.is_symlink() or directory == workspace or not directory.is_relative_to(workspace):
            raise PluginError(f"ACT4 review {label} must remain inside the workspace without a symlink root")
        directories.append(directory)
    source, output = directories
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise PluginError("ACT4 review input and output must be separate directories")
    setting = cfg.get_value("template_overwrite.ACT4_MANUAL_ROOT")
    if not isinstance(setting, str) or not setting.strip():
        raise PluginError("ACT4_MANUAL_ROOT must be a nonempty manual repository path")
    manual = Path(setting).expanduser()
    manual = (manual if manual.is_absolute() else workspace / manual).resolve()
    if any(manual.is_relative_to(directory) or directory.is_relative_to(manual) for directory in directories):
        raise PluginError("Read-only ACT4_MANUAL_ROOT must be separate from the review input and output")
    return {}


def validate_xiangshan_paths(cfg: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep V3 handoff writes separate from the source assets and both source checkouts."""
    from .xiangshan_bundle import safe_path

    workspace = Path(context["WORKSPACE"]).resolve()
    try:
        output = safe_path(workspace, context["OUT"])
        for field in ("ACT4_INPUT_ROOT", "ACT4_FRAMEWORK_ROOT", "ACT4_XIANGSHAN_ROOT", "ACT4_MANUAL_ROOT"):
            source = safe_path(workspace, cfg.get_value(f"template_overwrite.{field}"))
            if output.is_relative_to(source) or source.is_relative_to(output):
                raise ValueError(f"Handoff output must be separate from read-only {field}")
    except (ValueError, TypeError) as error:
        raise PluginError(str(error)) from error
    return {}
