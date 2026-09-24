"""Durable per-item storage for independent reported-root alignment review."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, Mapping, Optional

from .durable_task_store import DurableTaskFiles
from .reported_root_alignment_review import MATCH_STATES, build_alignment_review_prompt
from .task_manifest import stable_hash
from .task_revision_scope import normalize_revision_scope, ownership_fields
from .task_resources import llm_resource_profile


SCHEMA = "reported_root_alignment_task.v1"
_RESOLUTIONS = {
    "accepted_llm_alignment",
    "rejected_hard_rule_conflict",
    "ignored_rule_already_confirmed",
    "rejected_schema_or_citation",
    "rejected_llm_conflict",
    "insufficient_or_low_confidence",
}


def _runtime_identity(config: Mapping[str, object]) -> Dict[str, object]:
    """Return only LLM properties that can change an alignment judgement.

    Timeout, SDK retry and pool settings affect how a request is executed, not
    what the reviewer is asked to judge.  They must remain available in the
    runtime/resource metadata, but must not split the durable decision cache.
    Profile names are intentionally excluded as aliases may be renamed while
    still resolving to the same provider/model endpoint.
    """
    if not isinstance(config, Mapping):
        return {}
    return {
        key: config.get(key)
        for key in (
            "provider", "backend", "model", "base_url",
        )
        if config.get(key) not in {None, ""}
    }


def _semantic_revision_scope(scope: Mapping[str, object]) -> Dict[str, object]:
    """Keep immutable DUT input ownership, excluding derived revision IDs."""
    if not scope:
        return {}
    return {
        key: scope[key]
        for key in ("schema", "dut", "revision_scope_id", "source_snapshot_hash")
        if key in scope
    }


def _same_semantic_task(
    candidate: Mapping[str, object], current: Mapping[str, object],
) -> bool:
    """Match legacy task inputs while deliberately ignoring execution tuning."""
    required_fields = (
        "schema", "dut", "item_id", "input_snapshot_hash", "prompt_hash",
        "revision_scope_id", "source_snapshot_hash",
    )
    if any(candidate.get(key) != current.get(key) for key in required_fields):
        return False
    return _runtime_identity(candidate.get("runtime", {})) == _runtime_identity(
        current.get("runtime", {})
    )


def build_reported_root_alignment_task_input(
    dut: str,
    item: Mapping[str, object],
    runtime_config: Mapping[str, object],
    revision_scope: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    snapshot = copy.deepcopy(dict(item))
    messages = build_alignment_review_prompt(snapshot)
    input_snapshot_hash = stable_hash(snapshot)
    prompt_hash = stable_hash(messages)
    scope = normalize_revision_scope(dut, runtime_config, revision_scope)
    resource_profile = llm_resource_profile(runtime_config)
    # `resource_profile` is deliberately outside identity.  Its configured
    # concurrency limit is operational metadata, not part of a judgement.
    identity = {
        "schema": SCHEMA,
        "identity_version": "reported_root_alignment_identity.v2",
        "dut": str(dut),
        "item_id": str(snapshot.get("item_id") or ""),
        "input_snapshot_hash": input_snapshot_hash,
        "prompt_hash": prompt_hash,
        "runtime": _runtime_identity(runtime_config),
    }
    if scope:
        identity["revision_scope"] = _semantic_revision_scope(scope)
    ownership = ownership_fields(scope)
    return {
        **identity,
        # Keep the immutable source scope in `revision_scope`; the final
        # benchmark revision remains diagnostic-only and must not make the
        # same task ID appear to have changed input in place.
        "revision_scope_id": ownership.get("revision_scope_id", ""),
        "source_snapshot_hash": ownership.get("source_snapshot_hash", ""),
        "revision_id": ownership.get("revision_id", ""),
        "resource_profile": resource_profile,
        "task_id": "reported_root_alignment-" + stable_hash(identity)[:24],
        "input_snapshot": snapshot,
        "messages": messages,
    }


def _valid_decision(decision: object, task_input: Mapping[str, object]) -> bool:
    if not isinstance(decision, dict) or decision.get("schema_valid") is not True:
        return False
    if str(decision.get("item_id") or "") != str(task_input.get("item_id") or ""):
        return False
    if decision.get("resolution") not in _RESOLUTIONS:
        return False
    if not all(
        decision.get(field) in MATCH_STATES
        for field in (
            "ck_bg_match", "symptom_match", "rtl_cause_match", "attribution_chain_match",
        )
    ):
        return False
    item = task_input.get("input_snapshot", {})
    item = item if isinstance(item, dict) else {}
    selected = decision.get("selected_gt_id")
    candidate_ids = {
        str(candidate.get("gt_id"))
        for candidate in item.get("candidate_gt", []) or []
        if isinstance(candidate, dict)
    }
    if selected is not None and str(selected) not in candidate_ids:
        return False
    citations = decision.get("citations_used")
    if not isinstance(citations, list) or not all(isinstance(value, str) for value in citations):
        return False
    if set(citations) - set(item.get("allowed_citation_ids", []) or []):
        return False
    try:
        confidence = float(decision.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return (
        0.0 <= confidence <= 1.0
        and decision.get("input_snapshot_hash") == task_input.get("input_snapshot_hash")
        and decision.get("prompt_hash") == task_input.get("prompt_hash")
    )


class ReportedRootAlignmentTaskStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._files = DurableTaskFiles(self.root, SCHEMA)

    def prepare(
        self,
        dut: str,
        item: Mapping[str, object],
        runtime_config: Mapping[str, object],
        revision_scope: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        task_input = build_reported_root_alignment_task_input(
            dut, item, runtime_config, revision_scope,
        )
        self._files.prepare(task_input)
        return task_input

    def load_success(self, task_input: Mapping[str, object]) -> Optional[Dict[str, object]]:
        output = self._files.load_succeeded_output(task_input)
        if output is not None:
            decision = output.get("alignment_decision")
            if _valid_decision(decision, task_input):
                return copy.deepcopy(decision)
        return self._load_compatible_legacy_success(task_input)

    def _load_compatible_legacy_success(
        self, task_input: Mapping[str, object],
    ) -> Optional[Dict[str, object]]:
        """Reuse a v1 cache entry created before execution tuning was excluded.

        Old entries are never mutated.  A legacy output remains usable only if
        its immutable reviewer input and effective LLM identity match exactly,
        and its decision passes the current strict validation against the new
        task input.
        """
        tasks_root = self.root / "tasks"
        if not tasks_root.is_dir():
            return None
        current_id = str(task_input.get("task_id") or "")
        for input_path in sorted(tasks_root.glob("*/input.json")):
            try:
                candidate = self._files.read_json(input_path)
            except (OSError, ValueError):
                continue
            if str(candidate.get("task_id") or "") == current_id:
                continue
            if not _same_semantic_task(candidate, task_input):
                continue
            task_dir = input_path.parent
            try:
                state = self._files.read_json(task_dir / "state.json")
                if state.get("status") != "succeeded":
                    continue
                output = self._files.read_json(task_dir / "output.json")
            except (OSError, ValueError):
                continue
            if state.get("output_hash") != stable_hash(output):
                continue
            decision = output.get("alignment_decision")
            if _valid_decision(decision, task_input):
                return copy.deepcopy(decision)
        return None

    def mark_running(self, task_input: Mapping[str, object]) -> None:
        self._files.mark_running(task_input)

    def try_claim(self, task_input: Mapping[str, object], **kwargs) -> Optional[str]:
        return self._files.try_claim(task_input, **kwargs)

    def renew_claim(self, task_input: Mapping[str, object], lease_token: str, **kwargs) -> None:
        self._files.renew_claim(task_input, lease_token, **kwargs)

    def save_success(
        self,
        task_input: Mapping[str, object],
        decision: Mapping[str, object],
        *,
        lease_token: str = "",
    ) -> None:
        decision_copy = copy.deepcopy(dict(decision))
        if not _valid_decision(decision_copy, task_input):
            raise ValueError(f"refusing invalid reported-root decision: {task_input['task_id']}")
        self._files.save_output(
            task_input, {"alignment_decision": decision_copy}, lease_token=lease_token,
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

    def requeue_external_permanent_failure(self, task_input: Mapping[str, object]) -> bool:
        return self._files.requeue_external_permanent_failure(
            task_input,
            error_tokens=(
                "insufficient balance", "error code: 402", "error code: 429",
                "timeout", "timed out", "connection", "service unavailable",
                "error code: 500", "error code: 502", "error code: 503",
                "error code: 504", "too busy",
            ),
        )
