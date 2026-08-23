# -*- coding: utf-8 -*-
"""UCAgent tool wrapper for evaluation workflow control."""

from __future__ import annotations

import json
import os
import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ucagent.tools.uctool import UCTool

from .core import EvaluationControlError, evaluation_control_action
from .incremental import IncrementalDeploymentError, deploy_incremental_changes
from .incremental_runs import (
    IncrementalRunError,
    record_command_receipt,
    stage_incremental_candidates,
)
from .json_store import (
    JsonStoreError,
    aggregate_summary,
    document_record_template,
    initialize_workspace,
    load_document,
    mutate_document,
    update_run_request,
    validate_workspace,
)
from .static_audit import run_static_audit


class IncrementalContextFileUpdate(BaseModel):
    path: str = Field(description="Existing report file path to enrich.")
    purpose: str = Field(description="Concrete purpose of this file.")
    contract: str = Field(description="Important interface or behavioral contract.")
    synchronizes_with: list[str] = Field(
        default_factory=list,
        description="Related files whose contracts must remain synchronized.",
    )


class IncrementalContextInventoryArgs(BaseModel):
    action: str = Field(
        default="initialize",
        description="Operation: initialize, update, or validate.",
    )
    workflow_root: str = Field(default="workflow", description="Generated workflow root relative to workspace.")
    resource_root: str = Field(default="res", description="User-maintained resource root relative to workspace.")
    output_path: str = Field(
        default="tmp/incremental_context_report.json",
        description="Context-report skeleton path below tmp.",
    )
    overwrite: bool = Field(default=False, description="Replace an earlier temporary context skeleton.")
    architecture: str = Field(default="", description="Optional architecture analysis for update.")
    runtime_flow: str = Field(default="", description="Optional runtime-flow analysis for update.")
    approved_change_impact: str = Field(
        default="",
        description="Optional approved-change impact analysis for update.",
    )
    cross_file_risks: str = Field(default="", description="Optional cross-file risk analysis for update.")
    file_updates: list[IncrementalContextFileUpdate] = Field(
        default_factory=list,
        description="File analyses to merge atomically during update.",
    )


