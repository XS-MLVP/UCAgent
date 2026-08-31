# -*- coding: utf-8 -*-
"""User-facing finding review, suggestion, and approval operations."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .json_store import (
    REPORT_NAMES,
    JsonStoreError,
    load_document,
    mutate_document,
    record_audit_event,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_fragment(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")
    return value[:80] or "item"


def _fingerprint(value: dict[str, Any]) -> str:
    explicit = value.get("fingerprint")
    if isinstance(explicit, str) and explicit:
        return explicit
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def review_items(workspace: Path) -> list[dict[str, Any]]:
    """Return current open findings and user suggestions with provenance."""
    items: list[dict[str, Any]] = []
    for report_type in REPORT_NAMES:
        document = load_document(workspace, f"eval/{report_type}_report.json")
        latest = document.get("latest_run_id", "")
        run = next((item for item in document["runs"] if item.get("run_id") == latest), None)
        if not run:
            continue
        for finding in run.get("findings", []):
            if finding.get("status", "open") in {"resolved", "accepted"}:
                continue
            items.append(
                {
                    "review_id": f"{report_type}/{finding.get('id')}",
                    "source_kind": "finding",
                    "source_report": report_type,
                    "source_run_id": latest,
                    "source_id": finding.get("id"),
                    "source_fingerprint": _fingerprint(finding),
                    "severity": finding.get("severity", "unknown"),
                    "title": finding.get("title", ""),
                    "description": finding.get("description", ""),
                    "evidence": finding.get("evidence", []),
                    "component": finding.get("component", ""),
                    "expected": finding.get("expected", ""),
                    "actual": finding.get("actual", ""),
                    "impact": finding.get("impact", ""),
                    "recommendation": finding.get("recommendation", ""),
                    "severity_reason": finding.get("severity_reason", ""),
                    "confidence": finding.get("confidence", ""),
                    "requirement_refs": finding.get("requirement_refs", []),
                    "repro": finding.get("repro", {}),
                    "status": finding.get("status", "open"),
                }
            )
    suggestions = load_document(workspace, "eval/user_suggestions.json")
    for suggestion in suggestions["items"]:
        if suggestion.get("status", "open") != "open":
            continue
        items.append(
            {
                "review_id": f"user/{suggestion.get('id')}",
                "source_kind": "suggestion",
                "source_report": "user",
                "source_run_id": "",
                "source_id": suggestion.get("id"),
                "source_fingerprint": _fingerprint(suggestion),
                "severity": suggestion.get("priority", "user"),
                "title": suggestion.get("title", ""),
                "description": suggestion.get("description", ""),
                "evidence": [],
                "priority": suggestion.get("priority", "medium"),
                "entry_kind": suggestion.get("entry_kind", "suggestion"),
                "status": suggestion.get("status", "open"),
                "created_at": suggestion.get("created_at", ""),
            }
        )
    return items


def find_review_item(workspace: Path, source_id: str) -> dict[str, Any]:
    candidates = review_items(workspace)
    qualified = [item for item in candidates if item.get("review_id") == source_id]
    if qualified:
        return qualified[0]
    matches = [item for item in candidates if item.get("source_id") == source_id]
    if not matches:
        raise JsonStoreError(f"open finding or suggestion not found: {source_id}")
    if len(matches) > 1:
        choices = ", ".join(str(item["review_id"]) for item in matches)
        raise JsonStoreError(
            f"source id is ambiguous across current reports: {source_id}; use one of {choices}"
        )
    return matches[0]


def decide_item(workspace: Path, source_id: str, decision: str, reason: str) -> dict[str, Any]:
    """Persist one provenance-bound user decision."""
    if decision not in {"approved", "rejected", "deferred"}:
        raise JsonStoreError("decision must be approved, rejected, or deferred")
    if not reason.strip():
        raise JsonStoreError("a non-empty decision reason is required")
    source = find_review_item(workspace, source_id)
    record_id = f"decision-{_safe_fragment(source['source_kind'])}-{_safe_fragment(source['review_id'])}"
    approvals = load_document(workspace, "eval/approvals.json")
    prior = next((item for item in approvals["items"] if item.get("id") == record_id), None)
    history = list(prior.get("history", [])) if prior else []
    if prior:
        history.append(
            {
                "decision": prior.get("decision"),
                "reason": prior.get("reason", ""),
                "decided_at": prior.get("decided_at", ""),
                "source_fingerprint": prior.get("source_fingerprint", ""),
            }
        )
    record = {
        "id": record_id,
        "decision": decision,
        **{key: source[key] for key in (
            "source_kind",
            "source_report",
            "source_run_id",
            "source_id",
            "source_fingerprint",
        )},
        "reason": reason.strip(),
        "decided_at": _now(),
        "history": history,
    }
    return mutate_document(workspace, "upsert", "eval/approvals.json", record=record)


def decide_items(
    workspace: Path,
    source_ids: list[str],
    decision: str,
    reason: str,
) -> list[dict[str, Any]]:
    """Persist one decision for a validated collection of current review items."""
    unique_ids = list(dict.fromkeys(source_ids))
    if not unique_ids:
        raise JsonStoreError("at least one review item is required")
    if len(unique_ids) > 200:
        raise JsonStoreError("a bulk decision is limited to 200 review items")
    if decision not in {"approved", "rejected", "deferred"}:
        raise JsonStoreError("decision must be approved, rejected, or deferred")
    if not reason.strip():
        raise JsonStoreError("a non-empty decision reason is required")
    for source_id in unique_ids:
        find_review_item(workspace, source_id)
    return [decide_item(workspace, source_id, decision, reason) for source_id in unique_ids]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repair_review_items(workspace: Path) -> list[dict[str, Any]]:
    """Return deployed versions with live integrity and recoverable history state."""
    workspace = workspace.resolve()
    document = load_document(workspace, "eval/applied_changes.json")
    entries = document.get("entries", [])
    latest_by_target: dict[tuple[str, str], str] = {}
    for entry in entries:
        root = str(entry.get("workflow_root", "workflow"))
        for change in entry.get("applied_changes", []):
            target = str(change.get("target", ""))
            if target:
                latest_by_target[(root, target)] = str(entry.get("id", ""))

    repairs: list[dict[str, Any]] = []
    for entry in reversed(entries):
        entry_id = str(entry.get("id", ""))
        root = str(entry.get("workflow_root", "workflow"))
        for change in entry.get("applied_changes", []):
            if change.get("console_deleted_at"):
                continue
            target = str(change.get("target", ""))
            expected_hash = str(change.get("sha256", ""))
            is_latest = latest_by_target.get((root, target)) == entry_id
            target_path = (workspace / root / target).resolve()
            allowed_root = (workspace / root).resolve()
            target_safe = target_path == allowed_root or allowed_root in target_path.parents
            actual_hash = _file_sha256(target_path) if target_safe and target_path.is_file() else ""
            if not is_latest:
                integrity = "superseded"
            elif not actual_hash:
                integrity = "missing"
            elif actual_hash != expected_hash:
                integrity = "drifted"
            else:
                integrity = "verified"
            stored_review = change.get("review") if isinstance(change.get("review"), dict) else None
            review_current = bool(stored_review and stored_review.get("sha256") == expected_hash)
            backup = change.get("backup") if isinstance(change.get("backup"), dict) else None
            backup_status = "none"
            backup_actual_hash = ""
            if backup and backup.get("existed"):
                if backup.get("deleted_at"):
                    backup_status = "deleted"
                else:
                    backup_path = (workspace / str(backup.get("path", ""))).resolve()
                    legacy_history = (workspace / "tmp" / "change_history").resolve()
                    run_history = (workspace / "tmp" / "inc_runs").resolve()
                    run_relative = (
                        backup_path.relative_to(run_history)
                        if run_history in backup_path.parents
                        else None
                    )
                    history_allowed = legacy_history in backup_path.parents or bool(
                        run_relative
                        and len(run_relative.parts) >= 3
                        and run_relative.parts[1] == "history"
                    )
                    if not history_allowed or not backup_path.is_file():
                        backup_status = "missing"
                    else:
                        backup_actual_hash = _file_sha256(backup_path)
                        backup_status = (
                            "available"
                            if backup_actual_hash == backup.get("sha256")
                            else "corrupt"
                        )
            repairs.append(
                {
                    "repair_id": f"{entry_id}::{target}",
                    "entry_id": entry_id,
                    "operation": entry.get("operation", "deploy"),
                    "run_id": entry.get("run_id", "legacy"),
                    "batch_id": entry.get("batch_id", ""),
                    "attempt_id": entry.get("attempt_id", ""),
                    "workflow_root": root,
                    "source": change.get("source", ""),
                    "target": target,
                    "sha256": expected_hash,
                    "actual_sha256": actual_hash,
                    "integrity": integrity,
                    "is_latest": is_latest,
                    "approval_ids": change.get("approval_ids", []),
                    "rationale": change.get("rationale", ""),
                    "applied_at": entry.get("applied_at", ""),
                    "legacy_review": stored_review if review_current else None,
                    "legacy_stale_review": stored_review if stored_review and not review_current else None,
                    "supersedes": change.get("supersedes"),
                    "backup": backup,
                    "backup_status": backup_status,
                    "backup_actual_sha256": backup_actual_hash,
                }
            )
    return repairs


def delete_repair_items(
    workspace: Path,
    repair_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    """Remove deployment records from the console without altering files or audit history."""
    unique_ids = list(dict.fromkeys(repair_ids))
    if not unique_ids:
        raise JsonStoreError("at least one deployment version record is required")
    if len(unique_ids) > 200:
        raise JsonStoreError("a bulk deletion is limited to 200 deployment version records")
    if not reason.strip():
        raise JsonStoreError("a deletion reason is required")

    available = {item["repair_id"]: item for item in repair_review_items(workspace)}
    missing = [repair_id for repair_id in unique_ids if repair_id not in available]
    if missing:
        raise JsonStoreError(f"deployment version record not found: {missing[0]}")

    document = load_document(workspace, "eval/applied_changes.json")
    updated_entries: dict[str, dict[str, Any]] = {}
    deleted_at = _now()
    for repair_id in unique_ids:
        repair = available[repair_id]
        entry_id = str(repair["entry_id"])
        updated = updated_entries.get(entry_id)
        if updated is None:
            source = next(item for item in document["entries"] if item.get("id") == entry_id)
            updated = json.loads(json.dumps(source))
            updated_entries[entry_id] = updated
        change = next(
            item for item in updated["applied_changes"]
            if item.get("target") == repair["target"]
        )
        change["console_deleted_at"] = deleted_at
        change["console_delete_reason"] = reason.strip()

    for entry_id, updated in updated_entries.items():
        mutate_document(
            workspace,
            "update",
            "eval/applied_changes.json",
            record=updated,
            record_id=entry_id,
        )
    for repair_id in unique_ids:
        repair = available[repair_id]
        record_audit_event(
            workspace,
            "delete_deployment_version_from_console",
            "eval/applied_changes.json",
            repair_id,
            {
                "target": repair["target"],
                "workflow_root": repair["workflow_root"],
                "reason": reason.strip(),
                "formal_files_changed": False,
                "backup_files_changed": False,
            },
        )
    return {
        "deleted": unique_ids,
        "deleted_at": deleted_at,
        "formal_files_changed": False,
        "backup_files_changed": False,
    }


def decide_repair(workspace: Path, repair_id: str, decision: str, reason: str) -> dict[str, Any]:
    """Record user acceptance of one exact deployed file hash."""
    if decision not in {"approved", "rejected", "deferred"}:
        raise JsonStoreError("repair decision must be approved, rejected, or deferred")
    if not reason.strip():
        raise JsonStoreError("a non-empty repair decision reason is required")
    matches = [item for item in repair_review_items(workspace) if item["repair_id"] == repair_id]
    if not matches:
        raise JsonStoreError(f"deployed repair not found: {repair_id}")
    repair = matches[0]
    if decision == "approved" and repair["integrity"] != "verified":
        raise JsonStoreError(
            f"only a current deployed file with matching SHA256 can be approved; integrity={repair['integrity']}"
        )

    document = load_document(workspace, "eval/applied_changes.json")
    entry = next(item for item in document["entries"] if item.get("id") == repair["entry_id"])
    updated = json.loads(json.dumps(entry))
    change = next(item for item in updated["applied_changes"] if item.get("target") == repair["target"])
    prior = change.get("review") if isinstance(change.get("review"), dict) else None
    history = list(prior.get("history", [])) if prior else []
    if prior:
        history.append(
            {
                "decision": prior.get("decision"),
                "reason": prior.get("reason", ""),
                "reviewed_at": prior.get("reviewed_at", ""),
                "sha256": prior.get("sha256", ""),
            }
        )
    change["review"] = {
        "decision": decision,
        "reason": reason.strip(),
        "reviewed_at": _now(),
        "sha256": repair["sha256"],
        "history": history,
    }
    return mutate_document(
        workspace,
        "upsert",
        "eval/applied_changes.json",
        record=updated,
        record_id=repair["entry_id"],
    )


def decide_repairs(
    workspace: Path,
    repair_ids: list[str],
    decision: str,
    reason: str,
) -> list[dict[str, Any]]:
    """Record one decision for a validated collection of deployed file repairs."""
    unique_ids = list(dict.fromkeys(repair_ids))
    if not unique_ids:
        raise JsonStoreError("at least one deployed repair is required")
    if len(unique_ids) > 200:
        raise JsonStoreError("a bulk repair decision is limited to 200 items")
    available = {item["repair_id"]: item for item in repair_review_items(workspace)}
    missing = [item for item in unique_ids if item not in available]
    if missing:
        raise JsonStoreError(f"deployed repair not found: {missing[0]}")
    if decision == "approved":
        invalid = [item for item in unique_ids if available[item]["integrity"] != "verified"]
        if invalid:
            raise JsonStoreError("bulk approval contains missing, drifted, or superseded repairs")
    return [decide_repair(workspace, repair_id, decision, reason) for repair_id in unique_ids]


def _delete_matching_approvals(workspace: Path, source: dict[str, Any]) -> int:
    approvals = load_document(workspace, "eval/approvals.json")
    matches = [
        item["id"]
        for item in approvals["items"]
        if item.get("source_kind") == source.get("source_kind")
        and item.get("source_report") == source.get("source_report")
        and item.get("source_run_id", "") == source.get("source_run_id", "")
        and item.get("source_id") == source.get("source_id")
    ]
    for record_id in matches:
        mutate_document(workspace, "delete", "eval/approvals.json", record_id=record_id)
    return len(matches)


def delete_review_items(workspace: Path, review_ids: list[str]) -> dict[str, Any]:
    """Physically delete selected review records without reverting deployed files."""
    unique_ids = list(dict.fromkeys(review_ids))
    if not unique_ids:
        raise JsonStoreError("at least one review item is required")
    if len(unique_ids) > 200:
        raise JsonStoreError("a bulk deletion is limited to 200 review items")

    review_sources = {item["review_id"]: item for item in review_items(workspace)}
    repairs = {item["repair_id"]: item for item in repair_review_items(workspace)}
    missing = [item for item in unique_ids if item not in review_sources and item not in repairs]
    if missing:
        raise JsonStoreError(f"review item not found: {missing[0]}")
    if any(item in repairs for item in unique_ids):
        raise JsonStoreError(
            "部署记录属于不可变审计历史；请在版本详情中恢复旧版本，或显式删除归档的旧版本文件"
        )

    deleted: list[dict[str, Any]] = []
    approvals_deleted = 0
    for review_id in unique_ids:
        source = review_sources[review_id]
        record_audit_event(
            workspace,
            "delete_review_item",
            (
                "eval/user_suggestions.json"
                if source["source_kind"] == "suggestion"
                else f"eval/{source['source_report']}_report.json"
            ),
            review_id,
            {
                "kind": source["source_kind"],
                "source_run_id": source.get("source_run_id", ""),
                "source_id": source["source_id"],
                "source_fingerprint": source.get("source_fingerprint", ""),
                "title": source.get("title", ""),
            },
        )
        approvals_deleted += _delete_matching_approvals(workspace, source)
        if source["source_kind"] == "suggestion":
            mutate_document(
                workspace,
                "delete",
                "eval/user_suggestions.json",
                record_id=source["source_id"],
            )
        else:
            relative = f"eval/{source['source_report']}_report.json"
            document = load_document(workspace, relative)
            run = next(
                item for item in document["runs"]
                if item.get("run_id") == source["source_run_id"]
            )
            updated = json.loads(json.dumps(run))
            updated["findings"] = [
                item for item in updated.get("findings", [])
                if item.get("id") != source["source_id"]
            ]
            mutate_document(
                workspace,
                "update",
                relative,
                record=updated,
                record_id=source["source_run_id"],
            )
        deleted.append({"id": review_id, "kind": source["source_kind"]})
    return {
        "deleted": deleted,
        "approvals_deleted": approvals_deleted,
        "formal_files_changed": False,
        "backups_deleted": False,
    }


def create_suggestion(
    workspace: Path,
    title: str,
    description: str,
    priority: str = "medium",
    entry_kind: str = "suggestion",
) -> dict[str, Any]:
    """Create a typed user review entry without requiring direct JSON edits."""
    if not title.strip() or not description.strip():
        raise JsonStoreError("user entry title and description are required")
    if priority not in {"critical", "high", "medium", "low"}:
        raise JsonStoreError("user entry priority must be critical, high, medium, or low")
    if entry_kind not in {"issue", "suggestion", "context"}:
        raise JsonStoreError("user entry kind must be issue, suggestion, or context")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    record = {
        "id": f"{entry_kind}-{timestamp}",
        "entry_kind": entry_kind,
        "title": title.strip(),
        "description": description.strip(),
        "priority": priority,
        "status": "open",
        "created_at": _now(),
    }
    return mutate_document(workspace, "create", "eval/user_suggestions.json", record=record)


def approval_is_current(workspace: Path, approval: dict[str, Any]) -> bool:
    """Return whether an approval still identifies the current source fingerprint."""
    required = {
        "source_kind",
        "source_report",
        "source_id",
        "source_fingerprint",
        "decided_at",
    }
    if approval.get("decision") != "approved" or not required.issubset(approval):
        return False
    try:
        report = str(approval.get("source_report", ""))
        prefix = "user" if approval.get("source_kind") == "suggestion" else report
        source = find_review_item(workspace, f"{prefix}/{approval['source_id']}")
    except JsonStoreError:
        return False
    return source["source_fingerprint"] == approval["source_fingerprint"]
