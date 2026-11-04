"""Workspace-bound commands for the XiangShan and generic RTL workflows."""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ucagent.plugins import PluginContext
from ucagent.tools.fileops import (
    is_file_writeable,
    wildcard_entry_overlaps,
    write_entry_has_wildcards,
)
from ucagent.tools.uctool import UCTool

from .documents import artifact_paths
from .evidence import local_path, output_root


class RTL2SpecCommandArgs(BaseModel):
    """Select a plugin action and its exact module/configuration inputs."""

    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "preflight",
        "evidence",
        "related_sources",
        "metadata",
        "validate",
        "lint",
        "ports",
        "review",
        "finalize",
        "generic_preflight",
        "generic_evidence",
        "generic_related_sources",
        "generic_metadata",
        "generic_validate",
        "generic_lint",
        "generic_ports",
        "generic_review",
        "generic_finalize",
    ] = Field(
        description="preflight/evidence operate on XiangShan; generic_preflight/generic_evidence "
        "capture Verilog/SystemVerilog under inputs/{module}; metadata, validate and lint "
        "operate on the matching workflow. ports generates the exact I/O scaffold; review prepares source-review records; "
        "finalize validates, updates the report and signs validation.json. validate checks a draft; lint also checks review records. "
        "related_sources records XiangShan Scala evidence; "
        "generic_related_sources records input file evidence. Mermaid diagrams remain in Markdown."
    )
    module: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Exact top-level module identifier, e.g. Sbuffer or uart_rx.",
    )
    config: str = Field(
        default="DefaultConfig",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Workflow configuration label; XiangShan uses a configuration class, generic RTL uses a source label.",
    )
    related_modules: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="For related_sources: XiangShan Scala class/object/trait names whose source supports the document.",
    )
    related_files: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="For generic_related_sources: POSIX paths relative to inputs/{module} for source files read as evidence.",
    )

    @field_validator("related_modules")
    @classmethod
    def validate_related_modules(cls, values: list[str]) -> list[str]:
        """Reject ambiguous, duplicated, or path-like related module arguments."""
        if len(set(values)) != len(values) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) for value in values
        ):
            raise ValueError("related_modules must contain unique identifier-only names")
        return values

    @field_validator("related_files")
    @classmethod
    def validate_related_files(cls, values: list[str]) -> list[str]:
        """Reject duplicate, absolute, or escaping generic source paths."""
        if len(set(values)) != len(values) or any(
            not value
            or Path(value).is_absolute()
            or "\\" in value
            or "\x00" in value
            or ".." in Path(value).parts
            for value in values
        ):
            raise ValueError("related_files must contain unique workspace-relative POSIX paths")
        return values


