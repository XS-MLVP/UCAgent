"""Durable per-pair storage for semantic LLM judgements.

The store owns persistence only. Pair selection, retry policy, LLM calls and
clustering remain in the pipeline. Each task directory is immutable with
respect to its input; only the state/output sidecars change atomically.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .durable_task_store import DurableTaskFiles
from .semantic_judge import (
    SEMANTIC_RELATIONS,
    build_semantic_appeal_prompt,
    build_semantic_judge_prompt,
)
from .task_manifest import TASK_STATES, stable_hash
from .task_revision_scope import normalize_revision_scope, ownership_fields
from .task_resources import llm_resource_profile


SCHEMA = "semantic_pair_task.v1"
_MATCH_VALUES = {"match", "mismatch", "unknown"}


def _runtime_identity(config: Mapping[str, object]) -> Dict[str, object]:
    """Keep reproducibility fields without persisting credentials or tracing keys."""
    return {
        key: config.get(key)
        for key in (
            "provider", "backend", "model", "base_url",
            "request_timeout_seconds", "sdk_max_retries",
        )
        if config.get(key) not in {None, ""}
    }


def _ordered_pair(
    left: Mapping[str, object], right: Mapping[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    left_copy = copy.deepcopy(dict(left))
    right_copy = copy.deepcopy(dict(right))
    if str(left_copy.get("candidate_id") or "") <= str(right_copy.get("candidate_id") or ""):
        return left_copy, right_copy
    return right_copy, left_copy


def build_semantic_task_input(
    left: Mapping[str, object],
    right: Mapping[str, object],
    score: int,
    runtime_config: Mapping[str, object],
    revision_scope: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    ordered_left, ordered_right = _ordered_pair(left, right)
    messages = build_semantic_judge_prompt(ordered_left, ordered_right)
    appeal_messages = build_semantic_appeal_prompt(
        ordered_left, ordered_right, "same bug", int(score),
    )
    snapshot = {
        "left": ordered_left,
        "right": ordered_right,
        "score": int(score),
    }
    input_snapshot_hash = stable_hash(snapshot)
    prompt_hash = stable_hash(messages)
    appeal_prompt_hash = stable_hash(appeal_messages)
    runtime = _runtime_identity(runtime_config)
    resource_profile = llm_resource_profile(runtime_config)
    scope = normalize_revision_scope(
        str(ordered_left.get("dut") or ordered_right.get("dut") or ""),
        runtime_config,
        revision_scope,
    )
    identity = {
        "schema": SCHEMA,
        "dut": str(ordered_left.get("dut") or ordered_right.get("dut") or ""),
        "left_candidate_id": str(ordered_left.get("candidate_id") or ""),
        "right_candidate_id": str(ordered_right.get("candidate_id") or ""),
        "input_snapshot_hash": input_snapshot_hash,
        "prompt_hash": prompt_hash,
        "appeal_prompt_hash": appeal_prompt_hash,
        "runtime": runtime,
        "resource_profile": resource_profile,
    }
    if scope:
        identity["revision_scope"] = scope
    return {
        **identity,
        **ownership_fields(scope),
        "task_id": "semantic_judgement-" + stable_hash(identity)[:24],
        "input_snapshot": snapshot,
        "messages": messages,
        "appeal_messages": appeal_messages,
    }


def _valid_cached_row(row: object, task_input: Mapping[str, object]) -> bool:
    if not isinstance(row, dict):
        return False
    expected_ids = {
        str(task_input.get("left_candidate_id") or ""),
        str(task_input.get("right_candidate_id") or ""),
    }
    actual_ids = {
        str(row.get("left_candidate_id") or ""),
        str(row.get("right_candidate_id") or ""),
    }
    if expected_ids != actual_ids:
        return False
    judgement = row.get("judgement")
    if not isinstance(judgement, dict):
        return False
    # A missing flag belonged to legacy, weakly validated outputs.  Durable
    # reuse is deliberately stricter: only an explicitly schema-valid result
    # may bypass a future model call, unless explicitly degraded after retries.
    is_schema_valid = judgement.get("schema_valid") is True
    is_schema_fallback = (
        judgement.get("schema_fallback_downgraded") is True
        and judgement.get("relation") == "insufficient evidence"
    )
    if not (is_schema_valid or is_schema_fallback):
        return False
    if judgement.get("relation") not in SEMANTIC_RELATIONS:
        return False
    for field in (
        "property_match_status", "trigger_match_status",
        "expected_observed_match_status", "rtl_cause_match_status",
    ):
        value = judgement.get(field)
        if value is not None and value not in _MATCH_VALUES:
            return False
    return (
        judgement.get("input_snapshot_hash") == task_input.get("input_snapshot_hash")
        and judgement.get("prompt_hash") == task_input.get("prompt_hash")
    )


def _valid_cached_appeal(appeal: object, task_input: Mapping[str, object]) -> bool:
    if appeal is None:
        return True
    if not isinstance(appeal, dict) or not isinstance(appeal.get("appeal"), dict):
        return False
    expected_ids = {
        str(task_input.get("left_candidate_id") or ""),
        str(task_input.get("right_candidate_id") or ""),
    }
    actual_ids = {
        str(appeal.get("left_candidate_id") or ""),
        str(appeal.get("right_candidate_id") or ""),
    }
    return expected_ids == actual_ids and isinstance(appeal.get("appeal_supported"), bool)


class SemanticTaskStore:
    """Filesystem-backed task store safe for independent worker threads."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._files = DurableTaskFiles(self.root, SCHEMA)

    def _task_dir(self, task_input: Mapping[str, object]) -> Path:
        return self._files.task_dir(task_input)

    def prepare(
        self,
        left: Mapping[str, object],
        right: Mapping[str, object],
        score: int,
        runtime_config: Mapping[str, object],
        revision_scope: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        task_input = build_semantic_task_input(
            left, right, score, runtime_config, revision_scope,
        )
        self._files.prepare(task_input)
        return task_input

    def load_success(self, task_input: Mapping[str, object]) -> Optional[Dict[str, object]]:
        output = self._files.load_succeeded_output(task_input)
        if output is None:
            return None
        row = output.get("semantic_judgement")
        if not _valid_cached_row(row, task_input):
            return None
        if not _valid_cached_appeal(output.get("semantic_appeal"), task_input):
            return None
        return {
            "semantic_judgement": copy.deepcopy(row),
            "semantic_appeal": copy.deepcopy(output.get("semantic_appeal")),
        }

    def mark_running(self, task_input: Mapping[str, object]) -> None:
        self._files.mark_running(task_input)

    def try_claim(self, task_input: Mapping[str, object], **kwargs) -> Optional[str]:
        return self._files.try_claim(task_input, **kwargs)

    def renew_claim(self, task_input: Mapping[str, object], lease_token: str, **kwargs) -> None:
        self._files.renew_claim(task_input, lease_token, **kwargs)

    def save_success(
        self,
        task_input: Mapping[str, object],
        row: Mapping[str, object],
        appeal: Optional[Mapping[str, object]] = None,
        *,
        lease_token: str = "",
    ) -> None:
        row_copy = copy.deepcopy(dict(row))
        if not _valid_cached_row(row_copy, task_input):
            raise ValueError(f"refusing invalid semantic task output: {task_input['task_id']}")
        task_dir = self._task_dir(task_input)
        output = {
            "semantic_judgement": row_copy,
            "semantic_appeal": copy.deepcopy(dict(appeal)) if appeal is not None else None,
        }
        if not _valid_cached_appeal(output["semantic_appeal"], task_input):
            raise ValueError(f"refusing invalid semantic task appeal: {task_input['task_id']}")
        self._files.save_output(task_input, output, lease_token=lease_token)

    def save_failure(
        self, task_input: Mapping[str, object], error: BaseException, *, lease_token: str = "",
    ) -> None:
        self._save_failure_state(
            task_input, error, "retryable_failed", lease_token=lease_token,
        )

    def save_permanent_failure(
        self, task_input: Mapping[str, object], error: BaseException, *, lease_token: str = "",
    ) -> None:
        self._save_failure_state(
            task_input, error, "permanently_failed", lease_token=lease_token,
        )

    def _save_failure_state(
        self,
        task_input: Mapping[str, object],
        error: BaseException,
        status: str,
        *,
        lease_token: str = "",
    ) -> None:
        if status not in {"retryable_failed", "permanently_failed"}:
            raise ValueError(f"invalid semantic task failure status: {status}")
        self._files.save_failure(
            task_input, error, status, lease_token=lease_token,
        )

    def summarize(self) -> Dict[str, object]:
        """Return a read-only, evidence-light status view of this store."""
        rows = []
        tasks_root = self.root / "tasks"
        for input_path in sorted(tasks_root.glob("*/input.json")):
            try:
                task_input = self._read_json(input_path)
                state = self._read_json(input_path.parent / "state.json")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                rows.append({
                    "task_id": input_path.parent.name,
                    "status": "invalid_task_files",
                    "cache_reusable": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            raw_status = str(state.get("status") or "pending")
            effective_status = raw_status if raw_status in TASK_STATES else "invalid_state"
            cache_reusable = False
            integrity_error = ""
            if raw_status == "succeeded":
                try:
                    cache_reusable = self.load_success(task_input) is not None
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    integrity_error = f"{type(exc).__name__}: {exc}"
                if not cache_reusable:
                    effective_status = "invalid_succeeded_output"
            rows.append({
                "task_id": str(task_input.get("task_id") or input_path.parent.name),
                "dut": str(task_input.get("dut") or ""),
                "left_candidate_id": str(task_input.get("left_candidate_id") or ""),
                "right_candidate_id": str(task_input.get("right_candidate_id") or ""),
                "status": effective_status,
                "stored_status": raw_status,
                "attempts": int(state.get("attempts", 0) or 0),
                "cache_reusable": cache_reusable,
                "last_error": integrity_error or str(state.get("last_error") or ""),
            })
        counts = Counter(str(row["status"]) for row in rows)
        return {
            "schema": "semantic_pair_task_status.v1",
            "task_store_dir": str(self.root),
            "total": len(rows),
            "counts": dict(sorted(counts.items())),
            "reusable_successes": sum(bool(row.get("cache_reusable")) for row in rows),
            "tasks": rows,
        }

    @staticmethod
    def _read_json(path: Path) -> Dict[str, object]:
        return DurableTaskFiles.read_json(path)
