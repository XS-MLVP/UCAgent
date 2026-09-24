"""Persistent task and benchmark-revision metadata.

This module deliberately contains no LLM, replay, clustering, or rendering
logic.  It records immutable task inputs and classifies existing outputs so
the execution layer can resume work without making the manifest itself an
executor.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .task_dependencies import summarize_task_readiness


TASK_SCHEMA = "benchmark_task_manifest.v1"
REVISION_SCHEMA = "benchmark_revision.v1"
TASK_STATES = {
    "pending",
    "running",
    "succeeded",
    "retryable_failed",
    "permanently_failed",
    "cancelled",
    "superseded",
}
TERMINAL_TASK_STATES = {
    "succeeded", "permanently_failed", "cancelled", "superseded",
}
REPLAY_SUCCESS_STATUSES = {
    "reproduced",
    "not_reproduced",
    "not_reproduced_same_snapshot",
    "not_reproduced_snapshot_changed",
}
REPLAY_RETRYABLE_STATUSES = {
    "blocked",
    "blocked_environment",
    "infrastructure_incomplete",
    "partial_replay",
    "partially_reproduced",
    "timeout",
}
_TRANSIENT_REVISION_KEYS = {
    "benchmark_revision",
    "task_manifest",
    "generated_at",
    "updated_at",
    "started_at",
    "completed_at",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_is_active(lease: object) -> bool:
    if not isinstance(lease, dict):
        return False
    text = str(lease.get("expires_at") or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        expires = datetime.fromisoformat(text)
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires.astimezone(timezone.utc) > datetime.now(timezone.utc)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def _revision_projection(value: object) -> object:
    """Remove timestamps/private runtime caches from an immutable snapshot."""
    if isinstance(value, dict):
        return {
            str(key): _revision_projection(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _TRANSIENT_REVISION_KEYS
            and not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_revision_projection(item) for item in value]
    return value


def benchmark_snapshot_hash(payload: Mapping[str, object]) -> str:
    return stable_hash(_revision_projection(dict(payload)))


def _task_id(task_type: str, dut: str, logical_key: str, input_hash: str) -> str:
    digest = stable_hash({
        "schema": TASK_SCHEMA,
        "task_type": task_type,
        "dut": dut,
        "logical_key": logical_key,
        "input_hash": input_hash,
    })[:24]
    return f"{task_type}-{digest}"


def _base_task(
    *,
    task_type: str,
    dut: str,
    logical_key: str,
    task_input: Mapping[str, object],
    status: str,
    resumable: bool,
    output: Optional[Mapping[str, object]] = None,
    model: str = "",
    provider: str = "",
    prompt_hash: str = "",
) -> Dict[str, object]:
    if status not in TASK_STATES:
        raise ValueError(f"unsupported task status: {status}")
    input_hash = stable_hash(task_input)
    output_hash = stable_hash(output) if output is not None else ""
    return {
        "task_id": _task_id(task_type, dut, logical_key, input_hash),
        "task_type": task_type,
        "logical_key": logical_key,
        "dut": dut,
        "status": status,
        "resumable": bool(resumable),
        "input_hash": input_hash,
        "prompt_hash": prompt_hash,
        "output_hash": output_hash,
        "input_ref": "",
        "output_ref": "",
        "attempts": 0,
        "last_error": "",
        "provider": provider,
        "model": model,
        "depends_on": [],
    }


def _semantic_tasks(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    dut = str(payload.get("dut") or "")
    config = payload.get("semantic_llm_config", {})
    config = config if isinstance(config, dict) else {}
    llm_runtime = {
        key: config.get(key)
        for key in (
            "provider", "model", "base_url", "request_timeout_seconds", "sdk_max_retries",
        )
        if config.get(key) not in {None, ""}
    }
    pair_config = payload.get("semantic_pair_config", {})
    pair_config = pair_config if isinstance(pair_config, dict) else {}
    judgements = {
        tuple(sorted((str(row.get("left_candidate_id") or ""), str(row.get("right_candidate_id") or "")))): row
        for row in payload.get("semantic_judgements", []) or []
        if isinstance(row, dict)
        and row.get("left_candidate_id")
        and row.get("right_candidate_id")
    }

    expected_pairs = set(judgements)
    if str(pair_config.get("mode") or "") == "full_all_pairs":
        candidate_models: Dict[str, str] = {}
        for record in payload.get("benchmark_records", []) or []:
            if not isinstance(record, dict) or record.get("status") != "found":
                continue
            model = str(record.get("model") or "")
            for candidate_id in record.get("candidate_ids", []) or []:
                if candidate_id and model:
                    candidate_models[str(candidate_id)] = model
        candidate_ids = sorted(candidate_models)
        expected_pairs.update(
            (left, right)
            for index, left in enumerate(candidate_ids)
            for right in candidate_ids[index + 1:]
            if candidate_models[left] != candidate_models[right]
        )

    tasks = []
    for left_id, right_id in sorted(expected_pairs):
        row = judgements.get((left_id, right_id))
        judgement = row.get("judgement", {}) if isinstance(row, dict) else {}
        judgement = judgement if isinstance(judgement, dict) else {}
        relation = str(judgement.get("relation") or "")
        schema_valid = judgement.get("schema_valid")
        if row is None:
            status = "pending"
        elif schema_valid is False or not relation:
            status = "permanently_failed"
        else:
            status = "succeeded"
        score = row.get("score") if isinstance(row, dict) else None
        input_snapshot_hash = str(judgement.get("input_snapshot_hash") or "")
        prompt_hash = str(judgement.get("prompt_hash") or "")
        durable_task_id = str((row or {}).get("durable_task_id") or "") if isinstance(row, dict) else ""
        task_store_dir = str((row or {}).get("task_store_dir") or "") if isinstance(row, dict) else ""
        resumable = bool(durable_task_id and task_store_dir and input_snapshot_hash and prompt_hash)
        task_input = {
            "left_candidate_id": left_id,
            "right_candidate_id": right_id,
            "left_model": row.get("left_model") if isinstance(row, dict) else "",
            "right_model": row.get("right_model") if isinstance(row, dict) else "",
            "score": score,
            "semantic_policy": pair_config,
            "input_snapshot_hash": input_snapshot_hash,
            "llm_runtime": llm_runtime,
        }
        task = _base_task(
            task_type="semantic_judgement",
            dut=dut,
            logical_key=f"{left_id}__{right_id}",
            task_input=task_input,
            status=status,
            resumable=resumable,
            output=row if isinstance(row, dict) else None,
            model=str(config.get("model") or ""),
            provider=str(config.get("provider") or ""),
            prompt_hash=prompt_hash,
        )
        if resumable:
            task["task_id"] = durable_task_id
            task["task_store_dir"] = task_store_dir
            task["input_hash"] = input_snapshot_hash
            task["revision_scope_id"] = str(row.get("revision_scope_id") or "")
            task["task_source_snapshot_hash"] = str(row.get("task_source_snapshot_hash") or "")
        task["input_capture"] = (
            "durable_external_snapshot" if resumable
            else "frozen_snapshot_hash" if input_snapshot_hash and prompt_hash
            else "legacy_pair_identity_only"
        )
        if status == "permanently_failed":
            task["last_error"] = "saved semantic judgement is missing a schema-valid relation"
        elif status == "pending":
            task["last_error"] = "full_all_pairs output is missing this pair; frozen prompt input is unavailable"
        tasks.append(task)
    return tasks


def _failure_mode_tasks(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    dut = str(payload.get("dut") or "")
    config = payload.get("semantic_llm_config", {})
    config = config if isinstance(config, dict) else {}
    llm_runtime = {
        key: config.get(key)
        for key in (
            "provider", "model", "base_url", "request_timeout_seconds", "sdk_max_retries",
        )
        if config.get(key) not in {None, ""}
    }
    tasks = []
    for index, review in enumerate(payload.get("rtl_root_failure_mode_reviews", []) or []):
        if not isinstance(review, dict):
            continue
        canonical_bug = str(review.get("canonical_bug") or "")
        model_name = str(review.get("model") or "")
        logical_key = f"{canonical_bug}:{model_name}"
        method = str(review.get("method") or "")
        input_snapshot_hash = str(review.get("input_snapshot_hash") or "")
        prompt_hash = str(review.get("prompt_hash") or "")
        durable_task_id = str(review.get("durable_task_id") or "")
        task_store_dir = str(review.get("task_store_dir") or "")
        resumable = bool(
            durable_task_id and task_store_dir and input_snapshot_hash and prompt_hash
        )
        status = "permanently_failed" if method == "llm_error" else "succeeded"
        task = _base_task(
            task_type="failure_mode_review",
            dut=dut,
            logical_key=logical_key,
            task_input={
                "canonical_bug": canonical_bug,
                "model": model_name,
                "evidence_fields": review.get("evidence_fields", []),
                "input_snapshot_hash": input_snapshot_hash,
                "llm_runtime": llm_runtime,
            },
            status=status,
            resumable=resumable,
            output=review,
            model=str(config.get("model") or ""),
            provider=str(config.get("provider") or ""),
            prompt_hash=prompt_hash,
        )
        if resumable:
            task["task_id"] = durable_task_id
            task["task_store_dir"] = task_store_dir
            task["input_hash"] = input_snapshot_hash
            task["revision_scope_id"] = str(review.get("revision_scope_id") or "")
            task["task_source_snapshot_hash"] = str(review.get("task_source_snapshot_hash") or "")
        task["input_capture"] = (
            "durable_external_snapshot" if resumable
            else "frozen_snapshot_hash" if input_snapshot_hash and prompt_hash
            else "legacy_review_identity_only"
        )
        if status == "permanently_failed":
            task["last_error"] = str(review.get("rationale") or "failure-mode review failed")
        tasks.append(task)
    return tasks


def _appeal_tasks(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    dut = str(payload.get("dut") or "")
    config = payload.get("semantic_llm_config", {})
    config = config if isinstance(config, dict) else {}
    llm_runtime = {
        key: config.get(key)
        for key in (
            "provider", "model", "base_url", "request_timeout_seconds", "sdk_max_retries",
        )
        if config.get(key) not in {None, ""}
    }
    tasks = []
    rows: List[Tuple[str, Dict[str, object]]] = []
    rows.extend(
        ("semantic_appeal", row)
        for row in payload.get("semantic_appeals", []) or []
        if isinstance(row, dict)
    )
    rows.extend(
        ("rtl_root_appeal", row)
        for row in payload.get("rtl_root_llm_review", []) or []
        if isinstance(row, dict)
    )
    for index, (task_type, row) in enumerate(rows):
        left = str(row.get("left_candidate_id") or row.get("left_canonical_bug") or "")
        right = str(row.get("right_candidate_id") or row.get("right_canonical_bug") or "")
        method = str((row.get("appeal") or {}).get("method") or row.get("method") or "")
        detail = row.get("appeal") if isinstance(row.get("appeal"), dict) else row
        input_snapshot_hash = str(detail.get("input_snapshot_hash") or "")
        prompt_hash = str(detail.get("prompt_hash") or "")
        status = "permanently_failed" if method == "llm_error" else "succeeded"
        durable_task_id = str(row.get("durable_task_id") or "")
        task_store_dir = str(row.get("task_store_dir") or "")
        resumable = bool(
            task_type == "rtl_root_appeal"
            and durable_task_id and task_store_dir
            and input_snapshot_hash and prompt_hash
        )
        task = _base_task(
            task_type=task_type,
            dut=dut,
            logical_key=f"{left}__{right}",
            task_input={
                "left": left,
                "right": right,
                "base_reason": row.get("base_reason"),
                "input_snapshot_hash": input_snapshot_hash,
                "llm_runtime": llm_runtime,
            },
            status=status,
            resumable=resumable,
            output=row,
            model=str(config.get("model") or ""),
            provider=str(config.get("provider") or ""),
            prompt_hash=prompt_hash,
        )
        if resumable:
            task["task_id"] = durable_task_id
            task["task_store_dir"] = task_store_dir
            task["input_hash"] = input_snapshot_hash
            task["revision_scope_id"] = str(row.get("revision_scope_id") or "")
            task["task_source_snapshot_hash"] = str(row.get("task_source_snapshot_hash") or "")
        task["input_capture"] = (
            "durable_external_snapshot" if resumable
            else "frozen_snapshot_hash" if input_snapshot_hash and prompt_hash
            else "legacy_review_identity_only"
        )
        tasks.append(task)
    return tasks


def _candidate_replay_results(payload: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for item in payload.get("replay_candidates", []) or []:
        if not isinstance(item, dict) or not item.get("candidate_id"):
            continue
        result = item.get("replay_result")
        if isinstance(result, dict) and result.get("status"):
            results[str(item["candidate_id"])] = result
    for record in payload.get("benchmark_records", []) or []:
        if not isinstance(record, dict):
            continue
        candidate_ids = [str(item) for item in record.get("candidate_ids", []) or [] if item]
        replay_results = [item for item in record.get("replay_results", []) or [] if isinstance(item, dict)]
        if len(candidate_ids) == 1 and replay_results and replay_results[0].get("status"):
            results.setdefault(candidate_ids[0], replay_results[0])
    return results


def _replay_task_status(result: Optional[Mapping[str, object]]) -> str:
    status = str((result or {}).get("status") or "").strip().lower()
    if status in REPLAY_SUCCESS_STATUSES:
        return "succeeded"
    if status in REPLAY_RETRYABLE_STATUSES:
        return "retryable_failed"
    return "pending"


def _replay_tasks(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    dut = str(payload.get("dut") or "")
    replay_results = _candidate_replay_results(payload)
    tasks = []
    for index, contract in enumerate(payload.get("replay_runner_contracts", []) or []):
        if not isinstance(contract, dict):
            continue
        contract_input = contract.get("input", {})
        contract_input = contract_input if isinstance(contract_input, dict) else {}
        candidate_id = str(contract_input.get("candidate_id") or f"contract-{index}")
        result = replay_results.get(candidate_id)
        placeholder = contract.get("current_placeholder_result")
        if result is None and isinstance(placeholder, dict) and placeholder.get("status"):
            result = placeholder
        status = _replay_task_status(result)
        task = _base_task(
            task_type="replay",
            dut=dut,
            logical_key=candidate_id,
            task_input=contract,
            status=status,
            resumable=True,
            output=result,
        )
        task["candidate_id"] = candidate_id
        task["result_status"] = str((result or {}).get("status") or "")
        task["snapshot_hash"] = stable_hash(contract_input.get("content_snapshot", {}))
        if status == "retryable_failed":
            task["last_error"] = str((result or {}).get("reason") or task["result_status"])
        tasks.append(task)
    return tasks


def _stage_summary(tasks: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    stage_types = (
        "semantic_judgement",
        "semantic_appeal",
        "failure_mode_review",
        "rtl_root_appeal",
        "replay",
    )
    summary: Dict[str, object] = {}
    for task_type in stage_types:
        rows = [task for task in tasks if task.get("task_type") == task_type]
        counts = Counter(str(task.get("status") or "pending") for task in rows)
        incomplete = sum(count for state, count in counts.items() if state != "succeeded")
        summary[task_type] = {
            "task_count": len(rows),
            "status_counts": dict(sorted(counts.items())),
            "complete": incomplete == 0,
            "not_applicable": len(rows) == 0,
        }
    return summary


def _finalization_reasons(tasks: Sequence[Mapping[str, object]]) -> List[str]:
    reasons = []
    by_type: Dict[str, Counter] = {}
    for task in tasks:
        status = str(task.get("status") or "pending")
        if status == "succeeded":
            continue
        task_type = str(task.get("task_type") or "unknown")
        by_type.setdefault(task_type, Counter())[status] += 1
    for task_type in sorted(by_type):
        detail = ", ".join(
            f"{state}={count}" for state, count in sorted(by_type[task_type].items())
        )
        reasons.append(f"{task_type}: {detail}")
    legacy_counts = Counter(
        str(task.get("task_type") or "unknown")
        for task in tasks
        if task.get("status") == "succeeded"
        and str(task.get("input_capture") or "").startswith("legacy_")
    )
    for task_type, count in sorted(legacy_counts.items()):
        reasons.append(
            f"{task_type}: legacy_input_snapshot_unverifiable={count}"
        )
    return reasons


def build_task_manifest(
    payload: Mapping[str, object],
    *,
    benchmark_path: str = "",
    prior_manifest: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Build a deterministic task inventory and a revision finalization gate."""
    tasks = (
        _semantic_tasks(payload)
        + _appeal_tasks(payload)
        + _failure_mode_tasks(payload)
        + _replay_tasks(payload)
    )
    prior_by_id = {
        str(task.get("task_id")): task
        for task in (prior_manifest or {}).get("tasks", []) or []
        if isinstance(task, dict) and task.get("task_id")
    }
    for task in tasks:
        prior = prior_by_id.get(str(task["task_id"]))
        if not prior:
            continue
        task["attempts"] = int(prior.get("attempts", 0) or 0)
        # A persisted executor result is authoritative when the source payload
        # still has only a placeholder.  Input hash equality is guaranteed by
        # the stable task ID.
        if task["status"] in {"pending", "retryable_failed"} and prior.get("status") == "succeeded":
            task["status"] = "succeeded"
            task["output_hash"] = str(prior.get("output_hash") or "")
            task["output_ref"] = str(prior.get("output_ref") or "")
            task["result_status"] = str(prior.get("result_status") or "")
            task["last_error"] = ""
        elif prior.get("status") == "running" and _lease_is_active(prior.get("lease")):
            task["status"] = "running"
            task["lease"] = copy.deepcopy(prior["lease"])
            task["lease_recoveries"] = int(prior.get("lease_recoveries", 0) or 0)
            task["last_error"] = ""
        elif prior.get("status") == "running":
            task["status"] = "retryable_failed"
            task["last_error"] = "previous worker stopped while task was running"

    snapshot_hash = benchmark_snapshot_hash(payload)
    reasons = _finalization_reasons(tasks)
    report_state = "finalized" if not reasons else "provisional"
    revision_basis = {
        "schema": REVISION_SCHEMA,
        "dut": str(payload.get("dut") or ""),
        "source_snapshot_hash": snapshot_hash,
        "task_outputs": [
            {
                "task_id": task["task_id"],
                "status": task["status"],
                "output_hash": task.get("output_hash", ""),
            }
            for task in sorted(tasks, key=lambda item: str(item["task_id"]))
        ],
    }
    revision_id = "rev-" + stable_hash(revision_basis)[:20]
    revision = {
        "schema": REVISION_SCHEMA,
        "revision_id": revision_id,
        "dut": str(payload.get("dut") or ""),
        "report_state": report_state,
        "can_enter_overall_score": report_state == "finalized",
        "source_snapshot_hash": snapshot_hash,
        "finalization_reasons": reasons,
        "stage_summary": _stage_summary(tasks),
        "task_revision_scope_ids": sorted({
            str(task.get("revision_scope_id"))
            for task in tasks
            if task.get("revision_scope_id")
        }),
    }
    return {
        "schema": TASK_SCHEMA,
        "generated_at": utc_now(),
        "benchmark_path": benchmark_path,
        "prepared_source_snapshot_hash": snapshot_hash,
        "source_snapshot_hash": snapshot_hash,
        "revision": revision,
        "tasks": tasks,
    }