class IncrementalContextInventory(UCTool):
    """Create, update, and validate the deterministic incremental context report."""

    name: str = "IncrementalContextInventory"
    description: str = (
        "Initialize the required file-and-SHA256 inventory below tmp, atomically merge agent analysis into "
        "known records, or validate the completed report. Use action=update instead of editing JSON directly."
    )
    args_schema: type[BaseModel] = IncrementalContextInventoryArgs

    @staticmethod
    def _category(relative: str) -> str:
        if relative.startswith("res/") or "/input/" in relative:
            return "resource"
        if "/docs/" in relative or "/Guide_Doc/" in relative or relative.endswith("/README.md"):
            return "documentation"
        if "/tools/" in relative:
            return "tool"
        if "/checkers/" in relative:
            return "checker"
        if "/tool_specs/" in relative or "/tool_tests/" in relative:
            return "tool_contract"
        if "/checker_specs/" in relative or "/checker_tests/" in relative:
            return "checker_contract"
        if relative.endswith((".yaml", ".yml")):
            return "configuration"
        return "environment"

    def _run(
        self,
        action: str = "initialize",
        workflow_root: str = "workflow",
        resource_root: str = "res",
        output_path: str = "tmp/incremental_context_report.json",
        overwrite: bool = False,
        architecture: str = "",
        runtime_flow: str = "",
        approved_change_impact: str = "",
        cross_file_risks: str = "",
        file_updates: list[IncrementalContextFileUpdate | dict[str, Any]] | None = None,
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        output = (workspace / output_path).resolve()
        allowed = (workspace / "tmp").resolve()
        try:
            if output != allowed and allowed not in output.parents:
                raise ValueError("output_path must stay below tmp")
            # Keep the inventory implementation identical to the stage gate's required-file calculation.
            from .uc_checkers import IncrementalContextReportChecker

            checker = IncrementalContextReportChecker(
                workflow_root=workflow_root,
                report_path=output_path,
                resource_root=resource_root,
            )
            workflow = (workspace / workflow_root).resolve()
            resource = (workspace / resource_root).resolve()
            if action == "initialize":
                if output.exists() and not overwrite:
                    raise ValueError("context skeleton already exists; set overwrite=true to refresh it")
                paths = sorted(checker._required_files(workspace, workflow, resource))
                records = []
                for path in paths:
                    relative = path.relative_to(workspace).as_posix()
                    records.append(
                        {
                            "path": relative,
                            "category": self._category(relative),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "purpose": "",
                            "contract": "",
                            "synchronizes_with": [],
                        }
                    )
                report = {
                    "contract_version": 1,
                    "workflow_root": workflow_root,
                    "files": records,
                    "architecture": "",
                    "runtime_flow": "",
                    "approved_change_impact": "",
                    "cross_file_risks": "",
                }
                self._atomic_report_write(output, report)
                result = {
                    "message": "incremental context skeleton created; every record still requires agent analysis",
                    "output_path": output_path,
                    "file_count": len(records),
                }
            elif action == "update":
                try:
                    report = json.loads(output.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"context report is malformed at line {exc.lineno}, column {exc.colno}"
                    ) from exc
                records = report.get("files")
                if not isinstance(records, list):
                    raise ValueError("context report files must be an array")
                indexed = {
                    item.get("path"): item
                    for item in records
                    if isinstance(item, dict) and item.get("path")
                }
                updates = [
                    item.model_dump() if isinstance(item, IncrementalContextFileUpdate) else item
                    for item in (file_updates or [])
                ]
                seen: set[str] = set()
                for item in updates:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        raise ValueError("every file update requires a path")
                    relative = item["path"]
                    if relative in seen:
                        raise ValueError(f"duplicate file update: {relative}")
                    seen.add(relative)
                    if relative not in indexed:
                        raise ValueError(f"file update is not in the initialized inventory: {relative}")
                    target = (workspace / relative).resolve()
                    if not target.is_file():
                        raise ValueError(f"file update target no longer exists: {relative}")
                    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                    if indexed[relative].get("sha256") != current_hash:
                        raise ValueError(f"file changed after inventory initialization: {relative}")
                    purpose = item.get("purpose", "")
                    contract = item.get("contract", "")
                    links = item.get("synchronizes_with", [])
                    if (
                        not isinstance(purpose, str)
                        or len(purpose.strip()) < 10
                        or not isinstance(contract, str)
                        or len(contract.strip()) < 10
                        or not isinstance(links, list)
                        or any(not isinstance(link, str) for link in links)
                    ):
                        raise ValueError(f"file update lacks concrete structured analysis: {relative}")
                    indexed[relative].update(
                        purpose=purpose.strip(),
                        contract=contract.strip(),
                        synchronizes_with=links,
                    )
                summaries = {
                    "architecture": architecture,
                    "runtime_flow": runtime_flow,
                    "approved_change_impact": approved_change_impact,
                    "cross_file_risks": cross_file_risks,
                }
                for field, value in summaries.items():
                    if value:
                        if not isinstance(value, str) or len(value.strip()) < 40:
                            raise ValueError(f"{field} must contain at least 40 characters")
                        report[field] = value.strip()
                if not updates and not any(summaries.values()):
                    raise ValueError("update requires file_updates or at least one summary field")
                self._atomic_report_write(output, report)
                result = {
                    "message": "incremental context report updated atomically",
                    "output_path": output_path,
                    "updated_file_count": len(updates),
                }
            elif action == "validate":
                checker.workspace = str(workspace)
                passed, details = checker.do_check()
                result = {"valid": passed, **details}
            else:
                raise ValueError("action must be initialize, update, or validate")
        except (OSError, ValueError) as exc:
            return f"INC-CONTEXT-001: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @staticmethod
    def _atomic_report_write(output: Path, report: dict[str, Any]) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, output)
        finally:
            Path(temporary_name).unlink(missing_ok=True)


class StructuredJsonStoreArgs(BaseModel):
    action: str = Field(
        description="Operation: initialize, validate, template, get_document, list, get, create, update, delete, upsert, "
        "request_run, or aggregate."
    )
    document: str = Field(default="", description="Allowlisted eval/*.json or res/*.json document.")
    record: dict = Field(default_factory=dict, description="Structured record for create, update, or upsert.")
    record_id: str = Field(default="", description="Stable id or run_id for a collection record.")
    expected_revision: int | None = Field(default=None, ge=0, description="Optional optimistic-lock revision.")
    mode: str = Field(default="default", description="Runtime mode for request_run: default or inc.")
    workflow_root: str = Field(default="workflow", description="Generated workflow root for request_run.")
    target: str = Field(default="example", description="Generated workflow input target for request_run.")
    stall_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    max_runtime_seconds: int = Field(default=1800, ge=30, le=14400)


