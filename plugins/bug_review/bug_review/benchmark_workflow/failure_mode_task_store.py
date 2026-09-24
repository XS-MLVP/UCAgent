"""Durable record-level storage for RTL failure-mode consensus reviews.

One task contains the complete two-vote/optional tie-break result for one
benchmark record.  Voting policy and LLM execution remain in
``rtl_root_clustering``; this module owns only frozen input and atomic state.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, Mapping, Optional

from .semantic_judge import FAILURE_MODES, build_failure_mode_prompt
from .durable_task_store import DurableTaskFiles
from .task_manifest import stable_hash
from .task_revision_scope import normalize_revision_scope, ownership_fields
from .task_resources import llm_resource_profile


SCHEMA = "failure_mode_review_task.v1"
_CONSENSUS_STATES = {"unanimous", "majority", "no_consensus"}


def _runtime_identity(config: Mapping[str, object]) -> Dict[str, object]:
    identity = {
        key: config.get(key)
        for key in ("provider", "backend", "model", "base_url")
        if config.get(key) not in {None, ""}
    }
    if config.get("request_timeout_seconds") not in {None, ""}:
        identity["request_timeout_seconds"] = float(config["request_timeout_seconds"])
    if config.get("sdk_max_retries") not in {None, ""}:
        identity["sdk_max_retries"] = int(config["sdk_max_retries"])
    return identity


def build_failure_mode_task_input(
    record: Mapping[str, object],
    runtime_config: Mapping[str, object],
    revision_scope: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    snapshot = copy.deepcopy(dict(record))
    messages = build_failure_mode_prompt(snapshot)
    input_snapshot_hash = stable_hash(snapshot)
    prompt_hash = stable_hash(messages)
    scope = normalize_revision_scope(
        str(snapshot.get("dut") or ""), runtime_config, revision_scope,
    )
    resource_profile = llm_resource_profile(runtime_config)
    identity = {
        "schema": SCHEMA,
        "dut": str(snapshot.get("dut") or ""),
        "canonical_bug": str(snapshot.get("canonical_bug") or ""),
        "record_model": str(snapshot.get("model") or ""),
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
        "task_id": "failure_mode_review-" + stable_hash(identity)[:24],
        "input_snapshot": snapshot,
        "messages": messages,
    }


def _valid_review(review: object, task_input: Mapping[str, object]) -> bool:
    if not isinstance(review, dict):
        return False
    if str(review.get("canonical_bug") or "") != str(task_input.get("canonical_bug") or ""):
        return False
    if str(review.get("model") or "") != str(task_input.get("record_model") or ""):
        return False
    if review.get("failure_mode") not in FAILURE_MODES:
        return False
    if review.get("consensus_status") not in _CONSENSUS_STATES:
        return False
    vote_modes = review.get("vote_modes")
    votes = review.get("votes")
    if not isinstance(vote_modes, list) or len(vote_modes) not in {2, 3}:
        return False
    if not all(mode in FAILURE_MODES for mode in vote_modes):
        return False
    if not isinstance(votes, list) or len(votes) != len(vote_modes):
        return False
    if not all(isinstance(vote, dict) for vote in votes):
        return False
    try:
        confidence = float(review.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return (
        0.0 <= confidence <= 1.0
        and isinstance(review.get("evidence_fields"), list)
        and review.get("input_snapshot_hash") == task_input.get("input_snapshot_hash")
        and review.get("prompt_hash") == task_input.get("prompt_hash")
    )


class FailureModeTaskStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._files = DurableTaskFiles(self.root, SCHEMA)

    def prepare(
        self,
        record: Mapping[str, object],
        runtime_config: Mapping[str, object],
        revision_scope: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        task_input = build_failure_mode_task_input(
            record, runtime_config, revision_scope,
        )
        # Return a compatible historical succeeded task itself, before
        # preparing a new directory.  This prevents numeric-only runtime
        # identity migrations from creating duplicate task files.
        wanted = (
            str(task_input.get("dut") or ""), str(task_input.get("canonical_bug") or ""),
            str(task_input.get("record_model") or ""), str(task_input.get("input_snapshot_hash") or ""),
            str(task_input.get("prompt_hash") or ""), stable_hash(task_input.get("resource_profile") or {}),
        )
        tasks_root = self.root / "tasks"
        if tasks_root.is_dir():
            for input_path in tasks_root.glob("*/input.json"):
                try:
                    legacy = self._files.read_json(input_path)
                    legacy_key = (
                        str(legacy.get("dut") or ""), str(legacy.get("canonical_bug") or ""),
                        str(legacy.get("record_model") or ""), str(legacy.get("input_snapshot_hash") or ""),
                        str(legacy.get("prompt_hash") or ""), stable_hash(legacy.get("resource_profile") or {}),
                    )
                    if legacy_key != wanted:
                        continue
                    output = self._files.load_succeeded_output(legacy)
                    review = output.get("failure_mode_review") if output else None
                    if _valid_review(review, task_input):
                        return legacy
                except (OSError, ValueError, TypeError):
                    continue
        self._files.prepare(task_input)
        return task_input

    def load_success(self, task_input: Mapping[str, object]) -> Optional[Dict[str, object]]:
        output = self._files.load_succeeded_output(task_input)
        if output is not None:
            review = output.get("failure_mode_review")
            if _valid_review(review, task_input):
                return copy.deepcopy(review)

        # Compatibility for task stores created before runtime numeric values
        # were canonicalised (e.g. 120 versus 120.0).  The prompt and frozen
        # record hashes are the real semantic identity; additionally require
        # DUT/model/bug and the credential-free resource profile to match.
        # This only reads a *succeeded and schema-valid* historical output,
        # never aliases pending/failed work or a different prompt.
        wanted = (
            str(task_input.get("dut") or ""),
            str(task_input.get("canonical_bug") or ""),
            str(task_input.get("record_model") or ""),
            str(task_input.get("input_snapshot_hash") or ""),
            str(task_input.get("prompt_hash") or ""),
            stable_hash(task_input.get("resource_profile") or {}),
        )
        tasks_root = self.root / "tasks"
        if not tasks_root.is_dir():
            return None
        for input_path in tasks_root.glob("*/input.json"):
            try:
                legacy_input = self._files.read_json(input_path)
                legacy_key = (
                    str(legacy_input.get("dut") or ""),
                    str(legacy_input.get("canonical_bug") or ""),
                    str(legacy_input.get("record_model") or ""),
                    str(legacy_input.get("input_snapshot_hash") or ""),
                    str(legacy_input.get("prompt_hash") or ""),
                    stable_hash(legacy_input.get("resource_profile") or {}),
                )
                if legacy_key != wanted:
                    continue
                output = self._files.load_succeeded_output(legacy_input)
                review = output.get("failure_mode_review") if output else None
                if _valid_review(review, task_input):
                    return copy.deepcopy(review)
            except (OSError, ValueError, TypeError):
                continue
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
        review: Mapping[str, object],
        *,
        lease_token: str = "",
    ) -> None:
        review_copy = copy.deepcopy(dict(review))
        if not _valid_review(review_copy, task_input):
            raise ValueError(f"refusing invalid failure-mode output: {task_input['task_id']}")
        self._files.save_output(
            task_input, {"failure_mode_review": review_copy}, lease_token=lease_token,
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
