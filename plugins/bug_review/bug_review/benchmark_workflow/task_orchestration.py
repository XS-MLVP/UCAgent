"""Local, resumable orchestration for persisted benchmark tasks.

The first implementation intentionally executes only replay tasks because a
replay contract already is a complete frozen input.  Saved semantic outputs do
not contain the original candidate/prompt snapshot, so those tasks are audited
but never replayed from incomplete evidence.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
from typing import Dict, Iterator, Mapping, Optional, Sequence, Tuple
import uuid

from .pipeline import merge_benchmark_replay_results
from .replay_execution import run_benchmark_replay_execution
from .task_manifest import (
    REPLAY_SUCCESS_STATUSES,
    atomic_write_json,
    benchmark_snapshot_hash,
    build_task_manifest,
    materialize_task_workspace,
    stable_hash,
    refresh_manifest_revision,
)
from .durable_task_store import TaskLeaseLost, default_worker_id
from .task_resources import (
    append_attempt_observation,
    build_attempt_observation,
    replay_resource_profile,
)
from .task_dependencies import dependency_issues, summarize_task_readiness, task_readiness
from .task_heartbeat import LeaseHeartbeat
from .semantic_task_store import SemanticTaskStore
from .failure_mode_task_store import FailureModeTaskStore
from .rtl_root_appeal_task_store import RtlRootAppealTaskStore
from .reported_root_alignment_task_store import ReportedRootAlignmentTaskStore


_DURABLE_STORES = {
    "semantic_judgement": SemanticTaskStore,
    "failure_mode_review": FailureModeTaskStore,
    "rtl_root_appeal": RtlRootAppealTaskStore,
    "reported_root_alignment": ReportedRootAlignmentTaskStore,
}


def load_json(path: Path) -> Dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def prepare_task_workspace(benchmark_path: Path, workspace: Path) -> Dict[str, object]:
    payload = load_json(benchmark_path)
    prior_path = workspace / "task_manifest.json"
    prior = load_json(prior_path) if prior_path.exists() else None
    manifest = build_task_manifest(
        payload,
        benchmark_path=str(benchmark_path.resolve()),
        prior_manifest=prior,
    )
    return materialize_task_workspace(payload, manifest, workspace)


def _manifest_path(workspace: Path) -> Path:
    return workspace / "task_manifest.json"


@contextmanager
def _manifest_lock(workspace: Path) -> Iterator[None]:
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / "task_manifest.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _manifest_task(manifest: Mapping[str, object], task_id: str) -> Dict[str, object]:
    for task in manifest.get("tasks", []) or []:
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return task
    raise ValueError(f"task not present in manifest: {task_id}")


def _claim_manifest_task(
    workspace: Path,
    task_id: str,
    *,
    lease_seconds: int = 900,
    worker_id: str = "",
    resource_profile: Optional[Mapping[str, object]] = None,
) -> Optional[str]:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    with _manifest_lock(workspace):
        manifest_path = _manifest_path(workspace)
        manifest = load_json(manifest_path)
        task = _manifest_task(manifest, task_id)
        tasks = [row for row in manifest.get("tasks", []) or [] if isinstance(row, dict)]
        readiness = task_readiness(task, tasks)
        if not readiness["ready"]:
            return None
        status = str(task.get("status") or "pending")
        if status not in {"pending", "retryable_failed", "running"}:
            return None
        current = datetime.now(timezone.utc)
        lease = task.get("lease") if isinstance(task.get("lease"), dict) else {}
        expires = _parse_time(lease.get("expires_at"))
        if lease and expires is not None and expires > current:
            return None
        recovered = bool(lease) or status == "running"
        token = uuid.uuid4().hex
        task.update({
            "status": "running",
            "attempts": int(task.get("attempts", 0) or 0) + 1,
            "lease_recoveries": int(task.get("lease_recoveries", 0) or 0) + (1 if recovered else 0),
            "last_error": "",
            "updated_at": current.isoformat(),
            "lease": {
                "worker_id": worker_id or default_worker_id(),
                "token": token,
                "acquired_at": current.isoformat(),
                "renewed_at": current.isoformat(),
                "expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
            },
        })
        if resource_profile:
            task["resource_profile"] = dict(resource_profile)
        atomic_write_json(manifest_path, manifest)
        return token


def _claim_next_ready_replay_task(
    workspace: Path,
    *,
    excluded_task_ids: Sequence[str] = (),
    lease_seconds: int = 900,
    worker_id: str = "",
    resource_profile: Optional[Mapping[str, object]] = None,
) -> Optional[Tuple[str, str, Dict[str, object]]]:
    """Atomically select and claim one dependency-ready replay task."""
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    excluded = set(excluded_task_ids)
    with _manifest_lock(workspace):
        manifest_path = _manifest_path(workspace)
        manifest = load_json(manifest_path)
        tasks = [row for row in manifest.get("tasks", []) or [] if isinstance(row, dict)]
        issues = dependency_issues(tasks)
        candidates = [
            task for task in tasks
            if task.get("task_type") == "replay"
            and str(task.get("task_id") or "") not in excluded
            and task_readiness(task, tasks, issues=issues)["ready"]
        ]
        if not candidates:
            return None
        task = min(candidates, key=lambda row: str(row.get("task_id") or ""))
        task_id = str(task.get("task_id") or "")
        current = datetime.now(timezone.utc)
        lease = task.get("lease") if isinstance(task.get("lease"), dict) else {}
        recovered = bool(lease) or task.get("status") == "running"
        token = uuid.uuid4().hex
        task.update({
            "status": "running",
            "attempts": int(task.get("attempts", 0) or 0) + 1,
            "lease_recoveries": int(task.get("lease_recoveries", 0) or 0) + (1 if recovered else 0),
            "last_error": "",
            "updated_at": current.isoformat(),
            "lease": {
                "worker_id": worker_id or default_worker_id(),
                "token": token,
                "acquired_at": current.isoformat(),
                "renewed_at": current.isoformat(),
                "expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
            },
        })
        if resource_profile:
            task["resource_profile"] = dict(resource_profile)
        atomic_write_json(manifest_path, manifest)
        return task_id, token, copy.deepcopy(task)


def _checkpoint_manifest_task(
    workspace: Path,
    task_id: str,
    lease_token: str,
    updates: Mapping[str, object],
    *,
    output_path: Optional[Path] = None,
    output: Optional[Mapping[str, object]] = None,
    error: Optional[BaseException] = None,
) -> Dict[str, object]:
    with _manifest_lock(workspace):
        manifest_path = _manifest_path(workspace)
        manifest = load_json(manifest_path)
        task = _manifest_task(manifest, task_id)
        lease = task.get("lease") if isinstance(task.get("lease"), dict) else {}
        expires = _parse_time(lease.get("expires_at"))
        if lease.get("token") != lease_token:
            raise TaskLeaseLost(f"replay task lease no longer owns {task_id}")
        if expires is None or expires <= datetime.now(timezone.utc):
            raise TaskLeaseLost(f"replay task lease expired before checkpoint: {task_id}")
        if output_path is not None and output is not None:
            atomic_write_json(output_path, output)
        outcome = str(updates.get("status") or "checkpoint")
        task["attempt_history"] = append_attempt_observation(
            task,
            build_attempt_observation(lease, outcome, error=error),
        )
        task.update(dict(updates))
        task.pop("lease", None)
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(manifest_path, manifest)
        return manifest


def _renew_manifest_task(
    workspace: Path,
    task_id: str,
    lease_token: str,
    *,
    lease_seconds: int,
) -> None:
    current = datetime.now(timezone.utc)
    with _manifest_lock(workspace):
        manifest_path = _manifest_path(workspace)
        manifest = load_json(manifest_path)
        task = _manifest_task(manifest, task_id)
        lease = task.get("lease") if isinstance(task.get("lease"), dict) else {}
        expires = _parse_time(lease.get("expires_at"))
        if lease.get("token") != lease_token or expires is None or expires <= current:
            raise TaskLeaseLost(f"replay task lease no longer owns {task_id}")
        task["lease"] = {
            **lease,
            "renewed_at": current.isoformat(),
            "expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
        }
        task["updated_at"] = current.isoformat()
        atomic_write_json(manifest_path, manifest)


def _task_input(workspace: Path, task: Mapping[str, object]) -> Dict[str, object]:
    input_ref = str(task.get("input_ref") or "")
    if not input_ref:
        raise ValueError(f"task {task.get('task_id')} has no persisted input_ref")
    payload = load_json(workspace / input_ref)
    contract = payload.get("replay_runner_contract")
    if not isinstance(contract, dict):
        raise ValueError(f"task {task.get('task_id')} input has no replay_runner_contract")
    if stable_hash(contract) != task.get("input_hash"):
        raise ValueError(f"task {task.get('task_id')} input hash changed")
    return contract


def run_one_ready_replay_task(
    workspace: Path,
    *,
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
    execution_mode: str = "auto",
    target_arch: str = "auto",
    qemu_binary: str = "",
    target_python: str = "",
    sysroot: str = "",
    path: Optional[Sequence[str]] = None,
    ld_library_path: Optional[Sequence[str]] = None,
    pythonpath: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
    task_lease_seconds: int = 900,
    resource_pool_limit: int = 1,
    worker_id: str = "",
    excluded_task_ids: Sequence[str] = (),
    heartbeat_interval_seconds: Optional[float] = None,
) -> Dict[str, object]:
    """Claim, execute, and checkpoint at most one frozen replay task."""
    manifest_path = _manifest_path(workspace)
    manifest = load_json(manifest_path)
    if manifest.get("schema") != "benchmark_task_manifest.v1":
        raise ValueError(f"unsupported or missing task manifest: {manifest_path}")
    resource_profile = replay_resource_profile(
        execution_mode=execution_mode,
        target_arch=target_arch,
        runtime_root=runtime_root,
        runtime_profile=runtime_profile,
        qemu_binary=qemu_binary,
        target_python=target_python,
        sysroot=sysroot,
    )

    claimed = _claim_next_ready_replay_task(
        workspace,
        excluded_task_ids=excluded_task_ids,
        lease_seconds=task_lease_seconds,
        worker_id=worker_id,
        resource_profile=resource_profile,
    )
    if claimed is None:
        current = load_json(manifest_path)
        tasks = [row for row in current.get("tasks", []) or [] if isinstance(row, dict)]
        return {
            "claimed": False,
            "task_id": "",
            "task_status": "",
            "readiness": summarize_task_readiness(tasks),
            "manifest": current,
        }
    task_id, lease_token, task = claimed
    final_status = "retryable_failed"
    interval = heartbeat_interval_seconds
    if interval is None:
        interval = max(1.0, min(30.0, task_lease_seconds / 3.0))
    heartbeat = LeaseHeartbeat(
        lambda: _renew_manifest_task(
            workspace, task_id, lease_token, lease_seconds=task_lease_seconds,
        ),
        interval_seconds=interval,
    ).start()
    try:
        contract = _task_input(workspace, task)
        task_dir = workspace / "tasks" / str(task["task_id"])
        execution_dir = task_dir / "execution"
        execution_dir.mkdir(parents=True, exist_ok=True)
        contract_path = execution_dir / "replay_runner_contracts.json"
        atomic_write_json(contract_path, {"replay_runner_contracts": [contract]})
        result_payload = run_benchmark_replay_execution(
            contracts=[contract],
            contracts_path=str(contract_path),
            output_dir=str(execution_dir),
            runtime_root=runtime_root,
            runtime_profile=runtime_profile,
            execution_mode=execution_mode,
            target_arch=target_arch,
            qemu_binary=qemu_binary,
            target_python=target_python,
            sysroot=sysroot,
            path=path,
            ld_library_path=ld_library_path,
            pythonpath=pythonpath,
            extra_env=extra_env,
            resource_pool_limit=resource_pool_limit,
        )
        rows = [row for row in result_payload.get("results", []) or [] if isinstance(row, dict)]
        if len(rows) != 1 or not isinstance(rows[0].get("result"), dict):
            raise RuntimeError("replay executor did not return exactly one candidate result")
        row = rows[0]
        result = row["result"]
        output_path = task_dir / "output.json"
        output_ref = output_path.relative_to(workspace).as_posix()
        result_status = str(result.get("status") or "")
        if result_status in REPLAY_SUCCESS_STATUSES:
            final_status = "succeeded"
            last_error = ""
        else:
            final_status = "retryable_failed"
            last_error = str(result.get("reason") or result_status or "incomplete replay")
        heartbeat.stop()
        heartbeat.ensure_owned()
        _checkpoint_manifest_task(
            workspace,
            task_id,
            lease_token,
            {
                "output_ref": output_ref,
                "output_hash": stable_hash(result),
                "result_status": result_status,
                "status": final_status,
                "last_error": last_error,
            },
            output_path=output_path,
            output=row,
            error=(RuntimeError(last_error) if final_status != "succeeded" else None),
        )
    except Exception as exc:
        heartbeat.stop()
        if not isinstance(exc, TaskLeaseLost):
            try:
                heartbeat.ensure_owned()
                _checkpoint_manifest_task(
                    workspace,
                    task_id,
                    lease_token,
                    {
                        "status": "retryable_failed",
                        "last_error": f"{type(exc).__name__}: {exc}",
                    },
                    error=exc,
                )
            except TaskLeaseLost:
                pass
    current = load_json(manifest_path)
    current_task = _manifest_task(current, task_id)
    return {
        "claimed": True,
        "task_id": task_id,
        "task_status": str(current_task.get("status") or final_status),
        "readiness": summarize_task_readiness(
            [row for row in current.get("tasks", []) or [] if isinstance(row, dict)]
        ),
        "manifest": current,
    }


def run_pending_replay_tasks(
    workspace: Path,
    **kwargs: object,
) -> Dict[str, object]:
    """Compatibility batch runner: execute each initially known replay task once."""
    manifest_path = _manifest_path(workspace)
    manifest = load_json(manifest_path)
    replay_task_ids = {
        str(task.get("task_id") or "")
        for task in manifest.get("tasks", []) or []
        if isinstance(task, dict) and task.get("task_type") == "replay"
    }
    attempted = set()
    while replay_task_ids - attempted:
        outcome = run_one_ready_replay_task(
            workspace,
            excluded_task_ids=tuple(attempted),
            **kwargs,
        )
        if not outcome["claimed"]:
            break
        attempted.add(str(outcome["task_id"]))
    return load_json(manifest_path)


def replay_results_from_workspace(workspace: Path, manifest: Mapping[str, object]) -> Dict[str, object]:
    results = []
    status_counts: Dict[str, int] = {}
    for task in manifest.get("tasks", []) or []:
        if not isinstance(task, dict) or task.get("task_type") != "replay":
            continue
        output_ref = str(task.get("output_ref") or "")
        if not output_ref or not (workspace / output_ref).exists():
            continue
        row = load_json(workspace / output_ref)
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        candidate_id = str(row.get("candidate_id") or task.get("candidate_id") or "")
        results.append({"candidate_id": candidate_id, "result": result})
        status = str(result.get("status") or "")
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "results": results,
        "summary": {
            "input_contract_count": sum(
                isinstance(task, dict) and task.get("task_type") == "replay"
                for task in manifest.get("tasks", []) or []
            ),
            "result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
        },
    }


def merge_and_finalize_workspace(
    benchmark_path: Path,
    workspace: Path,
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    """Merge completed task outputs and derive a fresh provisional/final revision."""
    payload = load_json(benchmark_path)
    manifest = load_json(_manifest_path(workspace))
    expected_hash = str(
        manifest.get("prepared_source_snapshot_hash")
        or manifest.get("source_snapshot_hash")
        or ""
    )
    actual_hash = benchmark_snapshot_hash(payload)
    if expected_hash != actual_hash:
        raise ValueError(
            "benchmark input changed after prepare; prepare a new task revision "
            f"(expected {expected_hash}, got {actual_hash})"
        )
    replay_results = replay_results_from_workspace(workspace, manifest)
    merged = copy.deepcopy(payload)
    if replay_results["results"]:
        # An empty explicit config prevents this local merge command from
        # starting a targeted semantic LLM refresh as a hidden side effect.
        merged = merge_benchmark_replay_results(
            merged,
            replay_results,
            semantic_llm_config={},
        )
    refreshed = build_task_manifest(
        merged,
        benchmark_path=str(benchmark_path.resolve()),
        prior_manifest=manifest,
    )
    # The revision describes the merged snapshot, while this separate hash
    # remains the immutable source accepted by repeated/idempotent finalize.
    refreshed["prepared_source_snapshot_hash"] = expected_hash
    merged["benchmark_revision"] = copy.deepcopy(refreshed["revision"])
    materialize_task_workspace(merged, refreshed, workspace)
    atomic_write_json(workspace / "replay_results.json", replay_results)
    return merged, refreshed, replay_results


def sync_task_manifest_from_sidecars(
    workspace: Path, *, dry_run: bool = False,
) -> Dict[str, object]:
    """Repair derived manifest task states without executing or preparing work."""
    workspace = Path(workspace)
    with _manifest_lock(workspace):
        manifest_path = _manifest_path(workspace)
        manifest = load_json(manifest_path)
        if manifest.get("schema") != "benchmark_task_manifest.v1":
            raise ValueError(f"unsupported or missing task manifest: {manifest_path}")
        before_hash = stable_hash(manifest)
        changes = []
        for task in manifest.get("tasks", []) or []:
            if not isinstance(task, dict) or not task.get("task_id"):
                continue
            task_id = str(task["task_id"])
            task_type = str(task.get("task_type") or "")
            prior_status = str(task.get("status") or "pending")
            updates: Dict[str, object] = {}
            store_class = _DURABLE_STORES.get(task_type)
            store_dir = str(task.get("task_store_dir") or "")
            if store_class is not None and store_dir:
                task_dir = Path(store_dir) / "tasks" / task_id
                task_input = load_json(task_dir / "input.json") if (task_dir / "input.json").is_file() else {}
                state = load_json(task_dir / "state.json") if (task_dir / "state.json").is_file() else {}
                if task_input.get("task_id") != task_id or state.get("task_id") != task_id:
                    updates = {
                        "status": "permanently_failed",
                        "last_error": "authoritative durable sidecar identity mismatch",
                        "sidecar_integrity": "invalid",
                    }
                else:
                    sidecar_status = str(state.get("status") or "pending")
                    reusable = False
                    if sidecar_status == "succeeded":
                        reusable = store_class(Path(store_dir)).load_success(task_input) is not None
                    if sidecar_status == "succeeded" and not reusable:
                        updates = {
                            "status": "permanently_failed",
                            "last_error": "authoritative durable output failed schema/hash validation",
                            "sidecar_integrity": "invalid",
                        }
                    elif sidecar_status in {
                        "pending", "running", "succeeded", "retryable_failed",
                        "permanently_failed", "cancelled", "superseded",
                    }:
                        updates = {
                            "status": sidecar_status,
                            "attempts": int(state.get("attempts", 0) or 0),
                            "last_error": str(state.get("last_error") or ""),
                            "output_hash": str(state.get("output_hash") or ""),
                            "sidecar_integrity": "valid",
                        }
                        if isinstance(state.get("lease"), dict):
                            updates["lease"] = copy.deepcopy(state["lease"])
                        else:
                            task.pop("lease", None)
                    else:
                        updates = {
                            "status": "permanently_failed",
                            "last_error": f"unsupported authoritative durable status: {sidecar_status}",
                            "sidecar_integrity": "invalid",
                        }
            elif task_type == "replay":
                output_ref = str(task.get("output_ref") or "")
                output_path = workspace / output_ref if output_ref else None
                if output_path is not None and output_path.is_file():
                    row = load_json(output_path)
                    result = row.get("result") if isinstance(row.get("result"), dict) else None
                    valid = bool(
                        result is not None
                        and str(row.get("candidate_id") or "") == str(task.get("candidate_id") or "")
                    )
                    result_status = str((result or {}).get("status") or "")
                    if valid and result_status in REPLAY_SUCCESS_STATUSES:
                        updates = {
                            "status": "succeeded",
                            "output_hash": stable_hash(result),
                            "result_status": result_status,
                            "last_error": "", "sidecar_integrity": "valid",
                        }
                    elif valid:
                        updates = {
                            "status": "retryable_failed",
                            "output_hash": stable_hash(result),
                            "result_status": result_status,
                            "last_error": str(result.get("reason") or result_status),
                            "sidecar_integrity": "valid",
                        }
                    elif prior_status == "succeeded":
                        updates = {
                            "status": "retryable_failed",
                            "last_error": "authoritative replay output failed identity/schema validation",
                            "sidecar_integrity": "invalid",
                        }
                elif prior_status == "succeeded":
                    updates = {
                        "status": "retryable_failed",
                        "last_error": "authoritative replay output is missing",
                        "sidecar_integrity": "invalid",
                    }
            if not updates:
                continue
            task.update(updates)
            if prior_status != task.get("status") or updates.get("sidecar_integrity") == "invalid":
                changes.append({
                    "task_id": task_id, "task_type": task_type,
                    "before_status": prior_status, "after_status": task.get("status"),
                    "sidecar_integrity": task.get("sidecar_integrity", "unknown"),
                })
        refreshed = refresh_manifest_revision(manifest)
        after_hash = stable_hash(refreshed)
        audit = {
            "schema": "benchmark_manifest_sidecar_sync.v1",
            "workspace": str(workspace.resolve()), "dry_run": dry_run,
            "before_hash": before_hash, "after_hash": after_hash,
            "changed_task_count": len(changes), "changes": changes,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if not dry_run:
            atomic_write_json(manifest_path, refreshed)
            atomic_write_json(workspace / "manifest_sync_audit.json", audit)
        return {"manifest": refreshed, "audit": audit}