class RTL2SpecCommand(UCTool):
    """Run the plugin's packaged commands with bounded output and progress."""

    name: str = "RTL2SpecCommand"
    description: str = (
        "Run XiangShan or generic RTL2Spec actions in the active workspace. XiangShan actions "
        "use third_party/XiangShan; generic actions capture a supplied Verilog/SystemVerilog "
        "module under inputs/{module}. All artifacts use the selected --output directory. Start with an empty output directory; "
        "For existing output, select a new directory or ask the user to archive and clear it. Generate or capture evidence "
        "before drafting. Use ports for the I/O scaffold, metadata before review, and finalize before Complete. "
        "Mermaid diagrams stay as Markdown source."
    )
    args_schema: type[BaseModel] = RTL2SpecCommandArgs
    workspace: str
    output_dir: str = "outputs"
    write_dirs: list[str] = Field(default_factory=list)
    un_write_dirs: list[str] = Field(default_factory=list)
    command_timeout: int = Field(default=3600, gt=0)

    def _run(
        self,
        action: str,
        module: str,
        config: str = "DefaultConfig",
        related_modules: list[str] | None = None,
        related_files: list[str] | None = None,
    ) -> dict:
        """Validate paths/policy, execute one fixed action, and return bounded diagnostics."""
        try:
            args = RTL2SpecCommandArgs(
                action=action,
                module=module,
                config=config,
                related_modules=related_modules or [],
                related_files=related_files or [],
            )
        except ValidationError:
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "Invalid action, module, or config arguments.",
                "next_action": "Use an action from the schema and identifier-only module/config values.",
            }
        generic = action.startswith("generic_")
        related_action = "generic_related_sources" if generic else "related_sources"
        if action != related_action and (args.related_modules or args.related_files):
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "Related source arguments are only valid for the matching related_sources action.",
                "next_action": (
                    "Read the related input files, then call generic_related_sources with their paths."
                    if generic
                    else "Read the related Scala modules, then call related_sources with their class names."
                ),
            }
        if generic and args.related_modules:
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "related_modules is only valid for the XiangShan related_sources action.",
                "next_action": "Use related_files with generic_related_sources.",
            }
        if not generic and args.related_files:
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": "related_files is only valid for generic_related_sources.",
                "next_action": "Use related_modules with the XiangShan related_sources action.",
            }
        if action == related_action and not (args.related_modules or args.related_files):
            return {
                "ok": False,
                "error_code": "INVALID_ARGUMENTS",
                "error": f"{action} requires at least one related source.",
                "next_action": "Provide the source names or paths actually used by the document.",
            }
        workspace = Path(self.workspace).resolve()
        if not workspace.is_dir():
            return {
                "ok": False,
                "error_code": "WORKSPACE_MISSING",
                "error": "Workspace does not exist.",
                "next_action": (
                    "Create the workspace and put the top-level RTL under inputs/{module}."
                    if generic
                    else "Create the workspace and put the XiangShan source under third_party/XiangShan."
                ),
            }
        # Each action has a fixed write footprint; resolved paths must stay in the workspace.
        try:
            folder = output_root(workspace, self.output_dir)
            evidence = local_path(workspace, folder / "evidence").relative_to(workspace).as_posix()
            documents = [
                path.relative_to(workspace).as_posix()
                for path in artifact_paths(workspace, module, self.output_dir)
            ]
        except ValueError as exc:
            return {
                "ok": False,
                "error_code": "PATH_OUTSIDE_WORKSPACE",
                "error": str(exc),
                "artifact": self.output_dir,
                "next_action": "Select a workspace-local --output subdirectory and remove external symlinks.",
            }
        targets = [".cache"] if action in {"preflight", "evidence"} else []
        if generic:
            targets = []
        if action == "evidence":
            targets += [
                evidence,
                "third_party/XiangShan/out",
                "third_party/XiangShan/build",
                "third_party/XiangShan/src/main/resources/espresso",
            ]
        elif action == "related_sources":
            targets.append(evidence)
        elif action in {"generic_evidence", "generic_related_sources"}:
            targets.append(evidence)
        elif action in {"metadata", "generic_metadata"}:
            targets += documents
        elif action in {"ports", "generic_ports"}:
            targets.append(evidence + "/ports.md")
        elif action in {"review", "generic_review"}:
            targets.append(self.output_dir + "/semantic_review.json")
        elif action in {"finalize", "generic_finalize"}:
            targets += [*documents, self.output_dir + "/validation.json"]
        if action not in {"preflight", "generic_preflight"}:
            targets.append(self.output_dir + "/logs/actions.jsonl")
        for name in [
            *targets,
            self.output_dir,
            evidence,
            f"inputs/{module}",
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
            resolved_name = (workspace / name).resolve().relative_to(workspace).as_posix()
            resolved_permitted, resolved_reason = is_file_writeable(
                resolved_name, self.un_write_dirs, self.write_dirs
            )
            if not resolved_permitted:
                permitted, reason = False, resolved_reason
            protected_children = []
            for path in self.un_write_dirs:
                if write_entry_has_wildcards(path):
                    if wildcard_entry_overlaps(path, name) or wildcard_entry_overlaps(
                        path, resolved_name
                    ):
                        protected_children.append(path)
                elif (workspace / path).resolve().is_relative_to(
                    (workspace / name).resolve()
                ):
                    protected_children.append(path)
            if not permitted or protected_children:
                return {
                    "ok": False,
                    "error_code": "WRITE_POLICY_DENIED",
                    "error": reason
                    if not permitted
                    else "The action would write beneath a protected path.",
                    "artifact": name,
                    "next_action": "Select rtl2spec:xiangshan-design-document or rtl2spec:generic-design-document for the input, and allow writes to the selected --output without conflicting protected paths.",
                }

        if action in {
            "preflight",
            "evidence",
            "generic_preflight",
            "generic_evidence",
        }:
            from .documents import require_clean_output

            try:
                require_clean_output(workspace, self.output_dir)
            except (OSError, ValueError) as exc:
                return {
                    "ok": False,
                    "error_code": "OUTPUT_DIRECTORY_NOT_CLEAN",
                    "error": str(exc),
                    "next_action": "Stop and ask the user to package/archive and clear the selected output directory, or select a new --output and restart.",
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
            "--output",
            self.output_dir,
        ]
        for related in args.related_modules:
            command.extend(["--related-module", related])
        for related in args.related_files:
            command.extend(["--related-file", related])
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
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        timed_out = False
        self.put_alive_data(f"Starting {action} for {module}")
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
            "returncode": process.returncode,
            **output,
        }
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if not result["ok"]:
            result.update(
                error_code="COMMAND_TIMEOUT"
                if timed_out
                else "RTL2SPEC_COMMAND_FAILED",
                error=f"{action} did not complete successfully.",
                next_action="Inspect stdout/stderr, repair the named environment or artifact problem, then rerun this action.",
            )
        # Persist only public operation facts; subprocess output can contain unrelated context.
        if action not in {"preflight", "generic_preflight"} and folder.exists():
            log = folder / "logs/actions.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            record = {"action": action, "module": module, "config": config, "started_at": started_at,
                      "elapsed_seconds": result["elapsed_seconds"], "ok": result["ok"], "returncode": result["returncode"]}
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        return result


def create_tools(context: PluginContext) -> list[UCTool]:
    """Bind the tool to the active workspace and its resolved write policy."""
    return [
        RTL2SpecCommand(
            workspace=str(context.workspace),
            output_dir=context.output_dir,
            write_dirs=list(context.write_dirs),
            un_write_dirs=list(context.un_write_dirs),
            call_time_out=3660,
        )
    ]
