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
    manual = Path(setting).expanduser()
    if not manual.is_absolute():
        manual = workspace / manual
    manual = manual.resolve()
    for output in (workspace / context["OUT"], workspace / "riscv-arch-test"):
        output = output.resolve()
        if manual.is_relative_to(output) or output.is_relative_to(manual):
            raise PluginError(
                f"Read-only ACT4_MANUAL_ROOT {manual} overlaps writable directory {output}; "
                "use a separate manual checkout."
            )
    return {}
