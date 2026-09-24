"""Provider-free adapters around durable failure-mode and RTL-root appeal tasks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Dict, Mapping, Sequence

from .failure_mode import classify_failure_mode
from .failure_mode_task_store import FailureModeTaskStore
from .rtl_root_appeal_task_store import RtlRootAppealTaskStore
from .rtl_root_clustering import (
    consume_rtl_root_review_plan,
    prepare_rtl_root_review_plan,
    root_signature_brief,
)
from .stage_workflow import load_stage_workflow, refresh_stage_workflow, update_stage_workflow
from .task_manifest import atomic_write_json, stable_hash, utc_now


FAILURE_INPUT_SCHEMA = "benchmark_root_failure_mode_stage_input.v1"
APPEAL_INPUT_SCHEMA = "benchmark_rtl_root_appeal_stage_input.v1"


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _stage(workflow: Mapping[str, object], stage_id: str) -> Mapping[str, object]:
    for item in workflow.get("stages", []) or []:
        if isinstance(item, dict) and item.get("stage_id") == stage_id:
            return item
    raise ValueError(f"workflow stage is missing: {stage_id}")


def _require_succeeded(workflow: Mapping[str, object], stage_id: str) -> None:
    if _stage(workflow, stage_id).get("status") != "succeeded":
        raise ValueError(f"workflow stage is not complete: {stage_id}")


def _verify_finalized_batch(
    path: Path, expected_ids: Sequence[str], task_type: str,
) -> Dict[str, object]:
    if not expected_ids:
        return {}
    payload = _read_json(path)
    if payload.get("schema") != "benchmark_finalized_llm_task_batch.v1":
        raise ValueError(f"finalized {task_type} task batch is missing")
    rows = [item for item in payload.get("tasks", []) or [] if isinstance(item, dict)]
    if {str(item.get("task_id") or "") for item in rows} != set(expected_ids):
        raise ValueError(f"finalized {task_type} batch does not match prepared TaskIDs")
    if any(item.get("task_type") != task_type for item in rows):
        raise ValueError(f"finalized {task_type} batch contains another task type")
    return payload


def _comparison(root: Path) -> Dict[str, object]:
    path = root / "semantic" / "comparison_result.json"
    payload = _read_json(path)
    if not payload:
        raise ValueError(f"semantic comparison result is missing: {path}")
    return payload


def prepare_root_failure_mode_stage(
    root: Path, runtime_config: Mapping[str, object],
) -> Dict[str, object]:
    """Freeze rule-undetermined record reviews; never construct an LLM client."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    _require_succeeded(workflow, "semantic_consume")
    comparison = _comparison(root)
    comparison_hash = stable_hash(comparison)
    if comparison_hash != _stage(workflow, "semantic_consume").get("output_hash"):
        raise ValueError("semantic comparison failed integrity validation")
    records = [
        copy.deepcopy(item)
        for item in comparison.get("benchmark_records", []) or []
        if isinstance(item, dict)
        and item.get("status") == "found"
        and classify_failure_mode(item) == "undetermined"
    ]
    semantic_input = _read_json(root / "semantic" / "input.json")
    task_runtime = dict(runtime_config)
    task_runtime["task_revision_scope"] = semantic_input.get("revision_scope", {})
    store_dir = root / "root_review" / "failure_mode_store"
    store = FailureModeTaskStore(store_dir)
    task_inputs = [store.prepare(record, task_runtime) for record in records]
    payload = {
        "schema": FAILURE_INPUT_SCHEMA,
        "comparison_result_hash": comparison_hash,
        "task_ids": [str(item["task_id"]) for item in task_inputs],
        "tasks": [
            {
                "task_id": item["task_id"],
                "input_snapshot_hash": item["input_snapshot_hash"],
                "canonical_bug": item.get("canonical_bug"),
                "model": item.get("record_model"),
            }
            for item in task_inputs
        ],
        "created_at": utc_now(),
    }
    path = root / "root_review" / "failure_mode_input.json"
    existing = _read_json(path)
    comparable = lambda item: {key: item.get(key) for key in ("schema", "comparison_result_hash", "task_ids", "tasks")}
    if existing and stable_hash(comparable(existing)) != stable_hash(comparable(payload)):
        raise ValueError("root failure-mode stage input changed in place")
    if existing:
        payload = existing
    atomic_write_json(path, payload)
    execute_status = "succeeded" if not task_inputs else "pending"
    update_stage_workflow(root, "root_review_prepare", {
        "status": "succeeded", "output_ref": path.relative_to(root).as_posix(),
        "output_hash": stable_hash(payload), "completed_at": utc_now(),
    }, workflow_values={
        "failure_mode_task_store_dir": str(store_dir.resolve()),
        "failure_mode_finalization_dir": str((root / "root_review" / "failure_mode_finalization").resolve()),
        "failure_mode_task_ids": payload["task_ids"],
    })
    return update_stage_workflow(root, "root_failure_mode_execute", {
        "status": execute_status, "not_applicable": not task_inputs,
    })


