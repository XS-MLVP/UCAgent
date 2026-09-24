"""Immutable pre-execution ownership for durable task caches.

Final benchmark revision IDs depend on task outputs, so tasks cannot safely
claim a final revision before they run.  A revision scope instead identifies
the immutable DUT inputs.  Stages operating on an already-finalized payload
may additionally attach the real revision ID.
"""
from __future__ import annotations

import copy
from typing import Dict, Mapping, Optional

from .task_manifest import stable_hash


SCHEMA = "benchmark_task_revision_scope.v1"


def build_revision_scope(
    dut: str,
    source_snapshot: object = None,
    *,
    source_snapshot_hash: str = "",
    revision_id: str = "",
) -> Dict[str, object]:
    resolved_snapshot_hash = str(source_snapshot_hash or stable_hash(source_snapshot))
    identity = {
        "schema": SCHEMA,
        "dut": str(dut),
        "source_snapshot_hash": resolved_snapshot_hash,
    }
    return {
        **identity,
        "revision_scope_id": "scope-" + stable_hash(identity)[:20],
        "revision_id": str(revision_id or ""),
    }


def normalize_revision_scope(
    dut: str,
    runtime_config: Optional[Mapping[str, object]] = None,
    explicit: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    raw = explicit
    if raw is None and isinstance(runtime_config, Mapping):
        candidate = runtime_config.get("task_revision_scope")
        raw = candidate if isinstance(candidate, Mapping) else None
    if not isinstance(raw, Mapping):
        return {}
    scope = copy.deepcopy(dict(raw))
    if scope.get("schema") != SCHEMA:
        raise ValueError("unsupported durable task revision scope schema")
    scope_dut = str(scope.get("dut") or "")
    if scope_dut and dut and scope_dut != str(dut):
        raise ValueError(f"task revision scope DUT mismatch: {scope_dut} != {dut}")
    if not scope.get("revision_scope_id") or not scope.get("source_snapshot_hash"):
        raise ValueError("task revision scope requires scope ID and source snapshot hash")
    return {
        "schema": SCHEMA,
        "dut": scope_dut or str(dut),
        "revision_scope_id": str(scope["revision_scope_id"]),
        "source_snapshot_hash": str(scope["source_snapshot_hash"]),
        "revision_id": str(scope.get("revision_id") or ""),
    }


def ownership_fields(scope: Mapping[str, object]) -> Dict[str, object]:
    if not scope:
        return {}
    return {
        "revision_scope": copy.deepcopy(dict(scope)),
        "revision_scope_id": str(scope.get("revision_scope_id") or ""),
        "source_snapshot_hash": str(scope.get("source_snapshot_hash") or ""),
        "revision_id": str(scope.get("revision_id") or ""),
    }