def materialize_task_workspace(
    payload: Mapping[str, object],
    manifest: Dict[str, object],
    workspace: Path,
) -> Dict[str, object]:
    """Write replay inputs/results as sidecars and keep the manifest compact."""
    contracts = {
        str((contract.get("input") or {}).get("candidate_id") or ""): contract
        for contract in payload.get("replay_runner_contracts", []) or []
        if isinstance(contract, dict) and isinstance(contract.get("input"), dict)
    }
    replay_results = _candidate_replay_results(payload)
    for task in manifest.get("tasks", []) or []:
        if not isinstance(task, dict) or task.get("task_type") != "replay":
            continue
        candidate_id = str(task.get("candidate_id") or "")
        contract = contracts.get(candidate_id)
        if contract is None:
            continue
        task_dir = workspace / "tasks" / str(task["task_id"])
        input_path = task_dir / "input.json"
        atomic_write_json(input_path, {"replay_runner_contract": contract})
        task["input_ref"] = input_path.relative_to(workspace).as_posix()
        result = replay_results.get(candidate_id)
        if result is None:
            placeholder = contract.get("current_placeholder_result")
            if isinstance(placeholder, dict) and _replay_task_status(placeholder) == "succeeded":
                result = placeholder
        if result is not None and _replay_task_status(result) == "succeeded":
            output_path = task_dir / "output.json"
            if not output_path.exists():
                atomic_write_json(output_path, {"candidate_id": candidate_id, "result": result})
            task["output_ref"] = output_path.relative_to(workspace).as_posix()
    atomic_write_json(workspace / "task_manifest.json", manifest)
    atomic_write_json(workspace / "revision.json", manifest["revision"])
    return manifest


