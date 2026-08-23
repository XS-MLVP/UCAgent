# -*- coding: utf-8 -*-
"""Deterministic deployment and verification for incremental workflow changes."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .json_store import JsonStoreError, load_document, mutate_document
from .approvals import approval_is_current
from .incremental_runs import (
    IncrementalRunError,
    current_incremental_run,
    incremental_attempt_paths,
    write_run_artifact,
)


class IncrementalDeploymentError(RuntimeError):
    """Raised when an incremental change cannot be deployed safely."""


SAFE_CHANGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
APPROVAL_PROVENANCE_FIELDS = (
    "id",
    "source_kind",
    "source_report",
    "source_run_id",
    "source_id",
    "source_fingerprint",
    "decided_at",
)


def _resolve_under(root: Path, path_text: str, label: str) -> Path:
    path = Path(path_text)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise IncrementalDeploymentError(f"{label} escapes allowed root: {path_text}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _approval_snapshot(approval: dict[str, Any]) -> dict[str, Any]:
    """Freeze the authorization facts used by one deployment."""
    snapshot = {field: approval.get(field, "") for field in APPROVAL_PROVENANCE_FIELDS}
    snapshot["decision"] = "approved"
    return snapshot


def _validate_candidate(path: Path, label: str) -> None:
    """Reject structurally invalid candidate source before any target is copied."""
    try:
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            yaml.safe_load(text)
        elif suffix == ".json":
            json.loads(text)
        elif suffix == ".py":
            ast.parse(text, filename=str(path))
    except (OSError, UnicodeError, ValueError, SyntaxError, yaml.YAMLError) as exc:
        raise IncrementalDeploymentError(f"{label} is not structurally valid: {exc}") from exc


def _audit_finding_key(finding: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(finding.get(field, ""))
        for field in ("rule_id", "severity", "path", "location", "message", "actual")
    )


def _validate_projected_semantics(
    workspace: Path,
    target_root: Path,
    validated_mappings: list[tuple[Path, Path, list[str], str]],
) -> None:
    """Reject newly introduced high-risk findings before replacing formal files."""
    from .static_audit import run_static_audit

    baseline = run_static_audit(
        workspace,
        target_root.relative_to(workspace).as_posix(),
    )
    baseline_keys = {
        _audit_finding_key(item)
        for item in baseline.get("findings", [])
        if item.get("severity") in {"critical", "high"}
    }
    temporary_root = workspace / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="incremental-projection-", dir=temporary_root) as directory:
        projected_root = Path(directory) / "workflow"
        shutil.copytree(target_root, projected_root, symlinks=True)
        mapped_targets = {
            target.relative_to(target_root).as_posix()
            for _, target, _, _ in validated_mappings
        }
        for source, target, _, _ in validated_mappings:
            projected_target = projected_root / target.relative_to(target_root)
            _atomic_copy(source, projected_target)
        projected = run_static_audit(
            workspace,
            projected_root.relative_to(workspace).as_posix(),
        )
        contract_files = {
            "config.yaml",
            "inc.yaml",
            "config/inc.yaml",
            ".workflow/workflow_spec.yaml",
        }
        contract_change = bool(mapped_targets & contract_files)
        introduced = []
        for finding in projected.get("findings", []):
            if finding.get("severity") not in {"critical", "high"}:
                continue
            if _audit_finding_key(finding) in baseline_keys:
                continue
            path = str(finding.get("path", ""))
            rule_id = str(finding.get("rule_id", ""))
            relevant = path in mapped_targets or (
                contract_change
                and path in contract_files
                and rule_id in {"FLOW-PLACEHOLDERS", "FLOW-CONFIG-SYNC"}
            )
            if relevant:
                introduced.append(finding)
        if introduced:
            summary = [
                {
                    "rule_id": item.get("rule_id"),
                    "path": item.get("path"),
                    "location": item.get("location"),
                    "actual": item.get("actual"),
                }
                for item in introduced[:20]
            ]
            raise IncrementalDeploymentError(
                "projected deployment introduces deterministic high-risk findings: "
                + json.dumps(summary, ensure_ascii=False, sort_keys=True)
            )


def _atomic_copy(source: Path, target: Path) -> None:
    """Replace a target without requiring its existing file mode to be writable."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.incremental-",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _archive_target(workspace: Path, history_root: Path, target_root: Path, target: Path) -> dict[str, Any]:
    """Save the exact pre-deployment target under protected incremental history."""
    relative_target = target.relative_to(target_root)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not target.is_file():
        return {"existed": False, "path": "", "sha256": "", "created_at": created_at}
    backup = history_root / "before" / relative_target
    _atomic_copy(target, backup)
    return {
        "existed": True,
        "path": backup.relative_to(workspace).as_posix(),
        "sha256": _sha256(backup),
        "created_at": created_at,
    }


