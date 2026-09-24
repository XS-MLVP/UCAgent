"""Durable per-pair storage for constrained RTL-root appeals."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .durable_task_store import DurableTaskFiles
from .semantic_judge import (
    APPEAL_EVIDENCE_LINKS,
    SEMANTIC_RELATIONS,
    build_semantic_appeal_prompt,
)
from .task_manifest import stable_hash
from .task_revision_scope import normalize_revision_scope, ownership_fields
from .task_resources import llm_resource_profile


SCHEMA = "rtl_root_appeal_task.v1"


def _runtime_identity(config: Mapping[str, object]) -> Dict[str, object]:
    return {
        key: config.get(key)
        for key in (
            "provider", "backend", "model", "base_url",
            "request_timeout_seconds", "sdk_max_retries",
        )
        if config.get(key) not in {None, ""}
    }


def _ordered_inputs(
    item: Mapping[str, object],
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    left_key = (
        str(item.get("left_canonical_bug") or ""),
        str(item.get("left_model") or ""),
    )
    right_key = (
        str(item.get("right_canonical_bug") or ""),
        str(item.get("right_model") or ""),
    )
    if left_key <= right_key:
        return copy.deepcopy(dict(item)), copy.deepcopy(dict(left)), copy.deepcopy(dict(right))
    normalized_item = copy.deepcopy(dict(item))
    for field in ("canonical_bug", "model", "signature"):
        left_field = f"left_{field}"
        right_field = f"right_{field}"
        normalized_item[left_field], normalized_item[right_field] = (
            normalized_item.get(right_field), normalized_item.get(left_field),
        )
    return normalized_item, copy.deepcopy(dict(right)), copy.deepcopy(dict(left))


def build_rtl_root_appeal_task_input(
    item: Mapping[str, object],
    left: Mapping[str, object],
    right: Mapping[str, object],
    runtime_config: Mapping[str, object],
    revision_scope: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    normalized_item, ordered_left, ordered_right = _ordered_inputs(item, left, right)
    messages = build_semantic_appeal_prompt(
        ordered_left, ordered_right, "insufficient evidence", 0,
    )
    snapshot = {
        "review_item": normalized_item,
        "left": ordered_left,
        "right": ordered_right,
        "base_relation": "insufficient evidence",
        "base_score": 0,
    }
    input_snapshot_hash = stable_hash(snapshot)
    prompt_hash = stable_hash(messages)
    scope = normalize_revision_scope(
        str(normalized_item.get("dut") or ordered_left.get("dut") or ""),
        runtime_config,
        revision_scope,
    )
    resource_profile = llm_resource_profile(runtime_config)
    identity = {
        "schema": SCHEMA,
        "dut": str(normalized_item.get("dut") or ordered_left.get("dut") or ""),
        "left_canonical_bug": str(normalized_item.get("left_canonical_bug") or ""),
        "right_canonical_bug": str(normalized_item.get("right_canonical_bug") or ""),
        "left_model": str(normalized_item.get("left_model") or ""),
        "right_model": str(normalized_item.get("right_model") or ""),
        "input_snapshot_hash": input_snapshot_hash,
        "prompt_hash": prompt_hash,
        "runtime": _runtime_identity(runtime_config),
        "resource_profile": resource_profile,
    }
    if scope:
        identity["revision_scope"] = scope
    return {
        **identity,
        **ownership_fields(scope),
        "task_id": "rtl_root_appeal-" + stable_hash(identity)[:24],
        "input_snapshot": snapshot,
        "messages": messages,
    }


def _valid_review(review: object, task_input: Mapping[str, object]) -> bool:
    if not isinstance(review, dict):
        return False
    for field in (
        "left_canonical_bug", "right_canonical_bug", "left_model", "right_model",
    ):
        if str(review.get(field) or "") != str(task_input.get(field) or ""):
            return False
    if review.get("relation") not in SEMANTIC_RELATIONS:
        return False
    if not isinstance(review.get("merge_supported"), bool):
        return False
    if str(review.get("merge_risk") or "") not in {"low", "medium", "high"}:
        return False
    links = review.get("evidence_links")
    if not isinstance(links, list) or not all(link in APPEAL_EVIDENCE_LINKS for link in links):
        return False
    try:
        confidence = float(review.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return (
        0.0 <= confidence <= 1.0
        and review.get("input_snapshot_hash") == task_input.get("input_snapshot_hash")
        and review.get("prompt_hash") == task_input.get("prompt_hash")
    )


class RtlRootAppealTaskStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._files = DurableTaskFiles(self.root, SCHEMA)

    def prepare(
        self,
        item: Mapping[str, object],
        left: Mapping[str, object],
        right: Mapping[str, object],
        runtime_config: Mapping[str, object],
        revision_scope: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        task_input = build_rtl_root_appeal_task_input(
            item, left, right, runtime_config, revision_scope,
        )
        self._files.prepare(task_input)
        return task_input

    def load_success(self, task_input: Mapping[str, object]) -> Optional[Dict[str, object]]:
        output = self._files.load_succeeded_output(task_input)
        if output is None:
            return None
        review = output.get("rtl_root_appeal_review")
        if not _valid_review(review, task_input):
            return None
        return copy.deepcopy(review)

    def mark_running(self, task_input: Mapping[str, object]) -> None:
        self._files.mark_running(task_input)

    def try_claim(self, task_input: Mapping[str, object], **kwargs) -> Optional[str]:
        return self._files.try_claim(task_input, **kwargs)

    def renew_claim(self, task_input: Mapping[str, object], lease_token: str, **kwargs) -> None:
        self._files.renew_claim(task_input, lease_token, **kwargs)

    def save_success(
        self,
        task_input: Mapping[str, object],
        review: Mapping[str, object],
        *,
        lease_token: str = "",
    ) -> None:
        review_copy = copy.deepcopy(dict(review))
        if not _valid_review(review_copy, task_input):
            raise ValueError(f"refusing invalid RTL-root appeal output: {task_input['task_id']}")
        self._files.save_output(
            task_input, {"rtl_root_appeal_review": review_copy}, lease_token=lease_token,
        )

    def save_permanent_failure(
        self,
        task_input: Mapping[str, object],
        error: BaseException,
        *,
        lease_token: str = "",
    ) -> None:
        self._files.save_failure(
            task_input, error, "permanently_failed", lease_token=lease_token,
        )

    def save_failure(
        self,
        task_input: Mapping[str, object],
        error: BaseException,
        *,
        lease_token: str = "",
    ) -> None:
        self._files.save_failure(
            task_input, error, "retryable_failed", lease_token=lease_token,
        )
