# -*- coding: utf-8 -*-
"""Restricted command execution for workflow-builder validation stages."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any


class WorkflowCommandError(ValueError):
    """Raised when a requested command violates the execution policy."""


ALLOWED_MAKE_TARGETS = {
    "help",
    "clean",
    "plan",
    "package",
    "check",
    "check_input",
    "check_example",
    "check_config",
    "check_inc_config",
    "check_layout",
    "check_docs",
    "check_tool_specs",
    "check_tools",
    "test_tools",
    "check_checker_specs",
    "check_checkers",
    "test_checkers",
    "check_package",
    "test_mcp",
}
ALLOWED_COMMANDS = {"python", "python3", "bash", "sh", "pytest", "make", "pwd"}
FORBIDDEN_FRAGMENTS = ("sudo", "rm -rf", "curl | bash", "&&", "||", ";", "|", "`", "$(")


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _safe_relative(root: Path, value: str, *, must_exist: bool = False) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not value:
        raise WorkflowCommandError(f"unsafe workspace-relative path: {value}")
    target = (root / path).resolve()
    if not _inside(root, target):
        raise WorkflowCommandError(f"path escapes workflow root: {value}")
    if must_exist and not target.exists():
        raise WorkflowCommandError(f"path does not exist: {value}")
    return target


def parse_restricted_command(command: str, workflow_root: Path) -> list[str]:
    """Parse one command without a shell and enforce the command/path allowlist."""
    if not isinstance(command, str) or not command.strip():
        raise WorkflowCommandError("command is empty")
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in command:
            raise WorkflowCommandError(f"forbidden command fragment: {fragment}")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise WorkflowCommandError(f"invalid command quoting: {exc}") from exc
    if not argv or argv[0] not in ALLOWED_COMMANDS:
        raise WorkflowCommandError(f"command is not allowed: {argv[0] if argv else ''}")

    executable = argv[0]
    if executable in {"python", "python3", "bash", "sh"}:
        if len(argv) != 2 or argv[1].startswith("-"):
            raise WorkflowCommandError("interpreter commands require a tmp/*.py or tmp/*.sh script")
        expected = ".py" if executable in {"python", "python3"} else ".sh"
        script = _safe_relative(workflow_root, argv[1], must_exist=True)
        temp_root = (workflow_root / "tmp").resolve()
        if script.suffix != expected or not script.is_file() or not _inside(temp_root, script):
            raise WorkflowCommandError(
                f"interpreter script must be an existing {expected} file below workflow tmp/"
            )
    elif executable == "make":
        if len(argv) != 2 or argv[1] not in ALLOWED_MAKE_TARGETS:
            raise WorkflowCommandError("make requires exactly one explicitly allowed target")
    elif executable == "pwd" and len(argv) != 1:
        raise WorkflowCommandError("pwd does not accept arguments")
    elif executable == "pytest":
        for value in argv[1:]:
            if value == "-q":
                continue
            if value.startswith("-"):
                raise WorkflowCommandError(f"pytest option is not allowed: {value}")
            _safe_relative(workflow_root, value.split("::", 1)[0], must_exist=True)
    return argv


def run_restricted_command(
    workflow_root: str | Path,
    command: str,
    cwd: str = ".",
    timeout: int = 120,
) -> dict[str, Any]:
    """Run an allowed command and return stable execution evidence."""
    root = Path(workflow_root).resolve()
    if not root.is_dir():
        raise WorkflowCommandError(f"workflow root is not a directory: {root}")
    workdir = _safe_relative(root, cwd or ".", must_exist=True)
    if not workdir.is_dir():
        raise WorkflowCommandError(f"cwd is not a directory: {cwd}")
    timeout_value = int(timeout)
    if timeout_value < 1 or timeout_value > 300:
        raise WorkflowCommandError("timeout must be between 1 and 300 seconds")
    argv = parse_restricted_command(command, root)
    process = subprocess.run(
        argv,
        cwd=workdir,
        text=True,
        capture_output=True,
        timeout=timeout_value,
        shell=False,
    )
    return {
        "ok": process.returncode == 0,
        "return_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "command": command,
        "cwd": workdir.relative_to(root).as_posix() or ".",
        "timeout": timeout_value,
    }
