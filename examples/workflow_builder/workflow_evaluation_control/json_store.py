# -*- coding: utf-8 -*-
"""Validated JSON state store shared by evaluation and incremental workflows."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
REPORT_NAMES = ("tools", "checkers", "flow", "env", "run")
REPORT_FILES = {f"eval/{name}_report.json" for name in REPORT_NAMES}
EVAL_FILES = REPORT_FILES | {
    "eval/summary.json",
    "eval/user_suggestions.json",
    "eval/approvals.json",
    "eval/applied_changes.json",
    "eval/incremental_report.json",
    "eval/audit.json",
    "eval/run_request.json",
}
RESOURCE_FILES = {f"res/{name}.json" for name in ("common", *REPORT_NAMES)}
ALLOWED_FILES = EVAL_FILES | RESOURCE_FILES
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class JsonStoreError(RuntimeError):
    """Raised when a structured state operation violates the store contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _base_document(relative: str) -> dict[str, Any]:
    common: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "revision": 0}
    if relative in REPORT_FILES:
        return {**common, "report_type": Path(relative).stem.removesuffix("_report"), "latest_run_id": "", "runs": []}
    if relative == "eval/summary.json":
        return {**common, "generated_at": "", "reports": {}, "open_findings": [], "totals": {}}
    if relative == "eval/user_suggestions.json":
        return {**common, "items": []}
    if relative == "eval/approvals.json":
        return {**common, "items": []}
    if relative == "eval/applied_changes.json":
        return {**common, "entries": []}
    if relative == "eval/incremental_report.json":
        return {**common, "latest_run_id": "", "runs": []}
    if relative == "eval/audit.json":
        return {**common, "events": []}
    if relative == "eval/run_request.json":
        return {
            **common,
            "mode": "default",
            "target": "example",
            "workflow_root": "workflow",
            "stall_timeout_seconds": 300,
            "max_runtime_seconds": 1800,
        }
    if relative in RESOURCE_FILES:
        return {**common, "notes": [], "requirements": [], "references": []}
    raise JsonStoreError(f"unsupported JSON document: {relative}")


def _resolve(workspace: Path, relative: str) -> Path:
    if relative not in ALLOWED_FILES:
        raise JsonStoreError(f"document is not allowlisted: {relative}")
    root = workspace.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise JsonStoreError(f"document escapes workspace: {relative}")
    if path.is_symlink():
        raise JsonStoreError(f"symbolic links are not allowed: {relative}")
    return path


def _validate_id(value: Any, label: str = "id") -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise JsonStoreError(f"{label} must match {SAFE_ID.pattern}")
    return value


