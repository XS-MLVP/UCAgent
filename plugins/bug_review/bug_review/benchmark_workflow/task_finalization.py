"""Single-owner completion gate for idempotent asynchronous finalizers."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
from pathlib import Path
from typing import Callable, Dict, Iterator, Mapping, Optional, Sequence
import uuid

from .task_manifest import atomic_write_json, stable_hash, utc_now


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "finalization.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    import json
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def task_batch_completion(tasks: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    required = [task for task in tasks if task.get("required_for_finalize") is not False]
    counts: Dict[str, int] = {}
    for task in required:
        status = str(task.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    blocking = [
        str(task.get("task_id") or "") for task in required
        if str(task.get("status") or "pending") != "succeeded"
    ]
    fingerprint = stable_hash([
        {
            "task_id": task.get("task_id"),
            "input_snapshot_hash": task.get("input_snapshot_hash"),
            "required_for_finalize": task.get("required_for_finalize", True),
        }
        for task in sorted(required, key=lambda row: str(row.get("task_id") or ""))
    ])
    return {
        "required_task_count": len(required),
        "status_counts": dict(sorted(counts.items())),
        "blocking_task_ids": sorted(blocking),
        "all_required_succeeded": bool(required) and not blocking,
        "batch_fingerprint": fingerprint,
    }


def finalize_if_ready(
    root: Path,
    tasks: Sequence[Mapping[str, object]],
    finalizer: Callable[[], Mapping[str, object]],
    *,
    finalizer_lease_seconds: int = 300,
) -> Dict[str, object]:
    """Run an idempotent finalizer after every required task succeeds.

    The lease prevents concurrent execution.  A process crash after the
    callback side effect but before its checkpoint can cause a later retry,
    so callers must keep the deterministic finalizer idempotent.
    """
    completion = task_batch_completion(tasks)
    if not completion["all_required_succeeded"]:
        return {"triggered": False, "status": "waiting", **completion}
    state_path = Path(root) / "finalization.json"
    current_time = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    with _lock(Path(root)):
        state = _read_json(state_path)
        if (
            state.get("status") == "finalized"
            and state.get("batch_fingerprint") == completion["batch_fingerprint"]
        ):
            return {"triggered": False, **state, **completion}
        lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
        expires = _parse_time(lease.get("expires_at"))
        if state.get("status") == "finalizing" and expires and expires > current_time:
            return {"triggered": False, "status": "finalizing", **completion}
        atomic_write_json(state_path, {
            "schema": "benchmark_task_finalization.v1",
            "status": "finalizing",
            "batch_fingerprint": completion["batch_fingerprint"],
            "required_task_count": completion["required_task_count"],
            "lease": {
                "token": token,
                "acquired_at": current_time.isoformat(),
                "expires_at": (
                    current_time + timedelta(seconds=max(1, finalizer_lease_seconds))
                ).isoformat(),
            },
            "updated_at": utc_now(),
        })
    try:
        result = dict(finalizer())
    except BaseException as exc:
        with _lock(Path(root)):
            state = _read_json(state_path)
            lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
            if lease.get("token") == token:
                atomic_write_json(state_path, {
                    **state,
                    "status": "finalize_failed",
                    "last_error": f"{type(exc).__name__}: {exc}",
                    "updated_at": utc_now(),
                })
        raise
    with _lock(Path(root)):
        state = _read_json(state_path)
        lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
        if lease.get("token") != token:
            raise RuntimeError("finalizer lease ownership changed before checkpoint")
        atomic_write_json(state_path, {
            "schema": "benchmark_task_finalization.v1",
            "status": "finalized",
            "batch_fingerprint": completion["batch_fingerprint"],
            "required_task_count": completion["required_task_count"],
            "result": result,
            "finalized_at": utc_now(),
            "updated_at": utc_now(),
        })
    return {"triggered": True, "status": "finalized", "result": result, **completion}