class StructuredJsonStore(UCTool):
    """Safely read and mutate the fixed evaluation JSON contracts."""

    name: str = "StructuredJsonStore"
    description: str = (
        "Initialize, validate, query, and atomically mutate allowlisted eval/res JSON documents. "
        "It enforces schemas, stable record identifiers, revisions, path boundaries, and mutation audit events; "
        "evaluation and incremental agents must use this tool instead of editing structured JSON directly."
    )
    args_schema: type[BaseModel] = StructuredJsonStoreArgs

    def _run(
        self,
        action: str,
        document: str = "",
        record: dict | None = None,
        record_id: str = "",
        expected_revision: int | None = None,
        mode: str = "default",
        workflow_root: str = "workflow",
        target: str = "example",
        stall_timeout_seconds: int = 300,
        max_runtime_seconds: int = 1800,
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        try:
            if action == "initialize":
                result = initialize_workspace(workspace)
            elif action == "validate":
                result = validate_workspace(workspace)
            elif action == "get_document":
                result = load_document(workspace, document)
            elif action == "template":
                result = document_record_template(document)
            elif action == "aggregate":
                result = aggregate_summary(workspace)
            elif action == "request_run":
                result = update_run_request(
                    workspace, mode, workflow_root, target, stall_timeout_seconds, max_runtime_seconds
                )
            else:
                result = mutate_document(
                    workspace,
                    action,
                    document,
                    record=record or None,
                    record_id=record_id,
                    expected_revision=expected_revision,
                )
        except JsonStoreError as exc:
            return f"EVAL-JSON-001: {exc}"
        except Exception as exc:
            return f"EVAL-JSON-002: unexpected JSON store error: {type(exc).__name__}: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)


class EvaluationCommandRunnerArgs(BaseModel):
    workflow_root: str = Field(default="workflow", description="Generated workflow root relative to workspace.")
    command: str = Field(description="Allowlisted command identifier.")
    timeout_seconds: int = Field(default=300, ge=1, le=1800)


class EvaluationCommandRunner(UCTool):
    """Run a small allowlist of non-interactive checks inside the generated workflow."""

    name: str = "EvaluationCommandRunner"
    description: str = (
        "Execute one fixed, non-shell validation command inside the generated workflow and return bounded stdout, "
        "stderr, and exit status. It cannot start UCAgent, invoke arbitrary shell text, write outside the outer tmp "
        "directory, or run commands not explicitly registered by this implementation."
    )
    args_schema: type[BaseModel] = EvaluationCommandRunnerArgs
    COMMANDS: ClassVar[dict[str, list[str]]] = {
        "check": ["make", "check"],
        "config": ["make", "check_config"],
        "docs": ["make", "check_docs"],
        "check_config": ["make", "check_config"],
        "check_docs": ["make", "check_docs"],
        "check_tools": ["make", "check_tools"],
        "test_tools": ["make", "test_tools"],
        "check_checkers": ["make", "check_checkers"],
        "test_checkers": ["make", "test_checkers"],
        "configure-check": ["make", "configure-check"],
        "make_check": ["make", "check"],
        "make_check_config": ["make", "check_config"],
        "make_check_docs": ["make", "check_docs"],
        "make_check_tools": ["make", "check_tools"],
        "make_test_tools": ["make", "test_tools"],
        "make_check_checkers": ["make", "check_checkers"],
        "make_test_checkers": ["make", "test_checkers"],
        "make_configure_check": ["make", "configure-check"],
    }

    def _run(self, workflow_root: str = "workflow", command: str = "", timeout_seconds: int = 300, run_manager=None) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        root = (workspace / workflow_root).resolve()
        try:
            if root != workspace and workspace not in root.parents:
                raise ValueError("workflow_root escapes workspace")
            if not root.is_dir():
                raise ValueError("workflow_root does not exist")
            argv = self.COMMANDS.get(command)
            if argv is None:
                raise ValueError(
                    f"unsupported command: {command}; allowed commands: {', '.join(sorted(self.COMMANDS))}"
                )
            command_tmp = workspace / "tmp" / "eval_commands"
            command_tmp.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment["TMPDIR"] = str(command_tmp)
            result = subprocess.run(
                argv,
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            payload = {
                "command": command,
                "argv": argv,
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-12000:],
                "stderr_tail": result.stderr[-12000:],
            }
            run_id = os.environ.get("UCAGENT_INC_RUN_ID", "")
            if run_id:
                payload = record_command_receipt(
                    workspace,
                    run_id,
                    workflow_root,
                    payload,
                )
        except (OSError, ValueError, subprocess.TimeoutExpired, IncrementalRunError) as exc:
            failure = {
                "command": command,
                "argv": self.COMMANDS.get(command, []),
                "returncode": -1,
                "stdout_tail": "",
                "stderr_tail": str(exc),
                "execution_error": type(exc).__name__,
            }
            run_id = os.environ.get("UCAGENT_INC_RUN_ID", "")
            if run_id and command in self.COMMANDS:
                try:
                    failure = record_command_receipt(
                        workspace,
                        run_id,
                        workflow_root,
                        failure,
                    )
                except (OSError, IncrementalRunError):
                    pass
            return json.dumps(failure, indent=2, ensure_ascii=False)
        return json.dumps(payload, indent=2, ensure_ascii=False)


class StaticEvaluationAuditArgs(BaseModel):
    workflow_root: str = Field(default="workflow", description="Generated workflow root relative to workspace.")
    output_path: str = Field(
        default="tmp/eval_static_audit/audit.json",
        description="Audit result path below tmp/eval_static_audit.",
    )


class StaticEvaluationAudit(UCTool):
    """Run deterministic configuration, path, dependency, and source-contract checks."""

    name: str = "StaticEvaluationAudit"
    description: str = (
        "Read a generated workflow and deterministically audit YAML parsing, placeholder closure, concrete file "
        "paths, stage provenance, Python syntax, and Checker descriptions. The audit never imports generated "
        "code or starts a child workflow, and its structured evidence can only be written below tmp/eval_static_audit."
    )
    args_schema: type[BaseModel] = StaticEvaluationAuditArgs

    def _run(
        self,
        workflow_root: str = "workflow",
        output_path: str = "tmp/eval_static_audit/audit.json",
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        target = (workspace / output_path).resolve()
        allowed = (workspace / "tmp" / "eval_static_audit").resolve()
        run_allowed = (workspace / "tmp" / "inc_runs").resolve()
        try:
            if (
                target != allowed
                and allowed not in target.parents
                and run_allowed not in target.parents
            ):
                raise ValueError("output_path must stay below controlled evaluation or incremental tmp roots")
            result = run_static_audit(workspace, workflow_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except (OSError, ValueError) as exc:
            return f"EVAL-AUDIT-001: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)


class EvaluationControlArgs(BaseModel):
    action: str = Field(description="Operation: initialize, status, block, skip, terminate, continue, or complete.")
    control_path: str = Field(default="evaluation/control.yaml", description="Control-state YAML relative to workspace.")
    stage_name: str = Field(default="", description="Current or blocking evaluation stage name.")
    reason_code: str = Field(default="", description="Stable machine-readable failure or skip reason.")
    reason: str = Field(default="", description="Human-readable failure or skip explanation.")
    affected_stages: list[str] = Field(default_factory=list, description="Later runtime stages that must be skipped.")
    report_stages: list[str] = Field(default_factory=list, description="Stages that must run even after block/termination.")


class EvaluationControl(UCTool):
    name: str = "EvaluationControl"
    description: str = (
        "Persist evaluation run/block/skip/termination state. Blocking or terminating an evaluation skips "
        "affected runtime stages while report stages remain runnable."
    )
    args_schema: type[BaseModel] = EvaluationControlArgs

    def _run(
        self,
        action: str,
        control_path: str = "evaluation/control.yaml",
        stage_name: str = "",
        reason_code: str = "",
        reason: str = "",
        affected_stages: list[str] | None = None,
        report_stages: list[str] | None = None,
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        try:
            result = evaluation_control_action(
                workspace,
                action,
                control_path,
                stage_name,
                reason_code,
                reason,
                affected_stages,
                report_stages,
            )
        except EvaluationControlError as exc:
            return f"EVAL-CONTROL-001: {exc}"
        except Exception as exc:
            return f"EVAL-CONTROL-002: unexpected control error: {type(exc).__name__}: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)


class IncrementalChangeDeployerArgs(BaseModel):
    workflow_root: str = Field(description="Generated workflow root relative to the outer workspace.")
    run_id: str = Field(description="Current id from tmp/inc_runs/current.json.")
    batch_id: str = Field(description="Stable approved repair batch id within this run.")
    attempt_id: str = Field(description="Unique attempt id within the batch, such as attempt-001.")
    change_id: str = Field(description="Stable applied-change id stored in eval/applied_changes.json.")
    approval_ids: list[str] = Field(description="Explicit approved ids from eval/approvals.json.")
    mappings: list[dict[str, Any]] = Field(
        description=(
            "Files to deploy. Every mapping requires source, target, approval_ids, and a concrete rationale tying "
            "that file to the approved finding or user entry. Sources must be below the exact "
            "tmp/inc_runs/<run_id>/batches/<batch_id>/attempts/<attempt_id>/candidate directory."
        )
    )
    manifest_path: str = Field(
        default="eval/applied_changes.json",
        description="Fixed deployment evidence document relative to workspace.",
    )


class IncrementalCandidateStagerArgs(BaseModel):
    workflow_root: str = Field(default="workflow", description="Generated workflow root relative to workspace.")
    run_id: str = Field(description="Active id from tmp/inc_runs/current.json.")
    batch_id: str = Field(description="Stable approved repair batch id within this run.")
    attempt_id: str = Field(description="Unique attempt id within the batch, such as attempt-001.")
    files: list[str] = Field(
        description="Canonical file paths relative to workflow_root to copy byte-for-byte into the candidate tree."
    )
    overwrite: bool = Field(
        default=False,
        description="Explicitly replace an existing candidate file; false accepts only an identical existing copy.",
    )


class IncrementalCandidateStager(UCTool):
    """Seed an isolated repair attempt from exact generated-workflow files."""

    name: str = "IncrementalCandidateStager"
    description: str = (
        "Safely copy selected regular files from the generated workflow into the active run, batch, and attempt "
        "candidate tree without changing formal files. Paths remain workflow-relative; directories, symlinks, "
        "path traversal, inactive runs, and implicit overwrites are rejected."
    )
    args_schema: type[BaseModel] = IncrementalCandidateStagerArgs

    def _run(
        self,
        run_id: str,
        batch_id: str,
        attempt_id: str,
        files: list[str],
        workflow_root: str = "workflow",
        overwrite: bool = False,
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        try:
            result = stage_incremental_candidates(
                workspace,
                workflow_root,
                run_id,
                batch_id,
                attempt_id,
                files,
                overwrite,
            )
        except IncrementalRunError as exc:
            return f"INC-STAGE-001: {exc}"
        except Exception as exc:
            return f"INC-STAGE-002: unexpected candidate staging error: {type(exc).__name__}: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)


class IncrementalChangeDeployer(UCTool):
    """Deploy approved temporary candidates and persist auditable JSON hash evidence."""

    name: str = "IncrementalChangeDeployer"
    description: str = (
        "Deploy explicitly approved run- and attempt-scoped candidate files into a generated workflow using safe "
        "relative paths. Every replacement archives the displaced bytes and appends version, approval, and SHA256 "
        "evidence to eval/applied_changes.json; prior deployment review state never blocks a repair attempt."
    )
    args_schema: type[BaseModel] = IncrementalChangeDeployerArgs

    def _run(
        self,
        workflow_root: str,
        run_id: str,
        batch_id: str,
        attempt_id: str,
        change_id: str,
        approval_ids: list[str],
        mappings: list[dict[str, Any]],
        manifest_path: str = "eval/applied_changes.json",
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        try:
            result = deploy_incremental_changes(
                workspace,
                workflow_root,
                mappings,
                approval_ids,
                change_id,
                manifest_path,
                run_id,
                batch_id,
                attempt_id,
            )
        except IncrementalDeploymentError as exc:
            return f"INC-DEPLOY-001: {exc}"
        except Exception as exc:
            return f"INC-DEPLOY-002: unexpected deployment error: {type(exc).__name__}: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)