def summarize_manifest(manifest: Mapping[str, object]) -> Dict[str, object]:
    tasks = [task for task in manifest.get("tasks", []) or [] if isinstance(task, dict)]
    return {
        "schema": manifest.get("schema"),
        "revision": manifest.get("revision", {}),
        "task_count": len(tasks),
        "status_counts": dict(sorted(Counter(str(task.get("status") or "pending") for task in tasks).items())),
        "task_type_counts": dict(sorted(Counter(str(task.get("task_type") or "unknown") for task in tasks).items())),
        "resumable_pending": sum(
            task.get("resumable") is True
            and task.get("status") in {"pending", "retryable_failed"}
            for task in tasks
        ),
        "readiness": summarize_task_readiness(tasks),
    }


def refresh_manifest_revision(manifest: Mapping[str, object]) -> Dict[str, object]:
    """Recompute only derived revision/finalization fields from current tasks."""
    refreshed = copy.deepcopy(dict(manifest))
    tasks = [item for item in refreshed.get("tasks", []) or [] if isinstance(item, dict)]
    reasons = _finalization_reasons(tasks)
    source_hash = str(
        refreshed.get("prepared_source_snapshot_hash")
        or refreshed.get("source_snapshot_hash") or ""
    )
    prior_revision = refreshed.get("revision")
    prior_revision = prior_revision if isinstance(prior_revision, dict) else {}
    revision_basis = {
        "schema": REVISION_SCHEMA,
        "dut": str(prior_revision.get("dut") or ""),
        "source_snapshot_hash": source_hash,
        "task_outputs": [
            {
                "task_id": task.get("task_id"), "status": task.get("status"),
                "output_hash": task.get("output_hash", ""),
            }
            for task in sorted(tasks, key=lambda item: str(item.get("task_id") or ""))
        ],
    }
    refreshed["revision"] = {
        **prior_revision,
        "schema": REVISION_SCHEMA,
        "revision_id": "rev-" + stable_hash(revision_basis)[:20],
        "report_state": "finalized" if not reasons else "provisional",
        "can_enter_overall_score": not reasons,
        "source_snapshot_hash": source_hash,
        "finalization_reasons": reasons,
        "stage_summary": _stage_summary(tasks),
    }
    refreshed["source_snapshot_hash"] = source_hash
    refreshed["generated_at"] = utc_now()
    return refreshed