def validate_document(relative: str, value: Any) -> dict[str, Any]:
    """Validate the stable envelope and the document-specific collection."""
    if not isinstance(value, dict):
        raise JsonStoreError(f"{relative} root must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise JsonStoreError(f"{relative} schema_version must be {SCHEMA_VERSION}")
    revision = value.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise JsonStoreError(f"{relative} revision must be a non-negative integer")
    if relative in REPORT_FILES or relative == "eval/incremental_report.json":
        if not isinstance(value.get("runs"), list):
            raise JsonStoreError(f"{relative} runs must be an array")
        seen: set[str] = set()
        for run in value["runs"]:
            if not isinstance(run, dict):
                raise JsonStoreError(f"{relative} every run must be an object")
            run_id = _validate_id(run.get("run_id"), "run_id")
            if run_id in seen:
                raise JsonStoreError(f"{relative} contains duplicate run_id: {run_id}")
            seen.add(run_id)
            if run.get("status") not in {
                "passed",
                "passed_with_findings",
                "failed",
                "blocked",
                "skipped",
                "running",
                "no_change",
            }:
                raise JsonStoreError(f"{relative} run {run_id} has invalid status")
            for key in ("checks", "findings"):
                if key in run and not isinstance(run[key], list):
                    raise JsonStoreError(f"{relative} run {run_id} {key} must be an array")
            if not run.get("started_at"):
                raise JsonStoreError(f"{relative} run {run_id} must include started_at")
            if run.get("status") != "running":
                if not run.get("finished_at"):
                    raise JsonStoreError(f"{relative} terminal run {run_id} must include finished_at")
                if not run.get("checks"):
                    raise JsonStoreError(f"{relative} terminal run {run_id} must include at least one check")
            for check in run.get("checks", []):
                if not isinstance(check, dict) or not check.get("id") or check.get("status") not in {
                    "passed",
                    "failed",
                    "blocked",
                    "skipped",
                }:
                    raise JsonStoreError(
                        f"{relative} run {run_id} checks require id and passed/failed/blocked/skipped status"
                    )
                if "evidence" not in check:
                    raise JsonStoreError(f"{relative} run {run_id} check {check.get('id')} lacks evidence")
            finding_fields = {
                "id",
                "fingerprint",
                "severity",
                "category",
                "component",
                "title",
                "description",
                "evidence",
                "impact",
                "recommendation",
                "repro",
                "status",
            }
            if run.get("contract_version", 1) >= 2:
                finding_fields |= {
                    "expected",
                    "actual",
                    "severity_reason",
                    "confidence",
                    "requirement_refs",
                }
            for finding in run.get("findings", []):
                missing = finding_fields - set(finding) if isinstance(finding, dict) else finding_fields
                if missing:
                    raise JsonStoreError(
                        f"{relative} run {run_id} finding lacks fields: {', '.join(sorted(missing))}"
                    )
        latest = value.get("latest_run_id", "")
        if latest and latest not in seen:
            raise JsonStoreError(f"{relative} latest_run_id does not identify a stored run")
    elif relative in {"eval/user_suggestions.json", "eval/approvals.json"}:
        if not isinstance(value.get("items"), list):
            raise JsonStoreError(f"{relative} items must be an array")
        seen = set()
        for item in value["items"]:
            if not isinstance(item, dict):
                raise JsonStoreError(f"{relative} every item must be an object")
            item_id = _validate_id(item.get("id"))
            if item_id in seen:
                raise JsonStoreError(f"{relative} contains duplicate id: {item_id}")
            seen.add(item_id)
            if relative == "eval/user_suggestions.json":
                if not item.get("title") or not item.get("description"):
                    raise JsonStoreError(f"{relative} item {item_id} requires title and description")
                if item.get("entry_kind", "suggestion") not in {"issue", "suggestion", "context"}:
                    raise JsonStoreError(f"{relative} item {item_id} has invalid entry_kind")
                if item.get("status", "open") not in {"open", "withdrawn", "addressed"}:
                    raise JsonStoreError(f"{relative} item {item_id} has invalid status")
            elif item.get("decision") not in {"approved", "rejected", "deferred"}:
                raise JsonStoreError(
                    f"{relative} item {item_id} decision must be approved, rejected, or deferred"
                )
    elif relative == "eval/applied_changes.json":
        if not isinstance(value.get("entries"), list):
            raise JsonStoreError(f"{relative} entries must be an array")
        seen = set()
        for entry in value["entries"]:
            if not isinstance(entry, dict):
                raise JsonStoreError(f"{relative} every entry must be an object")
            entry_id = _validate_id(entry.get("id"))
            if entry_id in seen:
                raise JsonStoreError(f"{relative} contains duplicate id: {entry_id}")
            seen.add(entry_id)
            if entry.get("status") != "applied":
                raise JsonStoreError(f"{relative} entry {entry.get('id')} status must be applied")
            if not isinstance(entry.get("approval_ids"), list) or not entry["approval_ids"]:
                raise JsonStoreError(f"{relative} entry {entry.get('id')} requires approval_ids")
            approval_provenance = entry.get("approval_provenance")
            if approval_provenance is not None:
                if not isinstance(approval_provenance, list):
                    raise JsonStoreError(
                        f"{relative} entry {entry_id} approval_provenance must be an array"
                    )
                provenance_ids = set()
                for snapshot in approval_provenance:
                    if (
                        not isinstance(snapshot, dict)
                        or snapshot.get("decision") != "approved"
                        or not snapshot.get("id")
                        or not snapshot.get("source_kind")
                        or not snapshot.get("source_report")
                        or not snapshot.get("source_id")
                        or not snapshot.get("source_fingerprint")
                        or not snapshot.get("decided_at")
                        or "source_run_id" not in snapshot
                    ):
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} has incomplete approval provenance"
                        )
                    provenance_ids.add(snapshot["id"])
                if (
                    len(provenance_ids) != len(approval_provenance)
                    or provenance_ids != set(entry["approval_ids"])
                ):
                    raise JsonStoreError(
                        f"{relative} entry {entry_id} approval provenance does not match approval_ids"
                    )
            if not isinstance(entry.get("applied_changes"), list) or not entry["applied_changes"]:
                raise JsonStoreError(f"{relative} entry {entry.get('id')} requires applied_changes")
            operation = entry.get("operation", "deploy")
            if operation not in {"deploy", "restore"}:
                raise JsonStoreError(f"{relative} entry {entry_id} has invalid operation")
            for field in ("run_id", "batch_id", "attempt_id"):
                if field in entry:
                    _validate_id(entry.get(field), field)
            if operation == "restore":
                authorization = entry.get("user_authorization")
                if (
                    not isinstance(authorization, dict)
                    or authorization.get("action") != "restore"
                    or not authorization.get("reason")
                    or not authorization.get("authorized_at")
                    or not authorization.get("source_repair_id")
                ):
                    raise JsonStoreError(
                        f"{relative} restore entry {entry_id} requires user_authorization"
                    )
            targets: set[str] = set()
            for change in entry["applied_changes"]:
                if not isinstance(change, dict):
                    raise JsonStoreError(f"{relative} entry {entry_id} contains a non-object change")
                target = change.get("target")
                if not isinstance(target, str) or not target:
                    raise JsonStoreError(f"{relative} entry {entry_id} change requires target")
                if target in targets:
                    raise JsonStoreError(f"{relative} entry {entry_id} contains duplicate target: {target}")
                targets.add(target)
                if not isinstance(change.get("sha256"), str) or len(change["sha256"]) != 64:
                    raise JsonStoreError(f"{relative} entry {entry_id} change {target} requires SHA256")
                change_provenance = change.get("approval_provenance")
                if change_provenance is not None:
                    if not isinstance(change_provenance, list):
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} approval_provenance must be an array"
                        )
                    change_provenance_ids = {
                        snapshot.get("id")
                        for snapshot in change_provenance
                        if isinstance(snapshot, dict)
                        and snapshot.get("decision") == "approved"
                        and snapshot.get("source_kind")
                        and snapshot.get("source_report")
                        and snapshot.get("source_id")
                        and snapshot.get("source_fingerprint")
                        and snapshot.get("decided_at")
                        and "source_run_id" in snapshot
                    }
                    if (
                        len(change_provenance_ids) != len(change_provenance)
                        or change_provenance_ids != set(change.get("approval_ids", []))
                    ):
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} has invalid approval provenance"
                        )
                supersedes = change.get("supersedes")
                if supersedes is not None and (
                    not isinstance(supersedes, dict)
                    or not supersedes.get("repair_id")
                    or not isinstance(supersedes.get("sha256"), str)
                    or len(supersedes["sha256"]) != 64
                    or supersedes.get("operation") not in {"deploy", "restore"}
                ):
                    raise JsonStoreError(
                        f"{relative} entry {entry_id} change {target} has invalid supersedes record"
                    )
                backup = change.get("backup")
                if backup is not None:
                    if not isinstance(backup, dict) or not isinstance(backup.get("existed"), bool):
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} has invalid backup"
                        )
                    if backup["existed"]:
                        if (
                            not isinstance(backup.get("path"), str)
                            or not (
                                backup["path"].startswith("tmp/change_history/")
                                or (
                                    backup["path"].startswith("tmp/inc_runs/")
                                    and "/history/" in backup["path"]
                                )
                            )
                            or not isinstance(backup.get("sha256"), str)
                            or len(backup["sha256"]) != 64
                            or not backup.get("created_at")
                        ):
                            raise JsonStoreError(
                                f"{relative} entry {entry_id} change {target} has incomplete backup"
                            )
                        if backup.get("deleted_at") and not backup.get("delete_reason"):
                            raise JsonStoreError(
                                f"{relative} entry {entry_id} change {target} deleted backup lacks reason"
                            )
                review = change.get("review")
                if review is not None:
                    if not isinstance(review, dict) or review.get("decision") not in {
                        "approved",
                        "rejected",
                        "deferred",
                    }:
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} has invalid review decision"
                        )
                    if not review.get("reason") or not review.get("reviewed_at"):
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} review requires reason and reviewed_at"
                        )
                    if review.get("sha256") != change["sha256"]:
                        raise JsonStoreError(
                            f"{relative} entry {entry_id} change {target} review SHA256 must match deployment"
                        )
    elif relative == "eval/audit.json":
        if not isinstance(value.get("events"), list):
            raise JsonStoreError(f"{relative} events must be an array")
    elif relative == "eval/run_request.json":
        if value.get("mode") not in {"default", "inc"}:
            raise JsonStoreError("eval/run_request.json mode must be default or inc")
        if not isinstance(value.get("workflow_root"), str) or not value["workflow_root"]:
            raise JsonStoreError("eval/run_request.json workflow_root must be non-empty")
        if not isinstance(value.get("target"), str) or not value["target"]:
            raise JsonStoreError("eval/run_request.json target must be non-empty")
    elif relative in RESOURCE_FILES:
        for key in ("notes", "requirements", "references"):
            if not isinstance(value.get(key), list):
                raise JsonStoreError(f"{relative} {key} must be an array")
    return value


