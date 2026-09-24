"""Persisted stage DAG for external semantic execution and sync continuation."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
from typing import Dict, Iterator, Mapping, Optional

from .pipeline import (
    _build_comparison_result,
    _collect_semantic_llm_pairs,
    _is_excluded_declared_candidate,
    normalize_semantic_pair_config,
)
from .semantic_task_store import SemanticTaskStore
from .task_dependencies import summarize_task_readiness
from .task_manifest import atomic_write_json, stable_hash, utc_now
from .task_revision_scope import build_revision_scope


SCHEMA = "benchmark_stage_workflow.v2"
INPUT_SCHEMA = "benchmark_semantic_stage_input.v1"
_SAFE_RUNTIME_FIELDS = (
    "active_profile", "provider", "backend", "model", "base_url",
    "request_timeout_seconds", "sdk_max_retries", "resource_pool_limit",
)


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


@contextmanager
def _stage_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "stage_workflow.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stage_row(stage_id: str, status: str, depends_on=None) -> Dict[str, object]:
    return {
        "task_id": stage_id,
        "stage_id": stage_id,
        "task_type": "workflow_stage",
        "status": status,
        "resumable": True,
        "depends_on": list(depends_on or []),
    }


def _initial_stages(semantic_task_count: int) -> list:
    execute_status = "succeeded" if semantic_task_count == 0 else "pending"
    return [
        _stage_row("semantic_prepare", "succeeded"),
        {
            **_stage_row("semantic_execute", execute_status, ["semantic_prepare"]),
            "not_applicable": semantic_task_count == 0,
        },
        _stage_row("semantic_consume", "pending", ["semantic_execute"]),
        _stage_row("root_review_prepare", "pending", ["semantic_consume"]),
        _stage_row("root_failure_mode_execute", "pending", ["root_review_prepare"]),
        _stage_row("rtl_root_appeal_prepare", "pending", ["root_failure_mode_execute"]),
        _stage_row("rtl_root_appeal_execute", "pending", ["rtl_root_appeal_prepare"]),
        _stage_row("root_review_execute", "pending", ["rtl_root_appeal_execute"]),
        _stage_row("replay_prepare", "pending", ["root_review_execute"]),
        _stage_row("replay_execute", "pending", ["replay_prepare"]),
        _stage_row("replay_consume", "pending", ["replay_execute"]),
        _stage_row("final_merge_render_score", "pending", ["replay_consume"]),
    ]


def _stage_by_id(workflow: Mapping[str, object], stage_id: str) -> Dict[str, object]:
    for stage in workflow.get("stages", []) or []:
        if isinstance(stage, dict) and stage.get("stage_id") == stage_id:
            return stage
    raise ValueError(f"workflow stage is missing: {stage_id}")


def load_stage_workflow(root: Path) -> Dict[str, object]:
    workflow = _read_json(Path(root) / "stage_workflow.json")
    if workflow.get("schema") != SCHEMA:
        raise ValueError(f"missing or unsupported stage workflow: {Path(root) / 'stage_workflow.json'}")
    return workflow


def update_stage_workflow(
    root: Path,
    stage_id: str,
    values: Mapping[str, object],
    *,
    workflow_values: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Atomically checkpoint one adapter-owned stage transition."""
    root = Path(root)
    with _stage_lock(root):
        workflow = load_stage_workflow(root)
        _stage_by_id(workflow, stage_id).update(copy.deepcopy(dict(values)))
        if workflow_values:
            workflow.update(copy.deepcopy(dict(workflow_values)))
        workflow["updated_at"] = utc_now()
        atomic_write_json(root / "stage_workflow.json", workflow)
    return refresh_stage_workflow(root)


