"""Independent one-shot worker for durable LLM task stores."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import random
import time
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from .durable_task_store import TaskLeaseLost, default_worker_id
from .failure_mode_task_store import FailureModeTaskStore, SCHEMA as FAILURE_MODE_SCHEMA
from .llm_runtime import build_semantic_llm_client
from .llm_task_execution import EXECUTORS
from .reported_root_alignment_task_store import (
    ReportedRootAlignmentTaskStore,
    SCHEMA as REPORTED_ROOT_SCHEMA,
)
from .rtl_root_appeal_task_store import RtlRootAppealTaskStore, SCHEMA as RTL_APPEAL_SCHEMA
from .semantic_task_store import SemanticTaskStore, SCHEMA as SEMANTIC_SCHEMA
from .task_dependencies import dependency_issues, summarize_task_readiness, task_readiness
from .task_finalization import finalize_if_ready, task_batch_completion
from .task_heartbeat import LeaseHeartbeat
from .task_manifest import atomic_write_json, stable_hash
from .task_resources import classify_task_error


StoreSpec = Tuple[str, Path]
_STORE_TYPES = {
    "semantic_judgement": (SemanticTaskStore, SEMANTIC_SCHEMA),
    "failure_mode_review": (FailureModeTaskStore, FAILURE_MODE_SCHEMA),
    "rtl_root_appeal": (RtlRootAppealTaskStore, RTL_APPEAL_SCHEMA),
    "reported_root_alignment": (ReportedRootAlignmentTaskStore, REPORTED_ROOT_SCHEMA),
}
_RUNTIME_IDENTITY_FIELDS = (
    "provider", "backend", "model", "base_url",
    "request_timeout_seconds", "sdk_max_retries",
)


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _scan_tasks(
    store_specs: Sequence[StoreSpec],
    *,
    revision_scope_id: str = "",
    dut: str = "",
) -> Sequence[Dict[str, object]]:
    rows = []
    seen = set()
    for task_type, root in store_specs:
        if task_type not in _STORE_TYPES:
            raise ValueError(f"unsupported LLM task store type: {task_type}")
        _store_class, expected_schema = _STORE_TYPES[task_type]
        for input_path in sorted((Path(root) / "tasks").glob("*/input.json")):
            task_input = _read_json(input_path)
            state = _read_json(input_path.parent / "state.json")
            if revision_scope_id and str(task_input.get("revision_scope_id") or "") != revision_scope_id:
                continue
            if dut and str(task_input.get("dut") or "") != dut:
                continue
            task_id = str(task_input.get("task_id") or "")
            if not task_id or task_id in seen:
                raise ValueError(f"duplicate or missing durable TaskID: {task_id!r}")
            seen.add(task_id)
            if task_input.get("schema") != expected_schema:
                raise ValueError(
                    f"task {task_id} schema {task_input.get('schema')!r} does not match {expected_schema!r}"
                )
            rows.append({
                "task_id": task_id,
                "task_type": task_type,
                "status": str(state.get("status") or "pending"),
                "attempts": int(state.get("attempts", 0) or 0),
                "lease": copy.deepcopy(state.get("lease")),
                "resumable": True,
                "depends_on": copy.deepcopy(task_input.get("depends_on", [])),
                "required_for_finalize": task_input.get("required_for_finalize", True),
                "input_snapshot_hash": str(task_input.get("input_snapshot_hash") or ""),
                "task_input": task_input,
                "store_root": str(Path(root)),
            })
    return rows


def _hydrate_runtime(
    task_input: Mapping[str, object], runtime_config: Mapping[str, object],
) -> Dict[str, object]:
    frozen = task_input.get("runtime")
    if not isinstance(frozen, dict):
        raise ValueError(f"task {task_input.get('task_id')} has no frozen runtime identity")
    selected = dict(runtime_config)
    conflicts = []
    for field in ("provider", "backend", "model", "base_url"):
        frozen_value = frozen.get(field)
        selected_value = selected.get(field)
        if frozen_value not in {None, ""} and selected_value not in {None, ""}:
            if str(frozen_value) != str(selected_value):
                conflicts.append(f"{field}: frozen={frozen_value!r}, selected={selected_value!r}")
    if conflicts:
        raise ValueError("selected LLM profile does not match frozen task runtime: " + "; ".join(conflicts))
    merged = dict(selected)
    for field in _RUNTIME_IDENTITY_FIELDS:
        if frozen.get(field) not in {None, ""}:
            merged[field] = frozen[field]
    if not merged.get("model") or not merged.get("provider"):
        raise ValueError("frozen LLM task runtime is missing provider/model")
    return merged


def _store_for(task: Mapping[str, object]):
    store_class, _schema = _STORE_TYPES[str(task["task_type"])]
    return store_class(Path(str(task["store_root"])))


def finalize_llm_task_batch(
    store_specs: Sequence[StoreSpec],
    output_root: Path,
    *,
    revision_scope_id: str = "",
    dut: str = "",
) -> Dict[str, object]:
    """Atomically aggregate a completed LLM batch for synchronous consumers."""
    tasks = list(_scan_tasks(
        store_specs, revision_scope_id=revision_scope_id, dut=dut,
    ))
    completion = task_batch_completion(tasks)
    if not completion["all_required_succeeded"]:
        raise ValueError("cannot finalize an incomplete required LLM task batch")
    outputs = []
    for task in sorted(tasks, key=lambda row: str(row.get("task_id") or "")):
        if task.get("required_for_finalize") is False:
            continue
        task_dir = Path(str(task["store_root"])) / "tasks" / str(task["task_id"])
        state = _read_json(task_dir / "state.json")
        output = _read_json(task_dir / "output.json")
        if state.get("status") != "succeeded" or state.get("output_hash") != stable_hash(output):
            raise ValueError(f"task output integrity check failed: {task['task_id']}")
        outputs.append({
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "input_snapshot_hash": task.get("input_snapshot_hash", ""),
            "output_hash": state.get("output_hash", ""),
            "output": output,
        })
    payload = {
        "schema": "benchmark_finalized_llm_task_batch.v1",
        "batch_fingerprint": completion["batch_fingerprint"],
        "revision_scope_id": revision_scope_id,
        "dut": dut,
        "task_count": len(outputs),
        "tasks": outputs,
    }
    output_path = Path(output_root) / "finalized_task_outputs.json"
    atomic_write_json(output_path, payload)
    return {
        "output_path": str(output_path.resolve()),
        "task_count": len(outputs),
        "output_hash": stable_hash(payload),
        "batch_fingerprint": completion["batch_fingerprint"],
    }


def _persist_success(
    store: object,
    task: Mapping[str, object],
    output: Mapping[str, object],
    lease_token: str,
) -> None:
    task_input = task["task_input"]
    task_type = str(task["task_type"])
    store_dir = str(task["store_root"])
    ownership = {
        "durable_task_id": task_input["task_id"],
        "task_store_dir": store_dir,
        "revision_scope_id": task_input.get("revision_scope_id", ""),
        "task_source_snapshot_hash": task_input.get("source_snapshot_hash", ""),
    }
    if task_type == "semantic_judgement":
        row = copy.deepcopy(output["semantic_judgement"])
        row.update(ownership)
        appeal = copy.deepcopy(output.get("semantic_appeal"))
        store.save_success(task_input, row, appeal, lease_token=lease_token)
    elif task_type == "failure_mode_review":
        review = copy.deepcopy(output["failure_mode_review"])
        review.update(ownership)
        store.save_success(task_input, review, lease_token=lease_token)
    elif task_type == "rtl_root_appeal":
        review = copy.deepcopy(output["rtl_root_appeal_review"])
        review.update(ownership)
        store.save_success(task_input, review, lease_token=lease_token)
    elif task_type == "reported_root_alignment":
        decision = copy.deepcopy(output["alignment_decision"])
        decision.update(ownership)
        decision["benchmark_revision_id"] = task_input.get("revision_id", "")
        if decision.get("schema_valid") is not True:
            raise ValueError("reported-root alignment response failed schema/citation validation")
        store.save_success(task_input, decision, lease_token=lease_token)
    else:
        raise ValueError(f"no persistence adapter for {task_type}")


def run_one_ready_llm_task(
    store_specs: Sequence[StoreSpec],
    runtime_config: Mapping[str, object],
    *,
    client_factory: Callable[[Mapping[str, object]], object] = build_semantic_llm_client,
    worker_id: str = "",
    lease_seconds: int = 900,
    heartbeat_interval_seconds: Optional[float] = None,
    max_attempts: int = 3,
    finalization_root: Optional[Path] = None,
    finalizer: Optional[Callable[[], Mapping[str, object]]] = None,
    revision_scope_id: str = "",
    dut: str = "",
) -> Dict[str, object]:
    """Claim, execute, and checkpoint at most one dependency-ready LLM task."""
    if lease_seconds <= 0 or max_attempts <= 0:
        raise ValueError("lease_seconds and max_attempts must be positive")
    if finalization_root is not None and finalizer is None:
        finalizer = lambda: finalize_llm_task_batch(
            store_specs,
            finalization_root,
            revision_scope_id=revision_scope_id,
            dut=dut,
        )
    tasks = list(_scan_tasks(
        store_specs, revision_scope_id=revision_scope_id, dut=dut,
    ))
    issues = dependency_issues(tasks)
    ready = sorted(
        (
            task for task in tasks
            if task.get("status") in {"pending", "retryable_failed", "running"}
            and int(task.get("attempts", 0) or 0) < max_attempts
            and task_readiness(task, tasks, issues=issues)["ready"]
        ),
        key=lambda task: (str(task.get("task_type") or ""), str(task.get("task_id") or "")),
    )
    claimed = None
    store = None
    token = ""
    for task in ready:
        candidate_store = _store_for(task)
        candidate_token = candidate_store.try_claim(
            task["task_input"], worker_id=worker_id or default_worker_id(),
            lease_seconds=lease_seconds,
        ) or ""
        if candidate_token:
            claimed, store, token = task, candidate_store, candidate_token
            break
    if claimed is None:
        completion = task_batch_completion(tasks)
        finalization = {"triggered": False, "status": "not_configured"}
        if finalization_root is not None and finalizer is not None:
            finalization = finalize_if_ready(finalization_root, tasks, finalizer)
        return {
            "claimed": False,
            "task_id": "",
            "task_type": "",
            "task_status": "",
            "readiness": summarize_task_readiness(tasks),
            "completion": completion,
            "finalization": finalization,
        }

    task_input = claimed["task_input"]
    task_type = str(claimed["task_type"])
    runtime = _hydrate_runtime(task_input, runtime_config)
    interval = heartbeat_interval_seconds
    if interval is None:
        interval = max(1.0, min(30.0, lease_seconds / 3.0))
    heartbeat = LeaseHeartbeat(
        lambda: store.renew_claim(task_input, token, lease_seconds=lease_seconds),
        interval_seconds=interval,
    ).start()
    task_status = "retryable_failed"
    error_text = ""
    try:
        client = client_factory(runtime)
        if client is None:
            raise ValueError("selected LLM runtime did not build a client")
        output = EXECUTORS[task_type](task_input, client, runtime)
        heartbeat.stop()
        heartbeat.ensure_owned()
        _persist_success(store, claimed, output, token)
        task_status = "succeeded"
    except BaseException as exc:
        heartbeat.stop()
        if isinstance(exc, TaskLeaseLost):
            error_text = f"{type(exc).__name__}: {exc}"
            task_status = "lease_lost"
        else:
            try:
                heartbeat.ensure_owned()
                category = classify_task_error(exc).get("error_category")
                terminal = (
                    int(claimed.get("attempts", 0) or 0) + 1 >= max_attempts
                    or category in {"response_validation", "authentication_or_permission"}
                )
                if terminal and hasattr(store, "save_permanent_failure"):
                    store.save_permanent_failure(task_input, exc, lease_token=token)
                    task_status = "permanently_failed"
                else:
                    store.save_failure(task_input, exc, lease_token=token)
                    task_status = "retryable_failed"
                error_text = f"{type(exc).__name__}: {exc}"
            except TaskLeaseLost as lease_error:
                error_text = f"TaskLeaseLost: {lease_error}"
                task_status = "lease_lost"

    refreshed = list(_scan_tasks(
        store_specs, revision_scope_id=revision_scope_id, dut=dut,
    ))
    completion = task_batch_completion(refreshed)
    finalization = {"triggered": False, "status": "not_configured"}
    if finalization_root is not None and finalizer is not None:
        finalization = finalize_if_ready(finalization_root, refreshed, finalizer)
    return {
        "claimed": True,
        "task_id": str(claimed["task_id"]),
        "task_type": task_type,
        "task_status": task_status,
        "last_error": error_text,
        "readiness": summarize_task_readiness(refreshed),
        "completion": completion,
        "finalization": finalization,
    }


def run_llm_task_batch(
    store_specs: Sequence[StoreSpec],
    runtime_config: Mapping[str, object],
    *,
    client_factory: Callable[[Mapping[str, object]], object] = build_semantic_llm_client,
    worker_id: str = "",
    lease_seconds: int = 900,
    heartbeat_interval_seconds: Optional[float] = None,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 30.0,
    retry_max_backoff_seconds: float = 60.0,
    retry_jitter_ratio: float = 0.1,
    finalization_root: Optional[Path] = None,
    finalizer: Optional[Callable[[], Mapping[str, object]]] = None,
    revision_scope_id: str = "",
    dut: str = "",
    sleeper: Callable[[float], None] = time.sleep,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> Dict[str, object]:
    """Sequentially drain one frozen batch while honoring retry backoff."""
    if retry_backoff_seconds < 0 or retry_max_backoff_seconds < retry_backoff_seconds:
        raise ValueError("invalid retry backoff bounds")
    if not 0.0 <= retry_jitter_ratio <= 1.0:
        raise ValueError("retry_jitter_ratio must be within 0..1")
    cached_clients: Dict[tuple, object] = {}

    def cached_factory(runtime: Mapping[str, object]) -> object:
        key = tuple(
            str(runtime.get(field) or "")
            for field in ("provider", "backend", "model", "base_url", "request_timeout_seconds", "sdk_max_retries")
        )
        if key not in cached_clients:
            cached_clients[key] = client_factory(runtime)
        return cached_clients[key]

    outcomes = []
    failures_by_task: Dict[str, int] = {}
    try:
        while True:
            outcome = run_one_ready_llm_task(
                store_specs, runtime_config,
                client_factory=cached_factory,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                max_attempts=max_attempts,
                finalization_root=finalization_root,
                finalizer=finalizer,
                revision_scope_id=revision_scope_id,
                dut=dut,
            )
            outcomes.append(outcome)
            if not outcome.get("claimed"):
                break
            task_id = str(outcome.get("task_id") or "")
            if outcome.get("task_status") == "retryable_failed":
                failure_number = failures_by_task.get(task_id, 0) + 1
                failures_by_task[task_id] = failure_number
                base_delay = min(
                    retry_max_backoff_seconds,
                    retry_backoff_seconds * (2 ** max(0, failure_number - 1)),
                )
                spread = base_delay * retry_jitter_ratio
                delay = max(0.0, random_uniform(base_delay - spread, base_delay + spread))
                if delay:
                    sleeper(delay)
            elif outcome.get("task_status") == "succeeded":
                failures_by_task.pop(task_id, None)
    finally:
        for client in cached_clients.values():
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    final = outcomes[-1] if outcomes else {}
    return {
        "schema": "benchmark_llm_task_batch_run.v1",
        "attempted_task_calls": sum(bool(item.get("claimed")) for item in outcomes),
        "succeeded_task_calls": sum(item.get("task_status") == "succeeded" for item in outcomes),
        "retryable_failed_task_calls": sum(item.get("task_status") == "retryable_failed" for item in outcomes),
        "permanently_failed_task_calls": sum(item.get("task_status") == "permanently_failed" for item in outcomes),
        "completion": final.get("completion", {}),
        "finalization": final.get("finalization", {}),
        "readiness": final.get("readiness", {}),
        "outcomes": outcomes,
    }
