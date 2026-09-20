"""Workspace-bound commands for the XiangShan documentation workflow."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ucagent.plugins import PluginContext
from ucagent.tools.fileops import is_file_writeable
from ucagent.tools.uctool import UCTool


class RTL2SpecCommandArgs(BaseModel):
    """Select a plugin action and its exact module/version inputs."""

    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "preflight", "evidence", "metadata", "render", "validate", "lint"
    ] = Field(
        description="preflight checks tools; evidence generates RTL/ports; render creates SVGs; "
        "metadata updates generated fields; validate checks artifacts; lint performs final checks."
    )
    module: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Exact XiangShan module class, e.g. Sbuffer.",
    )
    config: str = Field(
        default="DefaultConfig",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="XiangShan configuration class.",
    )
    version: str = Field(
        default="",
        pattern=r"^(v[0-9]+\.[0-9]+\.[0-9]+)?$",
        description="Target document version, e.g. v1.0.0; required except for preflight.",
    )
    change_type: Literal["Major", "Minor", "Patch"] | None = Field(
        default=None,
        description="For metadata: semantic change category when adding a history row.",
    )
    summary: str = Field(
        default="",
        max_length=1000,
        description="For metadata: one-line change summary, required with change_type.",
    )


class RTL2SpecCommand(UCTool):
    """Run the plugin's packaged commands with bounded output and progress."""

    name: str = "RTL2SpecCommand"
    description: str = (
        "Run RTL2Spec preflight, evidence, render, metadata, validate, or lint "
        "in the active workspace; source must be under third_party/XiangShan. Read stderr/stdout on failure. "
        "Generate evidence before drafting, run metadata after writing, then render and lint."
    )
    args_schema: type[BaseModel] = RTL2SpecCommandArgs
    workspace: str
    write_dirs: list[str] = Field(default_factory=list)
    un_write_dirs: list[str] = Field(default_factory=list)
    command_timeout: int = Field(default=3600, gt=0)

    def _run(
        self,
        action: str,
        module: str,
        config: str = "DefaultConfig",
        version: str = "",
        change_type: str | None = None,
        summary: str = "",
    ) -> dict:
        """Validate paths/policy, execute one fixed action, and return bounded diagnostics."""
        try:
            args = RTL2SpecCommandArgs(
                action=action,
                module=module,
                config=config,
                version=version,
                change_type=change_type,
                summary=summary,
            )
        except ValidationError:
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "Invalid action, module, config, version, or metadata arguments.",
                "next_action": "Use an action from the schema, identifier-only module/config, and a vMAJOR.MINOR.PATCH version.",
            }
        if (
            (action != "preflight" and not args.version)
            or (change_type is not None and not summary.strip())
            or any(char in summary for char in "\r\n|")
            or (action != "metadata" and (change_type or summary))
        ):
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "A version is required except for preflight; history metadata requires a category and one-line summary without table separators.",
                "next_action": "Set version; use change_type and summary only for metadata.",
            }
        workspace = Path(self.workspace).resolve()
        if not workspace.is_dir():
            return {
                "ok": False,
                "error_code": "WORKSPACE_MISSING",
                "error": "Workspace does not exist.",
                "next_action": "Create the workspace and put the XiangShan source under third_party/XiangShan.",
            }

        # Each action has a fixed write footprint; resolved paths must stay in the workspace.
        targets = [".cache"] if action in {"preflight", "evidence", "render"} else []
        if action == "evidence":
            targets += [
                f"evidence/{module}/{version}",
                "third_party/XiangShan/out",
                "third_party/XiangShan/build",
                "third_party/XiangShan/src/main/resources/espresso",
            ]
        elif action == "render":
            targets += [f"evidence/{module}/{version}/diagrams"]
        elif action == "metadata":
            targets += [
                f"outputs/{module}/{module}_design_document_zh_{version}.md",
                f"outputs/{module}/VERSION_HISTORY.md",
                f"reports/{module}/{module}_document_quality_review_{version}.md",
            ]
        for name in [
            *targets,
            f"outputs/{module}",
            f"reports/{module}",
            f"evidence/{module}",
            "third_party/XiangShan",
            ".ucagent/.rtl2spec_receipt_key",
        ]:
            if not (workspace / name).resolve().is_relative_to(workspace):
                return {
                    "ok": False,
                    "error_code": "PATH_OUTSIDE_WORKSPACE",
                    "error": "An input or artifact path resolves outside the workspace.",
                    "artifact": name,
                    "next_action": "Use workspace-local files and directories; remove the external symlink.",
                }
        # Existing children may themselves redirect subprocess writes, even when
        # their parent directory is local. Internal tool-install symlinks are valid.
        for name in targets:
            for directory, dirs, files in os.walk(workspace / name, followlinks=False):
                for entry in (*dirs, *files):
                    path = Path(directory) / entry
                    if path.is_symlink() and not path.resolve().is_relative_to(
                        workspace
                    ):
                        return {
                            "ok": False,
                            "error_code": "PATH_OUTSIDE_WORKSPACE",
                            "error": "A writable tree contains an external symlink.",
                            "artifact": str(path.relative_to(workspace)),
                            "next_action": "Replace the external symlink with a workspace-local path before retrying.",
                        }
        for name in targets:
            permitted, reason = is_file_writeable(
                name, self.un_write_dirs, self.write_dirs
            )
            protected_children = [
                path
                for path in self.un_write_dirs
                if (workspace / path)
                .resolve()
                .is_relative_to((workspace / name).resolve())
            ]
            if not permitted or protected_children:
                return {
                    "ok": False,
                    "error_code": "WRITE_POLICY_DENIED",
                    "error": reason
                    if not permitted
                    else "The action would write beneath a protected path.",
                    "artifact": name,
                    "next_action": "Select the design-document workflow or configure its required write directories without conflicting protected paths.",
                }

        command = [
            sys.executable,
            "-P",
            "-m",
            "rtl2spec.runtime",
            action,
            "--module",
            module,
            "--config",
            config,
            "--version",
            version,
        ]
        if change_type:
            command += ["--change-type", change_type, "--summary", summary]
        env = os.environ.copy()
        # Bind imports and runtime locations to this loaded package and workspace.
        import_root = str(Path(__file__).resolve().parent.parent)
        other_paths = [
            item
            for item in env.get("PYTHONPATH", "").split(os.pathsep)
            if item and item != import_root
        ]
        env.update(
            PYTHONPATH=os.pathsep.join([import_root, *other_paths]),
            PYTHONSAFEPATH="1",
            PYTHONDONTWRITEBYTECODE="1",
            RTL2SPEC_WORKSPACE=str(workspace),
            RTL2SPEC_PYTHON=sys.executable,
            XIANGSHAN_ROOT=str(workspace / "third_party/XiangShan"),
            RTL2SPEC_CACHE=str(workspace / ".cache"),
        )
        started = time.monotonic()
        timed_out = False
        self.put_alive_data(f"Starting {action} for {module} {version}")
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=workspace,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                try:
                    while process.poll() is None:
                        remaining = self.command_timeout - (time.monotonic() - started)
                        if remaining <= 0 or self.is_force_exit():
                            timed_out = True
                            break
                        try:
                            process.wait(timeout=min(5, remaining))
                        except subprocess.TimeoutExpired:
                            self.put_alive_data(
                                f"{action}: running for {int(time.monotonic() - started)} seconds"
                            )
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                output = {}
                for key, stream in (("stdout", stdout), ("stderr", stderr)):
                    size = stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, size - 12000))
                    output[key] = stream.read().decode("utf-8", errors="replace")
                    output[f"{key}_truncated"] = size > 12000
        except OSError as exc:
            return {
                "ok": False,
                "error_code": "COMMAND_UNAVAILABLE",
                "error": str(exc),
                "next_action": "Check Python/Bash availability and the named input or file permission, then retry.",
            }
        result = {
            "ok": not timed_out and process.returncode == 0,
            "action": action,
            "module": module,
            "version": version,
            "returncode": process.returncode,
            **output,
        }
        if not result["ok"]:
            result.update(
                error_code="COMMAND_TIMEOUT"
                if timed_out
                else "RTL2SPEC_COMMAND_FAILED",
                error=f"{action} did not complete successfully.",
                next_action="Inspect stdout/stderr, repair the named environment or artifact problem, then rerun this action.",
            )
        return result


def create_tools(context: PluginContext) -> list[UCTool]:
    """Bind the tool to the active workspace and its resolved write policy."""
    return [
        RTL2SpecCommand(
            workspace=str(context.workspace),
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
            call_time_out=3660,
        )
    ]