def prepare_semantic_stage(
    comparison_input: Mapping[str, object],
    root: Path,
    runtime_config: Mapping[str, object],
    semantic_pair_config: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Freeze candidate pairs and prepare durable tasks without calling an LLM."""
    root = Path(root)
    raw_candidates = [
        copy.deepcopy(item)
        for item in comparison_input.get("flat_candidates", []) or []
        if isinstance(item, dict)
    ]
    flat_candidates = [
        item for item in raw_candidates if not _is_excluded_declared_candidate(item)
    ]
    run_graphs = [
        copy.deepcopy(item)
        for item in comparison_input.get("run_graphs", []) or []
        if isinstance(item, dict)
    ]
    model_names = [str(item) for item in comparison_input.get("model_names", []) or []]
    if not model_names:
        model_names = sorted({str(item.get("model") or "") for item in flat_candidates if item.get("model")})
    duts = {str(item.get("dut") or "") for item in raw_candidates if item.get("dut")}
    if len(duts) > 1:
        raise ValueError("semantic stage input must contain exactly one DUT")
    dut = next(iter(duts), str(comparison_input.get("dut") or ""))
    normalized_policy = normalize_semantic_pair_config(semantic_pair_config)
    task_store_dir = root / "semantic" / "task_store"
    # Cache location is execution metadata, not semantic policy identity.
    # Keeping it out of the source snapshot makes the same frozen comparison
    # portable across stage workspace directories.
    normalized_policy["task_store_dir"] = ""
    source_snapshot = {
        "dut": dut,
        "model_names": model_names,
        # Preserve excluded declarations for deterministic audit output. Pair
        # preparation below still uses only the active subset.
        "flat_candidates": raw_candidates,
        "run_graphs": run_graphs,
        "model_sources": copy.deepcopy(comparison_input.get("model_sources", []) or []),
        "semantic_pair_config": normalized_policy,
    }
    source_hash = stable_hash(source_snapshot)
    revision_scope = build_revision_scope(
        dut,
        {
            "runs": [
                {
                    "model": (graph.get("manifest") or {}).get("model")
                    if isinstance(graph.get("manifest"), dict) else "",
                    "run_key": (graph.get("manifest") or {}).get("run_key")
                    if isinstance(graph.get("manifest"), dict) else "",
                }
                for graph in run_graphs
            ],
            "candidates": [
                {"candidate_id": item.get("candidate_id"), "snapshot_hash": stable_hash(item)}
                for item in raw_candidates
            ],
        },
    )
    task_runtime = dict(runtime_config)
    task_runtime["task_revision_scope"] = revision_scope
    pairs, pair_scores = _collect_semantic_llm_pairs(
        flat_candidates,
        semantic_pair_mode=str(normalized_policy["mode"]),
        semantic_pair_budget=int(normalized_policy["budget"]),
        semantic_pair_recall=str(normalized_policy["recall"]),
    )
    store = SemanticTaskStore(task_store_dir)
    task_inputs = [store.prepare(left, right, score, task_runtime) for left, right, score in pairs]
    semantic_input = {
        "schema": INPUT_SCHEMA,
        "source_snapshot_hash": source_hash,
        "revision_scope": revision_scope,
        "semantic_config": {
            field: copy.deepcopy(runtime_config[field])
            for field in _SAFE_RUNTIME_FIELDS
            if runtime_config.get(field) not in {None, ""}
        },
        **source_snapshot,
        "selected_pairs": [
            {
                "left_candidate_id": left.get("candidate_id"),
                "right_candidate_id": right.get("candidate_id"),
                "score": score,
                "task_id": task_input.get("task_id"),
                "input_snapshot_hash": task_input.get("input_snapshot_hash"),
            }
            for (left, right, score), task_input in zip(pairs, task_inputs)
        ],
        "cross_model_pair_scores": [
            {"left_candidate_id": key[0], "right_candidate_id": key[1], "score": value}
            for key, value in sorted(pair_scores.items())
        ],
    }
    input_path = root / "semantic" / "input.json"
    workflow_path = root / "stage_workflow.json"
    with _stage_lock(root):
        existing = _read_json(input_path)
        if existing and stable_hash(existing) != stable_hash(semantic_input):
            raise ValueError("semantic stage input changed in place; use a new stage workspace")
        atomic_write_json(input_path, semantic_input)
        prior = _read_json(workflow_path)
        if prior and prior.get("source_snapshot_hash") != source_hash:
            raise ValueError("stage workflow source snapshot changed in place")
        workflow = prior or {
            "schema": SCHEMA,
            "dut": dut,
            "source_snapshot_hash": source_hash,
            "revision_scope_id": revision_scope.get("revision_scope_id", ""),
            "semantic_task_store_dir": str(task_store_dir.resolve()),
            "semantic_finalization_dir": str((root / "semantic" / "finalization").resolve()),
            "semantic_task_ids": [str(item["task_id"]) for item in task_inputs],
            "stages": _initial_stages(len(task_inputs)),
            "created_at": utc_now(),
        }
        workflow["updated_at"] = utc_now()
        atomic_write_json(workflow_path, workflow)
    return refresh_stage_workflow(root)


def refresh_stage_workflow(root: Path) -> Dict[str, object]:
    """Synchronize externally executed stage state from durable sidecars only."""
    root = Path(root)
    with _stage_lock(root):
        workflow_path = root / "stage_workflow.json"
        workflow = _read_json(workflow_path)
        if workflow.get("schema") != SCHEMA:
            raise ValueError(f"missing or unsupported stage workflow: {workflow_path}")
        for stage_id, ids_field, store_field in (
            ("semantic_execute", "semantic_task_ids", "semantic_task_store_dir"),
            ("root_failure_mode_execute", "failure_mode_task_ids", "failure_mode_task_store_dir"),
            ("rtl_root_appeal_execute", "rtl_root_appeal_task_ids", "rtl_root_appeal_task_store_dir"),
        ):
            try:
                execute = _stage_by_id(workflow, stage_id)
            except ValueError:
                continue
            if ids_field not in workflow:
                continue
            task_ids = [str(item) for item in workflow.get(ids_field, []) or []]
            statuses = []
            for task_id in task_ids:
                state = _read_json(
                    Path(str(workflow[store_field])) / "tasks" / task_id / "state.json"
                )
                statuses.append(str(state.get("status") or "pending"))
            if not task_ids or statuses and all(status == "succeeded" for status in statuses):
                execute["status"] = "succeeded"
            elif any(status in {"permanently_failed", "cancelled", "superseded"} for status in statuses):
                execute["status"] = "permanently_failed"
            elif any(status == "running" for status in statuses):
                execute["status"] = "running"
            elif any(status == "retryable_failed" for status in statuses):
                execute["status"] = "retryable_failed"
            else:
                execute["status"] = "pending"
            execute["task_status_counts"] = {
                status: statuses.count(status) for status in sorted(set(statuses))
            }
        if "replay_task_ids" in workflow and workflow.get("replay_task_workspace_dir"):
            replay_ids = {str(item) for item in workflow.get("replay_task_ids", []) or []}
            manifest = _read_json(
                Path(str(workflow["replay_task_workspace_dir"])) / "task_manifest.json"
            )
            replay_statuses = {
                str(item.get("task_id") or ""): str(item.get("status") or "pending")
                for item in manifest.get("tasks", []) or []
                if isinstance(item, dict) and item.get("task_type") == "replay"
            }
            execute = _stage_by_id(workflow, "replay_execute")
            if set(replay_statuses) != replay_ids:
                execute["status"] = "permanently_failed"
                execute["last_error"] = "replay manifest TaskIDs differ from prepared stage"
            else:
                statuses = [replay_statuses[task_id] for task_id in sorted(replay_ids)]
                if not statuses or all(status == "succeeded" for status in statuses):
                    execute["status"] = "succeeded"
                elif any(status in {"permanently_failed", "cancelled", "superseded"} for status in statuses):
                    execute["status"] = "permanently_failed"
                elif any(status == "running" for status in statuses):
                    execute["status"] = "running"
                elif any(status == "retryable_failed" for status in statuses):
                    execute["status"] = "retryable_failed"
                else:
                    execute["status"] = "pending"
                execute["task_status_counts"] = {
                    status: statuses.count(status) for status in sorted(set(statuses))
                }
        workflow["updated_at"] = utc_now()
        atomic_write_json(workflow_path, workflow)
        summary = summarize_task_readiness(
            [stage for stage in workflow.get("stages", []) or [] if isinstance(stage, dict)]
        )
        return {**workflow, "readiness": summary}


def consume_finalized_semantic_stage(root: Path) -> Dict[str, object]:
    """Strictly consume completed semantic tasks and run deterministic clustering."""
    root = Path(root)
    workflow = refresh_stage_workflow(root)
    execute = _stage_by_id(workflow, "semantic_execute")
    if execute.get("status") != "succeeded":
        raise ValueError("semantic task stage is not complete")
    stage_input = _read_json(root / "semantic" / "input.json")
    if stable_hash({
        key: stage_input.get(key)
        for key in (
            "dut", "model_names", "flat_candidates", "run_graphs", "model_sources",
            "semantic_pair_config",
        )
    }) != stage_input.get("source_snapshot_hash"):
        raise ValueError("semantic stage source snapshot failed integrity validation")
    expected = {
        str(item.get("task_id")): item
        for item in stage_input.get("selected_pairs", []) or []
        if isinstance(item, dict) and item.get("task_id")
    }
    if expected:
        finalized = _read_json(root / "semantic" / "finalization" / "finalized_task_outputs.json")
        finalized_ids = {
            str(item.get("task_id"))
            for item in finalized.get("tasks", []) or [] if isinstance(item, dict)
        }
        if finalized.get("schema") != "benchmark_finalized_llm_task_batch.v1":
            raise ValueError("finalized semantic task batch is missing")
        if finalized_ids != set(expected):
            raise ValueError("finalized semantic task batch does not match prepared TaskIDs")
    store = SemanticTaskStore(Path(str(workflow["semantic_task_store_dir"])))
    judgements = []
    appeals = []
    for task_id in sorted(expected):
        task_input = _read_json(
            Path(str(workflow["semantic_task_store_dir"])) / "tasks" / task_id / "input.json"
        )
        if task_input.get("input_snapshot_hash") != expected[task_id].get("input_snapshot_hash"):
            raise ValueError(f"semantic task input hash mismatch: {task_id}")
        bundle = store.load_success(task_input)
        if bundle is None:
            raise ValueError(f"semantic task output failed strict validation: {task_id}")
        judgements.append(bundle["semantic_judgement"])
        if isinstance(bundle.get("semantic_appeal"), dict):
            appeals.append(bundle["semantic_appeal"])
    comparison_candidates = copy.deepcopy(stage_input.get("flat_candidates", []) or [])
    # v2 prepare snapshots preserve excluded declarations directly.  Recover
    # them from frozen run graphs for earlier staged workspaces whose pair-only
    # flat list had already discarded those audit rows.
    known_candidate_ids = {
        str(item.get("candidate_id") or "")
        for item in comparison_candidates if isinstance(item, dict)
    }
    for graph in stage_input.get("run_graphs", []) or []:
        if not isinstance(graph, dict):
            continue
        for candidate in graph.get("candidate_bugs", []) or []:
            if not isinstance(candidate, dict) or not _is_excluded_declared_candidate(candidate):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate_id and candidate_id not in known_candidate_ids:
                comparison_candidates.append(copy.deepcopy(candidate))
                known_candidate_ids.add(candidate_id)
    comparison = _build_comparison_result(
        comparison_candidates,
        list(stage_input.get("model_names", []) or []),
        copy.deepcopy(stage_input.get("run_graphs", []) or []),
        None,
        dict(stage_input.get("semantic_config", {}) or {}),
        semantic_pair_config=dict(stage_input.get("semantic_pair_config", {}) or {}),
        cached_semantic_judgements=judgements,
        cached_semantic_appeals=appeals,
        finalize_scores=False,
    )
    if stage_input.get("dut") and not comparison.get("dut"):
        comparison["dut"] = stage_input["dut"]
    if stage_input.get("model_sources"):
        comparison["model_sources"] = copy.deepcopy(stage_input["model_sources"])
    output_path = root / "semantic" / "comparison_result.json"
    atomic_write_json(output_path, comparison)
    with _stage_lock(root):
        current = _read_json(root / "stage_workflow.json")
        consume = _stage_by_id(current, "semantic_consume")
        consume.update({
            "status": "succeeded",
            "output_ref": output_path.relative_to(root).as_posix(),
            "output_hash": stable_hash(comparison),
            "completed_at": utc_now(),
        })
        current["updated_at"] = utc_now()
        atomic_write_json(root / "stage_workflow.json", current)
    return refresh_stage_workflow(root)
