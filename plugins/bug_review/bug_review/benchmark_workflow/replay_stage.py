"""Staged replay preparation and deterministic result consumption."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Dict, Mapping

from .pipeline import merge_benchmark_replay_results
from .stage_workflow import refresh_stage_workflow, update_stage_workflow
from .task_manifest import atomic_write_json, stable_hash, utc_now
from .task_orchestration import prepare_task_workspace, replay_results_from_workspace


REPLAY_INPUT_SCHEMA = "benchmark_replay_stage_input.v1"


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


def _root_review_source(
    root: Path, workflow: Mapping[str, object],
) -> Dict[str, object]:
    comparison = _read_json(root / "semantic" / "comparison_result.json")
    root_result = _read_json(root / "root_review" / "result.json")
    if not comparison or not root_result:
        raise ValueError("semantic comparison or root-review result is missing")
    if stable_hash(comparison) != _stage(workflow, "semantic_consume").get("output_hash"):
        raise ValueError("semantic comparison failed integrity validation")
    if stable_hash(root_result) != _stage(workflow, "root_review_execute").get("output_hash"):
        raise ValueError("root-review result failed integrity validation")
    payload = copy.deepcopy(comparison)
    payload.update(copy.deepcopy(root_result))
    return payload


def prepare_replay_stage(root: Path) -> Dict[str, object]:
    """Freeze replay contracts into the existing lease/heartbeat workspace."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    _require_succeeded(workflow, "root_review_execute")
    source = _root_review_source(root, workflow)
    source_hash = stable_hash(source)
    replay_root = root / "replay"
    source_path = replay_root / "source_benchmark.json"
    prior_source = _read_json(source_path)
    if prior_source and stable_hash(prior_source) != source_hash:
        raise ValueError("replay stage source changed in place")
    if not prior_source:
        atomic_write_json(source_path, source)
    workspace = replay_root / "task_workspace"
    manifest = prepare_task_workspace(source_path, workspace)
    replay_tasks = [
        item for item in manifest.get("tasks", []) or []
        if isinstance(item, dict) and item.get("task_type") == "replay"
    ]
    task_ids = [str(item.get("task_id") or "") for item in replay_tasks]
    stage_input = {
        "schema": REPLAY_INPUT_SCHEMA,
        "source_benchmark_hash": source_hash,
        "replay_task_ids": task_ids,
        "replay_contract_count": len(source.get("replay_runner_contracts", []) or []),
        "created_at": utc_now(),
    }
    input_path = replay_root / "input.json"
    existing = _read_json(input_path)
    comparable_keys = ("schema", "source_benchmark_hash", "replay_task_ids", "replay_contract_count")
    if existing and stable_hash({key: existing.get(key) for key in comparable_keys}) != stable_hash({
        key: stage_input.get(key) for key in comparable_keys
    }):
        raise ValueError("replay stage input changed in place")
    if existing:
        stage_input = existing
    atomic_write_json(input_path, stage_input)
    update_stage_workflow(root, "replay_prepare", {
        "status": "succeeded", "output_ref": input_path.relative_to(root).as_posix(),
        "output_hash": stable_hash(stage_input), "completed_at": utc_now(),
    }, workflow_values={
        "replay_source_benchmark_path": str(source_path.resolve()),
        "replay_source_benchmark_hash": source_hash,
        "replay_task_workspace_dir": str(workspace.resolve()),
        "replay_task_ids": task_ids,
    })
    return update_stage_workflow(root, "replay_execute", {
        "status": "succeeded" if not task_ids else "pending",
        "not_applicable": not task_ids,
    })


def consume_finalized_replay_stage(root: Path, *, finalize_scores: bool = True) -> Dict[str, object]:
    """Validate every frozen replay result and merge without semantic LLM calls."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    _require_succeeded(workflow, "replay_execute")
    source_path = Path(str(workflow.get("replay_source_benchmark_path") or ""))
    source = _read_json(source_path)
    if stable_hash(source) != workflow.get("replay_source_benchmark_hash"):
        raise ValueError("replay source benchmark failed integrity validation")
    workspace = Path(str(workflow.get("replay_task_workspace_dir") or ""))
    manifest = _read_json(workspace / "task_manifest.json")
    expected_ids = {str(item) for item in workflow.get("replay_task_ids", []) or []}
    replay_tasks = [
        item for item in manifest.get("tasks", []) or []
        if isinstance(item, dict) and item.get("task_type") == "replay"
    ]
    if {str(item.get("task_id") or "") for item in replay_tasks} != expected_ids:
        raise ValueError("replay manifest does not match prepared TaskIDs")
    for task in replay_tasks:
        if task.get("status") != "succeeded":
            raise ValueError(f"replay task is not succeeded: {task.get('task_id')}")
        output_ref = str(task.get("output_ref") or "")
        row = _read_json(workspace / output_ref) if output_ref else {}
        result = row.get("result") if isinstance(row.get("result"), dict) else None
        if (
            str(row.get("candidate_id") or "") != str(task.get("candidate_id") or "")
            or result is None
            or stable_hash(result) != task.get("output_hash")
        ):
            raise ValueError(f"replay task output failed integrity validation: {task.get('task_id')}")
    replay_results = replay_results_from_workspace(workspace, manifest)
    if len(replay_results.get("results", []) or []) != len(expected_ids):
        raise ValueError("replay result count does not match prepared TaskIDs")
    # The staged semantic snapshot intentionally contains no mutable run graph,
    # so this merge cannot introduce a hidden targeted semantic LLM pass.
    merged = merge_benchmark_replay_results(
        source, replay_results, semantic_llm_config={}, finalize_scores=finalize_scores,
    )
    output_path = root / "replay" / "merged_result.json"
    atomic_write_json(output_path, merged)
    atomic_write_json(root / "replay" / "replay_results.json", replay_results)
    return update_stage_workflow(root, "replay_consume", {
        "status": "succeeded", "output_ref": output_path.relative_to(root).as_posix(),
        "output_hash": stable_hash(merged), "completed_at": utc_now(),
    })