def _rollback_targets(
    workspace: Path,
    target_root: Path,
    archived: list[tuple[Path, dict[str, Any]]],
) -> None:
    for target, backup in reversed(archived):
        if backup["existed"]:
            source = _resolve_under(workspace, str(backup["path"]), "rollback backup")
            _atomic_copy(source, target)
        else:
            target.unlink(missing_ok=True)


def deploy_incremental_changes(
    workspace: Path,
    workflow_root: str,
    mappings: list[dict[str, Any]],
    approval_ids: list[str],
    change_id: str,
    manifest_path: str = "eval/applied_changes.json",
    run_id: str = "",
    batch_id: str = "",
    attempt_id: str = "",
) -> dict[str, Any]:
    """Copy approved candidate files into a generated workflow and record hashes."""
    workspace = workspace.resolve()
    target_root = _resolve_under(workspace, workflow_root, "workflow_root")
    if not target_root.is_dir():
        raise IncrementalDeploymentError(f"generated workflow root does not exist: {target_root}")
    if not mappings:
        raise IncrementalDeploymentError("at least one source/target mapping is required")
    if manifest_path != "eval/applied_changes.json":
        raise IncrementalDeploymentError("manifest_path must be eval/applied_changes.json")
    if not SAFE_CHANGE_ID.fullmatch(change_id):
        raise IncrementalDeploymentError("change_id contains unsupported characters or is too long")
    try:
        run = current_incremental_run(workspace, run_id)
        paths = incremental_attempt_paths(
            workspace,
            run["run_id"],
            batch_id,
            attempt_id,
        )
    except IncrementalRunError as exc:
        raise IncrementalDeploymentError(str(exc)) from exc
    try:
        approvals = load_document(workspace, "eval/approvals.json")
        applied_document = load_document(workspace, manifest_path)
    except JsonStoreError as exc:
        raise IncrementalDeploymentError(str(exc)) from exc
    approved = {
        str(item["id"]): item
        for item in approvals["items"]
        if item.get("id") and approval_is_current(workspace, item)
    }
    if not approval_ids or any(item not in approved for item in approval_ids):
        raise IncrementalDeploymentError(
            "every deployment requires a current provenance-bound approval; legacy or stale approvals must be renewed"
        )
    if any(item.get("id") == change_id for item in applied_document.get("entries", [])):
        raise IncrementalDeploymentError(f"change_id already exists: {change_id}")
    history_root = (paths["history"] / change_id).resolve()
    if history_root.exists():
        raise IncrementalDeploymentError(f"history directory already exists for change_id: {change_id}")

    cited_by_mappings: set[str] = set()
    validated_mappings: list[
        tuple[Path, Path, list[str], str, dict[str, Any] | None]
    ] = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            raise IncrementalDeploymentError(f"mapping {index} must be an object")
        source_text = mapping.get("source", "")
        target_text = mapping.get("target", "")
        if not isinstance(source_text, str) or not source_text:
            raise IncrementalDeploymentError(f"mapping {index} requires a source path")
        if not isinstance(target_text, str) or not target_text:
            raise IncrementalDeploymentError(f"mapping {index} requires a target path")
        mapping_approval_ids = mapping.get("approval_ids", [])
        rationale = mapping.get("rationale", "")
        if (
            not isinstance(mapping_approval_ids, list)
            or not mapping_approval_ids
            or any(not isinstance(item, str) or item not in approved for item in mapping_approval_ids)
        ):
            raise IncrementalDeploymentError(
                f"mapping {index} requires current approved approval_ids"
            )
        if any(item not in approval_ids for item in mapping_approval_ids):
            raise IncrementalDeploymentError(
                f"mapping {index} cites an approval outside the deployment approval_ids"
            )
        if not isinstance(rationale, str) or len(rationale.strip()) < 20:
            raise IncrementalDeploymentError(
                f"mapping {index} requires a concrete rationale of at least 20 characters"
            )
        cited_by_mappings.update(mapping_approval_ids)
        target_parts = Path(target_text).parts
        if target_parts and target_parts[0] == target_root.name:
            raise IncrementalDeploymentError(
                f"mapping {index} target must be relative to workflow_root and must not start with "
                f"'{target_root.name}/': {target_text}"
            )
        source = _resolve_under(workspace, source_text, f"mapping {index} source")
        candidate_root = paths["candidate"].resolve()
        if candidate_root not in source.parents:
            raise IncrementalDeploymentError(
                f"mapping {index} source must be under the current attempt candidate directory "
                f"{candidate_root.relative_to(workspace).as_posix()}: {source_text}"
            )
        target = _resolve_under(target_root, target_text, f"mapping {index} target")
        canonical_target = target.relative_to(target_root).as_posix()
        prior_entry = None
        prior_change = None
        for prior_entry in reversed(applied_document.get("entries", [])):
            if prior_entry.get("workflow_root") != target_root.relative_to(workspace).as_posix():
                continue
            prior_change = next(
                (
                    item
                    for item in prior_entry.get("applied_changes", [])
                    if item.get("target") == canonical_target
                ),
                None,
            )
            if prior_change:
                break
        supersedes = None
        if prior_change:
            prior_operation = prior_entry.get("operation", "deploy") if prior_entry else "deploy"
            expected_hash = str(prior_change.get("sha256", ""))
            actual_hash = _sha256(target) if target.is_file() else ""
            supersedes = {
                "repair_id": f"{prior_entry.get('id')}::{canonical_target}",
                "sha256": expected_hash,
                "operation": prior_operation,
                "displaced_sha256": actual_hash,
                "drifted": bool(actual_hash and actual_hash != expected_hash),
            }
        if not source.is_file():
            raise IncrementalDeploymentError(f"mapping {index} source file does not exist: {source_text}")
        _validate_candidate(source, f"mapping {index} source")
        validated_mappings.append(
            (source, target, list(mapping_approval_ids), rationale.strip(), supersedes)
        )
    if cited_by_mappings != set(approval_ids):
        unused = sorted(set(approval_ids) - cited_by_mappings)
        raise IncrementalDeploymentError(
            f"every deployment approval must authorize at least one mapping; unused approvals: {unused}"
        )
    projected_mappings = [
        (source, target, mapping_ids, rationale)
        for source, target, mapping_ids, rationale, _ in validated_mappings
    ]
    _validate_projected_semantics(workspace, target_root, projected_mappings)

    applied: list[dict[str, Any]] = []
    archived: list[tuple[Path, dict[str, Any]]] = []
    receipt_path = ""
    try:
        for source, target, mapping_approval_ids, rationale, supersedes in validated_mappings:
            backup = _archive_target(workspace, history_root, target_root, target)
            archived.append((target, backup))
            _atomic_copy(source, target)
            digest = _sha256(target)
            change = {
                "source": source.relative_to(workspace).as_posix(),
                "target": target.relative_to(target_root).as_posix(),
                "sha256": digest,
                "approval_ids": mapping_approval_ids,
                "approval_provenance": [
                    _approval_snapshot(approved[item]) for item in mapping_approval_ids
                ],
                "rationale": rationale,
                "backup": backup,
            }
            if supersedes:
                change["supersedes"] = supersedes
            applied.append(change)

        payload: dict[str, Any] = {
            "id": change_id,
            "status": "applied",
            "operation": "deploy",
            "run_id": run["run_id"],
            "batch_id": batch_id,
            "attempt_id": attempt_id,
            "workflow_root": target_root.relative_to(workspace).as_posix(),
            "approval_ids": approval_ids,
            "approval_provenance": [
                _approval_snapshot(approved[item]) for item in approval_ids
            ],
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "applied_changes": applied,
        }
        receipt_path = write_run_artifact(
            workspace,
            run["run_id"],
            f"deployments/{change_id}.json",
            payload,
        )
        result = mutate_document(workspace, "upsert", manifest_path, record=payload, record_id=change_id)
    except (JsonStoreError, IncrementalRunError, OSError) as exc:
        try:
            _rollback_targets(workspace, target_root, archived)
        finally:
            shutil.rmtree(history_root, ignore_errors=True)
            if receipt_path:
                (workspace / receipt_path).unlink(missing_ok=True)
        raise IncrementalDeploymentError(f"deployment rolled back: {exc}") from exc
    return {"manifest_path": manifest_path, "receipt_path": receipt_path, **payload, "store": result}