def load_document(workspace: Path, relative: str) -> dict[str, Any]:
    path = _resolve(workspace, relative)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise JsonStoreError(f"document does not exist: {relative}") from exc
    except json.JSONDecodeError as exc:
        raise JsonStoreError(f"malformed JSON in {relative}: line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    return validate_document(relative, value)


def _atomic_write(workspace: Path, relative: str, value: dict[str, Any]) -> None:
    path = _resolve(workspace, relative)
    tmp_root = (workspace.resolve() / "tmp" / "json_store").resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    old_mode = path.stat().st_mode if path.exists() else None
    parent_mode = path.parent.stat().st_mode
    path.parent.chmod(parent_mode | stat.S_IWUSR | stat.S_IXUSR)
    if old_mode is not None:
        path.chmod(old_mode | stat.S_IWUSR)
    fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".json", dir=tmp_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
        path.parent.chmod(parent_mode)
    if relative.startswith("eval/") and relative != "eval/user_suggestions.json":
        path.chmod(path.stat().st_mode & ~stat.S_IWGRP & ~stat.S_IWOTH)


def initialize_workspace(workspace: Path) -> dict[str, Any]:
    """Create missing state files without replacing user or historical data."""
    workspace = workspace.resolve()
    (workspace / "eval").mkdir(parents=True, exist_ok=True)
    (workspace / "res").mkdir(parents=True, exist_ok=True)
    (workspace / "tmp").mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    validated: list[str] = []
    for relative in sorted(ALLOWED_FILES):
        path = _resolve(workspace, relative)
        if path.exists():
            load_document(workspace, relative)
            validated.append(relative)
        else:
            value = _base_document(relative)
            _atomic_write(workspace, relative, value)
            created.append(relative)
    return {"created": created, "validated": validated}


def validate_workspace(workspace: Path) -> dict[str, Any]:
    validated = [relative for relative in sorted(ALLOWED_FILES) if load_document(workspace, relative)]
    return {"valid": True, "documents": validated}


def document_record_template(relative: str) -> dict[str, Any]:
    """Return a minimal valid record plus optional nested templates for one document."""
    if relative in REPORT_FILES or relative == "eval/incremental_report.json":
        report_type = (
            Path(relative).stem.removesuffix("_report")
            if relative in REPORT_FILES
            else "incremental"
        )
        return {
            "action": "create",
            "document": relative,
            "record": {
                "run_id": f"{report_type}-YYYYMMDD-HHMMSS",
                "contract_version": 2,
                "status": "passed",
                "started_at": "YYYY-MM-DDTHH:MM:SS+00:00",
                "finished_at": "YYYY-MM-DDTHH:MM:SS+00:00",
                "target": {"workflow_root": "workflow", "revision": "sha256-or-version"},
                "checks": [
                    {
                        "id": "check-1",
                        "status": "passed",
                        "summary": "What was checked and the observed result.",
                        "evidence": [
                            {
                                "kind": "source",
                                "path": "relative/path",
                                "location": "line or YAML field",
                                "observation": "Exact observed fact",
                            }
                        ],
                    }
                ],
                "findings": [],
                "metrics": {},
            },
            "finding_template": {
                "id": "finding-stable-id",
                "fingerprint": "stable-content-fingerprint",
                "severity": "high",
                "category": "contract",
                "component": "relative/path/or/component",
                "title": "Concise problem title",
                "description": "Observed defect and expected behavior.",
                "expected": "The contractually required behavior.",
                "actual": "The observed behavior.",
                "severity_reason": "Why the impact maps to this severity.",
                "confidence": "confirmed",
                "requirement_refs": ["guide section, user requirement, or rule id"],
                "evidence": [
                    {
                        "kind": "source",
                        "path": "relative/path",
                        "location": "line or YAML field",
                        "observation": "Exact observed fact",
                    }
                ],
                "impact": "Why this matters.",
                "recommendation": "Bounded remediation.",
                "repro": ["deterministic reproduction step"],
                "status": "open",
            },
            "note": "Pass only the record object to create/upsert; never pass the whole JSON document.",
        }
    if relative == "eval/user_suggestions.json":
        return {
            "action": "create",
            "document": relative,
            "record": {
                "id": "suggestion-stable-id",
                "entry_kind": "suggestion",
                "title": "Suggestion title",
                "description": "Concrete requested change and rationale.",
                "status": "open",
            },
        }
    if relative == "eval/approvals.json":
        return {
            "action": "create",
            "document": relative,
            "record": {
                "id": "approval-stable-id",
                "decision": "approved",
                "source_kind": "finding",
                "source_report": "flow",
                "source_run_id": "flow-YYYYMMDD-HHMMSS",
                "source_id": "finding-or-suggestion-id",
                "reason": "Explicit user approval rationale.",
                "source_fingerprint": "stable source fingerprint",
                "decided_at": "YYYY-MM-DDTHH:MM:SS+00:00",
            },
        }
    if relative == "eval/applied_changes.json":
        return {
            "note": "This document is written by IncrementalChangeDeployer; do not create entries directly."
        }
    raise JsonStoreError(f"{relative} does not expose a record template")


def _collection_name(relative: str) -> str:
    if relative in REPORT_FILES or relative == "eval/incremental_report.json":
        return "runs"
    if relative in {"eval/user_suggestions.json", "eval/approvals.json"}:
        return "items"
    if relative == "eval/applied_changes.json":
        return "entries"
    if relative == "eval/audit.json":
        return "events"
    raise JsonStoreError(f"{relative} does not expose CRUD records")


def _record_id(relative: str, record: dict[str, Any]) -> str:
    key = "run_id" if _collection_name(relative) == "runs" else "id"
    return _validate_id(record.get(key), key)


def _audit(workspace: Path, action: str, relative: str, record_id: str = "") -> None:
    if relative == "eval/audit.json":
        return
    audit = load_document(workspace, "eval/audit.json")
    audit["events"].append(
        {"time": utc_now(), "action": action, "document": relative, "record_id": record_id}
    )
    audit["revision"] += 1
    _atomic_write(workspace, "eval/audit.json", audit)


def record_audit_event(
    workspace: Path,
    action: str,
    relative: str,
    record_id: str,
    details: dict[str, Any],
) -> None:
    """Append structured context for a user action that spans nested records."""
    audit = load_document(workspace, "eval/audit.json")
    audit["events"].append({
        "time": utc_now(),
        "action": action,
        "document": relative,
        "record_id": record_id,
        "details": copy.deepcopy(details),
    })
    audit["revision"] += 1
    _atomic_write(workspace, "eval/audit.json", audit)


def mutate_document(
    workspace: Path,
    action: str,
    relative: str,
    record: dict[str, Any] | None = None,
    record_id: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Perform record CRUD with optimistic revision checks and atomic persistence."""
    document = load_document(workspace, relative)
    if expected_revision is not None and document["revision"] != expected_revision:
        raise JsonStoreError(
            f"revision conflict for {relative}: expected {expected_revision}, actual {document['revision']}"
        )
    collection_name = _collection_name(relative)
    collection = document[collection_name]
    if action == "list":
        return {"revision": document["revision"], "records": copy.deepcopy(collection)}
    if action == "get":
        wanted = _validate_id(record_id)
        for item in collection:
            if _record_id(relative, item) == wanted:
                return {"revision": document["revision"], "record": copy.deepcopy(item)}
        raise JsonStoreError(f"record not found: {wanted}")
    if action not in {"create", "update", "delete", "upsert"}:
        raise JsonStoreError(f"unsupported CRUD action: {action}")
    wanted = _validate_id(record_id or _record_id(relative, record or {}))
    index = next((i for i, item in enumerate(collection) if _record_id(relative, item) == wanted), None)
    if action == "create" and index is not None:
        raise JsonStoreError(f"record already exists: {wanted}")
    if action in {"update", "delete"} and index is None:
        raise JsonStoreError(f"record not found: {wanted}")
    if action == "delete":
        collection.pop(index)
    else:
        if not isinstance(record, dict):
            raise JsonStoreError(f"{action} requires a record object")
        normalized = copy.deepcopy(record)
        key = "run_id" if collection_name == "runs" else "id"
        normalized[key] = wanted
        if index is None:
            collection.append(normalized)
        else:
            collection[index] = normalized
        if collection_name == "runs":
            document["latest_run_id"] = wanted
    document["revision"] += 1
    validate_document(relative, document)
    _atomic_write(workspace, relative, document)
    _audit(workspace, action, relative, wanted)
    if relative == "eval/incremental_report.json" and os.environ.get("UCAGENT_INC_RUN_ID"):
        try:
            from .incremental_runs import write_run_artifact

            write_run_artifact(
                workspace,
                os.environ["UCAGENT_INC_RUN_ID"],
                "reports/incremental_report.json",
                document,
            )
        except (OSError, RuntimeError) as exc:
            raise JsonStoreError(f"cannot snapshot incremental report into its run directory: {exc}") from exc
    return {"document": relative, "revision": document["revision"], "record_id": wanted}


def update_run_request(
    workspace: Path,
    mode: str,
    workflow_root: str,
    target: str,
    stall_timeout_seconds: int = 300,
    max_runtime_seconds: int = 1800,
) -> dict[str, Any]:
    if mode not in {"default", "inc"}:
        raise JsonStoreError("mode must be default or inc")
    if not 30 <= stall_timeout_seconds <= 3600:
        raise JsonStoreError("stall_timeout_seconds must be between 30 and 3600")
    if not stall_timeout_seconds <= max_runtime_seconds <= 14400:
        raise JsonStoreError("max_runtime_seconds must be at least the stall timeout and at most 14400")
    document = load_document(workspace, "eval/run_request.json")
    document.update(
        mode=mode,
        workflow_root=workflow_root,
        target=target,
        stall_timeout_seconds=stall_timeout_seconds,
        max_runtime_seconds=max_runtime_seconds,
        revision=document["revision"] + 1,
    )
    validate_document("eval/run_request.json", document)
    _atomic_write(workspace, "eval/run_request.json", document)
    _audit(workspace, "update", "eval/run_request.json", mode)
    return document


def aggregate_summary(workspace: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    open_findings: list[dict[str, Any]] = []
    totals = {
        "reports": 0,
        "passed": 0,
        "passed_with_findings": 0,
        "failed": 0,
        "blocked": 0,
        "open_findings": 0,
    }
    for name in REPORT_NAMES:
        relative = f"eval/{name}_report.json"
        document = load_document(workspace, relative)
        latest = document.get("latest_run_id", "")
        run = next((item for item in document["runs"] if item.get("run_id") == latest), None)
        reports[name] = {"latest_run_id": latest, "status": run.get("status") if run else "not_run"}
        totals["reports"] += int(run is not None)
        if run:
            status = run.get("status")
            if status in totals:
                totals[status] += 1
            else:
                totals["failed"] += 1
            for finding in run.get("findings", []):
                if (
                    isinstance(finding, dict)
                    and finding.get("status", "open") not in {"resolved", "accepted"}
                    and finding.get("severity") != "info"
                ):
                    open_findings.append({"report": name, **finding})
    totals["open_findings"] = len(open_findings)
    summary = load_document(workspace, "eval/summary.json")
    summary.update(
        generated_at=utc_now(),
        reports=reports,
        open_findings=open_findings,
        totals=totals,
        revision=summary["revision"] + 1,
    )
    _atomic_write(workspace, "eval/summary.json", summary)
    _audit(workspace, "aggregate", "eval/summary.json")
    return summary