def prepare_rtl_root_appeal_stage(
    root: Path, runtime_config: Mapping[str, object],
    *, finalize_scores: bool = True,
) -> Dict[str, object]:
    """Consume failure-mode results and freeze the resulting structural appeal queue."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    _require_succeeded(workflow, "root_failure_mode_execute")
    comparison = _comparison(root)
    failure_input = _read_json(root / "root_review" / "failure_mode_input.json")
    if failure_input.get("comparison_result_hash") != stable_hash(comparison):
        raise ValueError("root failure-mode source comparison changed")
    failure_ids = [str(item) for item in failure_input.get("task_ids", []) or []]
    _verify_finalized_batch(
        root / "root_review" / "failure_mode_finalization" / "finalized_task_outputs.json",
        failure_ids, "failure_mode_review",
    )
    failure_store = FailureModeTaskStore(Path(str(workflow["failure_mode_task_store_dir"])))
    failure_reviews = []
    for task_id in failure_ids:
        task_input = _read_json(Path(str(workflow["failure_mode_task_store_dir"])) / "tasks" / task_id / "input.json")
        review = failure_store.load_success(task_input)
        if review is None:
            raise ValueError(f"failure-mode task output failed strict validation: {task_id}")
        failure_reviews.append(review)
    plan = prepare_rtl_root_review_plan(
        comparison.get("benchmark_records", []) or [],
        comparison.get("model_names", []) or [],
        failure_reviews,
        dict(runtime_config),
        finalize_scores=finalize_scores,
    )
    semantic_input = _read_json(root / "semantic" / "input.json")
    task_runtime = dict(runtime_config)
    task_runtime["task_revision_scope"] = semantic_input.get("revision_scope", {})
    store_dir = root / "root_review" / "rtl_root_appeal_store"
    store = RtlRootAppealTaskStore(store_dir)
    task_inputs = []
    for item in plan.get("selected_review_queue", []) or []:
        left = item.get("left_signature") if isinstance(item.get("left_signature"), dict) else {}
        right = item.get("right_signature") if isinstance(item.get("right_signature"), dict) else {}
        prepared_item = copy.deepcopy(item)
        prepared_item.setdefault("dut", left.get("dut") or right.get("dut") or workflow.get("dut"))
        task_inputs.append(store.prepare(
            prepared_item, root_signature_brief(left), root_signature_brief(right), task_runtime,
        ))
    payload = {
        "schema": APPEAL_INPUT_SCHEMA,
        "comparison_result_hash": stable_hash(comparison),
        "failure_mode_task_ids": failure_ids,
        "task_ids": [str(item["task_id"]) for item in task_inputs],
        "tasks": [
            {"task_id": item["task_id"], "input_snapshot_hash": item["input_snapshot_hash"]}
            for item in task_inputs
        ],
        "plan": plan,
        "created_at": utc_now(),
    }
    path = root / "root_review" / "rtl_root_appeal_input.json"
    existing = _read_json(path)
    comparable = lambda item: {
        key: item.get(key)
        for key in ("schema", "comparison_result_hash", "failure_mode_task_ids", "task_ids", "tasks", "plan")
    }
    if existing and stable_hash(comparable(existing)) != stable_hash(comparable(payload)):
        raise ValueError("RTL-root appeal stage input changed in place")
    if existing:
        payload = existing
    atomic_write_json(path, payload)
    update_stage_workflow(root, "rtl_root_appeal_prepare", {
        "status": "succeeded", "output_ref": path.relative_to(root).as_posix(),
        "output_hash": stable_hash(payload), "completed_at": utc_now(),
    }, workflow_values={
        "rtl_root_appeal_task_store_dir": str(store_dir.resolve()),
        "rtl_root_appeal_finalization_dir": str((root / "root_review" / "rtl_root_appeal_finalization").resolve()),
        "rtl_root_appeal_task_ids": payload["task_ids"],
    })
    return update_stage_workflow(root, "rtl_root_appeal_execute", {
        "status": "succeeded" if not task_inputs else "pending",
        "not_applicable": not task_inputs,
    })


def consume_finalized_root_review_stage(root: Path, *, finalize_scores: bool = True) -> Dict[str, object]:
    """Strictly consume appeal outputs and checkpoint deterministic root clustering."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    _require_succeeded(workflow, "rtl_root_appeal_execute")
    comparison = _comparison(root)
    appeal_input = _read_json(root / "root_review" / "rtl_root_appeal_input.json")
    if appeal_input.get("comparison_result_hash") != stable_hash(comparison):
        raise ValueError("RTL-root appeal source comparison changed")
    task_ids = [str(item) for item in appeal_input.get("task_ids", []) or []]
    _verify_finalized_batch(
        root / "root_review" / "rtl_root_appeal_finalization" / "finalized_task_outputs.json",
        task_ids, "rtl_root_appeal",
    )
    store_dir = Path(str(workflow["rtl_root_appeal_task_store_dir"]))
    store = RtlRootAppealTaskStore(store_dir)
    reviews = []
    for task_id in task_ids:
        task_input = _read_json(store_dir / "tasks" / task_id / "input.json")
        review = store.load_success(task_input)
        if review is None:
            raise ValueError(f"RTL-root appeal output failed strict validation: {task_id}")
        reviews.append(review)
    result = consume_rtl_root_review_plan(
        comparison.get("benchmark_records", []) or [],
        comparison.get("model_names", []) or [],
        appeal_input.get("plan", {}) or {},
        reviews,
        finalize_scores=finalize_scores,
    )
    output_path = root / "root_review" / "result.json"
    atomic_write_json(output_path, result)
    return update_stage_workflow(root, "root_review_execute", {
        "status": "succeeded", "output_ref": output_path.relative_to(root).as_posix(),
        "output_hash": stable_hash(result), "completed_at": utc_now(),
    })