def _history_path_is_allowed(workspace: Path, path: Path) -> bool:
    """Accept current run-scoped archives and legacy change_history archives."""
    legacy = (workspace / "tmp" / "change_history").resolve()
    if legacy in path.parents:
        return True
    runs = (workspace / "tmp" / "inc_runs").resolve()
    if runs not in path.parents:
        return False
    relative = path.relative_to(runs)
    return len(relative.parts) >= 3 and relative.parts[1] == "history"


def _find_recorded_change(
    document: dict[str, Any],
    repair_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entry_id, separator, target = repair_id.partition("::")
    if not separator or not entry_id or not target:
        raise IncrementalDeploymentError("repair_id must use <change_id>::<target>")
    entry = next((item for item in document.get("entries", []) if item.get("id") == entry_id), None)
    if not entry:
        raise IncrementalDeploymentError(f"deployment entry does not exist: {entry_id}")
    change = next((item for item in entry.get("applied_changes", []) if item.get("target") == target), None)
    if not change:
        raise IncrementalDeploymentError(f"deployment target does not exist in entry: {target}")
    return entry, change


def restore_incremental_backup(
    workspace: Path,
    repair_id: str,
    reason: str,
    manifest_path: str = "eval/applied_changes.json",
) -> dict[str, Any]:
    """Restore one archived pre-deployment version and retain the displaced current version."""
    if not reason.strip():
        raise IncrementalDeploymentError("restore reason is required")
    workspace = workspace.resolve()
    try:
        document = load_document(workspace, manifest_path)
    except JsonStoreError as exc:
        raise IncrementalDeploymentError(str(exc)) from exc
    entry, change = _find_recorded_change(document, repair_id)
    backup = change.get("backup")
    if not isinstance(backup, dict) or not backup.get("existed"):
        raise IncrementalDeploymentError("the selected deployment has no previous file version")
    if backup.get("deleted_at"):
        raise IncrementalDeploymentError("the selected historical file was deleted")
    backup_path = _resolve_under(workspace, str(backup.get("path", "")), "history backup")
    if not _history_path_is_allowed(workspace, backup_path) or not backup_path.is_file():
        raise IncrementalDeploymentError("historical file is missing or outside protected incremental history")
    if _sha256(backup_path) != backup.get("sha256"):
        raise IncrementalDeploymentError("historical file SHA256 does not match its record")
    _validate_candidate(backup_path, "history backup")

    target_root = _resolve_under(workspace, str(entry.get("workflow_root", "workflow")), "workflow_root")
    target = _resolve_under(target_root, str(change.get("target", "")), "restore target")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    restore_id = f"restore-{timestamp}"
    history_base = (workspace / "tmp" / "change_history").resolve()
    history_root = (history_base / restore_id).resolve()
    current_backup = _archive_target(workspace, history_root, target_root, target)
    approval_ids = list(change.get("approval_ids") or entry.get("approval_ids") or [])
    if not approval_ids:
        shutil.rmtree(history_root, ignore_errors=True)
        raise IncrementalDeploymentError("historical deployment has no approval provenance")
    authorization = {
        "action": "restore",
        "reason": reason.strip(),
        "authorized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_repair_id": repair_id,
        "source_sha256": backup["sha256"],
    }
    restored_change = {
        "source": backup["path"],
        "target": target.relative_to(target_root).as_posix(),
        "sha256": backup["sha256"],
        "approval_ids": approval_ids,
        "rationale": f"User-authorized restoration of archived version: {reason.strip()}",
        "backup": current_backup,
    }
    payload = {
        "id": restore_id,
        "status": "applied",
        "operation": "restore",
        "workflow_root": target_root.relative_to(workspace).as_posix(),
        "approval_ids": approval_ids,
        "applied_at": authorization["authorized_at"],
        "user_authorization": authorization,
        "applied_changes": [restored_change],
    }
    try:
        _atomic_copy(backup_path, target)
        result = mutate_document(
            workspace,
            "create",
            manifest_path,
            record=payload,
            record_id=restore_id,
        )
    except (JsonStoreError, OSError) as exc:
        try:
            _rollback_targets(workspace, target_root, [(target, current_backup)])
        finally:
            shutil.rmtree(history_root, ignore_errors=True)
        raise IncrementalDeploymentError(f"restore rolled back: {exc}") from exc
    return {"manifest_path": manifest_path, **payload, "store": result}


def delete_incremental_backup(
    workspace: Path,
    repair_id: str,
    reason: str,
    manifest_path: str = "eval/applied_changes.json",
) -> dict[str, Any]:
    """Delete one archived file while preserving its hash and deletion audit metadata."""
    if not reason.strip():
        raise IncrementalDeploymentError("history deletion reason is required")
    workspace = workspace.resolve()
    try:
        document = load_document(workspace, manifest_path)
    except JsonStoreError as exc:
        raise IncrementalDeploymentError(str(exc)) from exc
    entry, change = _find_recorded_change(document, repair_id)
    backup = change.get("backup")
    if not isinstance(backup, dict) or not backup.get("existed"):
        raise IncrementalDeploymentError("the selected deployment has no previous file version")
    if backup.get("deleted_at"):
        raise IncrementalDeploymentError("the selected historical file was already deleted")
    backup_path = _resolve_under(workspace, str(backup.get("path", "")), "history backup")
    if not _history_path_is_allowed(workspace, backup_path) or not backup_path.is_file():
        raise IncrementalDeploymentError("historical file is missing or outside protected incremental history")
    if _sha256(backup_path) != backup.get("sha256"):
        raise IncrementalDeploymentError("historical file SHA256 does not match its record")

    updated = json.loads(json.dumps(entry))
    updated_change = next(
        item for item in updated["applied_changes"] if item.get("target") == change.get("target")
    )
    deleted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated_change["backup"]["deleted_at"] = deleted_at
    updated_change["backup"]["delete_reason"] = reason.strip()
    quarantine = backup_path.with_name(f".{backup_path.name}.deleting-{os.getpid()}")
    try:
        os.replace(backup_path, quarantine)
        result = mutate_document(
            workspace,
            "update",
            manifest_path,
            record=updated,
            record_id=str(entry["id"]),
        )
    except (JsonStoreError, OSError) as exc:
        if quarantine.exists():
            os.replace(quarantine, backup_path)
        raise IncrementalDeploymentError(f"history deletion failed: {exc}") from exc
    quarantine.unlink(missing_ok=True)
    return {
        "manifest_path": manifest_path,
        "repair_id": repair_id,
        "deleted_path": backup["path"],
        "deleted_at": deleted_at,
        "store": result,
    }


def verify_incremental_application(
    workspace: Path,
    workflow_root: str,
    manifest_path: str = "eval/applied_changes.json",
) -> tuple[bool, dict[str, Any]]:
    """Verify every staged change was copied into the generated workflow."""
    workspace = workspace.resolve()
    target_root = _resolve_under(workspace, workflow_root, "workflow_root")
    try:
        manifest = load_document(workspace, manifest_path)
    except JsonStoreError as exc:
        return False, {"error": str(exc), "manifest_path": manifest_path}
    entries = manifest.get("entries", [])
    if not entries:
        return False, {"error": "applied change manifest contains no entries", "manifest_path": manifest_path}
    latest_changes: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for change in entry.get("applied_changes", []):
            if isinstance(change, dict) and change.get("target"):
                latest_changes[str(change["target"])] = change
    changes = list(latest_changes.values())
    if not isinstance(changes, list) or not changes:
        return False, {"error": "applied change manifest contains no changes", "manifest_path": manifest_path}

    failures: list[dict[str, str]] = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            failures.append({"index": str(index), "error": "change is not an object"})
            continue
        try:
            source = _resolve_under(workspace, str(change.get("source", "")), "source")
            target = _resolve_under(target_root, str(change.get("target", "")), "target")
        except IncrementalDeploymentError as exc:
            failures.append({"index": str(index), "error": str(exc)})
            continue
        if not target.is_file():
            failures.append({"target": str(change.get("target", "")), "error": "deployed target is missing"})
            continue
        target_hash = _sha256(target)
        expected = str(change.get("sha256", ""))
        source_hash = _sha256(source) if source.is_file() else ""
        if target_hash != expected or (source_hash and source_hash != target_hash):
            failures.append(
                {
                    "target": target.relative_to(target_root).as_posix(),
                    "error": "deployed target does not match staged source or recorded hash",
                }
            )
    if failures:
        return False, {"error": "incremental changes were not fully applied", "failures": failures}
    return True, {
        "message": "incremental changes are applied to generated workflow",
        "manifest_path": manifest_path,
        "applied_count": len(changes),
        "historical_entry_count": len(entries),
    }
