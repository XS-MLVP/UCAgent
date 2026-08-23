# -*- coding: utf-8 -*-
"""UCAgent tool wrapper for the workflow builder."""

from __future__ import annotations

import os
import json
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from ucagent.tools.uctool import UCTool

from .core import WorkflowBuildError, build_workflow, copy_input_example_tree
from .command_runner import WorkflowCommandError, run_restricted_command
from .artifact_inspector import inspect_artifacts
from .environment_preflight import inspect_environment
from .plan_contract import append_record, validate_records


class WorkflowBuilderArgs(BaseModel):
    build_config_path: str = Field(description="Path to workflow_build.yaml, relative to UCAgent workspace by default.")
    base_dir: str = Field(default="", description="Optional base directory for root.path. Defaults to UCAgent workspace.")
    input_example_manifest_path: str = Field(
        default="",
        description=(
            "Optional input-example manifest. When copy_mode=copy_tree, the Builder "
            "copies the declared source tree byte-for-byte into input/example."
        ),
    )


class WorkflowBuilder(UCTool):
    name: str = "WorkflowBuilder"
    description: str = (
        "Build an extensible workflow project skeleton from workflow_build.yaml. "
        "It validates paths, creates directories, renders Makefile/config.yaml, "
        "generates .workflow metadata and basic checkers."
    )
    args_schema: type[BaseModel] = WorkflowBuilderArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _resolve_input_path(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute():
            return path.resolve()
        return (self._workspace_root() / path).resolve()

    def _run(
        self,
        build_config_path: str,
        base_dir: str = "",
        input_example_manifest_path: str = "",
        run_manager=None,
    ) -> str:
        workspace_root = self._workspace_root()
        config_path = self._resolve_input_path(build_config_path)
        if base_dir:
            resolved_base = self._resolve_input_path(base_dir)
        else:
            output_dir = (
                os.environ.get("UCAGENT_OUTPUT", "").strip()
                or os.environ.get("UCAGENT_OUT", "").strip()
            )
            resolved_base = self._resolve_input_path(output_dir) if output_dir else workspace_root
        try:
            report = build_workflow(config_path, resolved_base)
            copied_files: list[str] = []
            if input_example_manifest_path:
                manifest_path = self._resolve_input_path(input_example_manifest_path)
                copied_files = copy_input_example_tree(
                    workspace_root,
                    report.root_path,
                    manifest_path,
                )
        except WorkflowBuildError as exc:
            return str(exc)
        except Exception as exc:
            return f"WORKFLOW-BUILD-TOOL-001: unexpected builder error: {type(exc).__name__}: {exc}"
        return (
            "WorkflowBuilder completed\n"
            f"- workflow: {report.workflow_name}\n"
            f"- root: {report.root_path}\n"
            f"- created_dirs: {len(report.created_dirs)}\n"
            f"- created_files: {len(report.created_files)}\n"
            f"- skipped_files: {len(report.skipped_files)}\n"
            f"- copied_example_files: {len(copied_files)}\n"
            "Next step: cd <root> && make check"
        )


class WorkflowCommandRunnerArgs(BaseModel):
    workflow_root: str = Field(
        description="Generated workflow root relative to the UCAgent workspace."
    )
    command: str = Field(
        description=(
            "One allowlisted command: an approved make target, pytest path, pwd, "
            "or a Python/Shell script below the generated workflow's tmp/ directory."
        )
    )
    cwd: str = Field(
        default=".",
        description="Command working directory relative to workflow_root.",
    )
    timeout: int = Field(default=120, description="Timeout from 1 to 300 seconds.")


class WorkflowCommandRunner(UCTool):
    """Run deterministic checks inside a generated workflow without shell expansion."""

    name: str = "WorkflowCommandRunner"
    description: str = (
        "Run an explicitly allowed validation command inside a generated workflow. "
        "Make targets are allowlisted, interpreter scripts must stay below tmp/, "
        "and shell composition, absolute paths and parent traversal are rejected."
    )
    args_schema: type[BaseModel] = WorkflowCommandRunnerArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _run(
        self,
        workflow_root: str,
        command: str,
        cwd: str = ".",
        timeout: int = 120,
        run_manager=None,
    ) -> str:
        workspace = self._workspace_root()
        relative = Path(workflow_root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return "WORKFLOW-CMD-001: workflow_root must be workspace-relative"
        root = (workspace / relative).resolve()
        if workspace not in root.parents:
            return "WORKFLOW-CMD-001: workflow_root escapes the UCAgent workspace"
        try:
            result = run_restricted_command(root, command, cwd=cwd, timeout=timeout)
        except (WorkflowCommandError, OSError, subprocess.SubprocessError, ValueError) as exc:
            return f"WORKFLOW-CMD-002: {exc}"
        return (
            f"WorkflowCommandRunner {'passed' if result['ok'] else 'failed'}\n"
            f"- command: {result['command']}\n"
            f"- cwd: {result['cwd']}\n"
            f"- return_code: {result['return_code']}\n"
            f"- stdout:\n{result['stdout']}\n"
            f"- stderr:\n{result['stderr']}"
        )


class WorkflowArtifactInspectorArgs(BaseModel):
    workflow_root: str = Field(
        description="Generated workflow root relative to the UCAgent workspace."
    )
    action: str = Field(
        description=(
            "Read-only inspection action: yaml_summary, release_tree, or "
            "migration_manifest."
        )
    )
    path: str = Field(
        default="",
        description="Workflow-relative YAML path for yaml_summary; ignored otherwise.",
    )


class WorkflowArtifactInspector(UCTool):
    """Return structured evidence without creating one-off validation scripts."""

    name: str = "WorkflowArtifactInspector"
    description: str = (
        "Inspect generated workflow YAML shape, release-tree cleanliness, or migration "
        "manifest consistency using fixed read-only logic. It never edits artifacts and "
        "keeps acceptance_rules.yaml as the authority for required public paths."
    )
    args_schema: type[BaseModel] = WorkflowArtifactInspectorArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _run(
        self,
        workflow_root: str,
        action: str,
        path: str = "",
        run_manager=None,
    ) -> str:
        workspace = self._workspace_root()
        relative = Path(workflow_root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return "WORKFLOW-INSPECT-001: workflow_root must be workspace-relative"
        root = (workspace / relative).resolve()
        if workspace not in root.parents or not root.is_dir():
            return "WORKFLOW-INSPECT-001: workflow_root is outside the workspace or missing"
        try:
            result = inspect_artifacts(root, action=action, path=path)
        except Exception as exc:
            return f"WORKFLOW-INSPECT-002: {type(exc).__name__}: {exc}"
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


class WorkflowEnvironmentPreflightArgs(BaseModel):
    workflow_root: str = Field(
        description="Generated workflow root relative to the UCAgent workspace."
    )
    include_tmux: bool = Field(
        default=True,
        description="Inspect tmux global proxy variables in addition to this process.",
    )


class WorkflowEnvironmentPreflight(UCTool):
    """Diagnose Python, UCAgent, proxy, tmux, and generated setup prerequisites."""

    name: str = "WorkflowEnvironmentPreflight"
    description: str = (
        "Perform a read-only environment preflight for a generated workflow. It reports "
        "the active Python and UCAgent paths, process and tmux proxy variables, unsupported "
        "proxy schemes, and missing setup files without changing the environment."
    )
    args_schema: type[BaseModel] = WorkflowEnvironmentPreflightArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _run(
        self,
        workflow_root: str,
        include_tmux: bool = True,
        run_manager=None,
    ) -> str:
        workspace = self._workspace_root()
        relative = Path(workflow_root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return "WORKFLOW-ENV-001: workflow_root must be workspace-relative"
        root = (workspace / relative).resolve()
        if workspace not in root.parents or not root.is_dir():
            return "WORKFLOW-ENV-001: workflow_root is outside the workspace or missing"
        try:
            result = inspect_environment(root, include_tmux=include_tmux)
        except Exception as exc:
            return f"WORKFLOW-ENV-002: {type(exc).__name__}: {exc}"
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


class WorkflowPlanAppenderArgs(BaseModel):
    plan_path: str = Field(
        default="wfgen/workflow_implementation_plan.md",
        description="Existing implementation-plan path under wfgen/.",
    )
    stage_name: str = Field(
        description="Current workflow-builder stage name from config.yaml."
    )
    stage_record: str = Field(
        description=(
            "Markdown record containing the five required level-three headings: "
            "阶段目标、决策与变更、产物与验证证据、问题与处理、后续约束."
        )
    )


class WorkflowPlanAppender(UCTool):
    """Append one validated stage record without rewriting prior plan content."""

    name: str = "WorkflowPlanAppender"
    description: str = (
        "Append the current workflow-builder stage record to the living implementation "
        "plan. The tool enforces stage order, required sections, minimum detail, and a "
        "SHA256 chain over all prior bytes. It never replaces existing plan content."
    )
    args_schema: type[BaseModel] = WorkflowPlanAppenderArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _run(
        self,
        stage_name: str,
        stage_record: str,
        plan_path: str = "wfgen/workflow_implementation_plan.md",
        run_manager=None,
    ) -> str:
        workspace = self._workspace_root()
        relative = Path(plan_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return "WORKFLOW-PLAN-001: plan_path must be a relative path under wfgen/"
        if relative.parts[0] != "wfgen":
            return "WORKFLOW-PLAN-002: plan_path must be under wfgen/"
        target = (workspace / relative).resolve()
        if workspace not in target.parents or not target.is_file():
            return f"WORKFLOW-PLAN-003: existing plan file not found: {plan_path}"
        try:
            original = target.read_text(encoding="utf-8")
            updated = append_record(original, stage_name, stage_record)
            problems = validate_records(updated, stage_name)
            if problems:
                return f"WORKFLOW-PLAN-004: appended plan failed validation: {problems}"
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                delete=False,
            ) as stream:
                stream.write(updated)
                temp_path = Path(stream.name)
            temp_path.replace(target)
        except (OSError, UnicodeError, ValueError) as exc:
            return f"WORKFLOW-PLAN-005: {exc}"
        return (
            f"Workflow plan stage appended: {stage_name}\n"
            f"- plan: {plan_path}\n"
            f"- total_characters: {len(updated)}"
        )
