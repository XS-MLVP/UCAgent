"""Shared atomic sidecar mechanics for local durable tasks.

This module deliberately knows nothing about semantic schemas, failure modes,
or clustering.  Callers own task identity and output validation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import socket
import threading
from typing import Dict, Iterator, Mapping, Optional
import uuid

from .task_manifest import atomic_write_json, stable_hash, utc_now
from .task_resources import append_attempt_observation, build_attempt_observation


class TaskClaimUnavailable(RuntimeError):
    """Another live worker currently owns the task lease."""

    retryable_task_claim = True


class TaskLeaseLost(RuntimeError):
    """A worker attempted to checkpoint after its lease was lost or expired."""


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


class DurableTaskFiles:
    def __init__(self, root: Path, schema: str):
        self.root = Path(root)
        self.schema = schema

    def task_dir(self, task_input: Mapping[str, object]) -> Path:
        return self.root / "tasks" / str(task_input["task_id"])

    @contextmanager
    def _state_lock(self, task_dir: Path) -> Iterator[None]:
        task_dir.mkdir(parents=True, exist_ok=True)
        lock_path = task_dir / "state.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def prepare(self, task_input: Mapping[str, object]) -> None:
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            input_path = task_dir / "input.json"
            if input_path.exists():
                existing = self.read_json(input_path)
                if stable_hash(existing) != stable_hash(task_input):
                    raise ValueError(f"durable task input changed in place: {task_input['task_id']}")
            else:
                atomic_write_json(input_path, task_input)
            state_path = task_dir / "state.json"
            if not state_path.exists():
                atomic_write_json(state_path, {
                    "schema": self.schema,
                    "task_id": task_input["task_id"],
                    "status": "pending",
                    "attempts": 0,
                    "last_error": "",
                    "updated_at": utc_now(),
                })

    def load_succeeded_output(
        self, task_input: Mapping[str, object],
    ) -> Optional[Dict[str, object]]:
        task_dir = self.task_dir(task_input)
        state = self.read_json(task_dir / "state.json")
        if state.get("status") != "succeeded":
            return None
        output = self.read_json(task_dir / "output.json")
        if state.get("output_hash") != stable_hash(output):
            return None
        return output

    def mark_running(self, task_input: Mapping[str, object]) -> None:
        """Legacy single-worker transition; new executors should use try_claim."""
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            if isinstance(state.get("lease"), dict):
                raise TaskClaimUnavailable(f"task already leased: {task_input['task_id']}")
            atomic_write_json(state_path, {
                **state,
                "schema": self.schema,
                "task_id": task_input["task_id"],
                "status": "running",
                "attempts": int(state.get("attempts", 0) or 0) + 1,
                "last_error": "",
                "updated_at": utc_now(),
            })

    def try_claim(
        self,
        task_input: Mapping[str, object],
        *,
        worker_id: str = "",
        lease_seconds: int = 900,
        now: Optional[datetime] = None,
    ) -> Optional[str]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            status = str(state.get("status") or "pending")
            # permanently_failed means the prior invocation exhausted its
            # policy; an explicit later workflow invocation may still retry.
            if status in {"succeeded", "cancelled", "superseded"}:
                return None
            lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
            expires_at = _parse_time(lease.get("expires_at"))
            if lease and expires_at is not None and expires_at > current:
                return None
            recovered = bool(lease) or status == "running"
            token = uuid.uuid4().hex
            worker = worker_id or default_worker_id()
            acquired_at = current.isoformat()
            resource_profile = (
                dict(task_input.get("resource_profile"))
                if isinstance(task_input.get("resource_profile"), dict) else {}
            )
            updated_state = {
                **state,
                "schema": self.schema,
                "task_id": task_input["task_id"],
                "status": "running",
                "attempts": int(state.get("attempts", 0) or 0) + 1,
                "lease_recoveries": int(state.get("lease_recoveries", 0) or 0) + (1 if recovered else 0),
                "last_error": "",
                "lease": {
                    "worker_id": worker,
                    "token": token,
                    "acquired_at": acquired_at,
                    "renewed_at": acquired_at,
                    "expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
                },
                "updated_at": acquired_at,
            }
            if resource_profile:
                updated_state["resource_profile"] = resource_profile
            atomic_write_json(state_path, updated_state)
            return token

    def renew_claim(
        self,
        task_input: Mapping[str, object],
        lease_token: str,
        *,
        lease_seconds: int = 900,
        now: Optional[datetime] = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            lease = self._require_lease(state, lease_token, current)
            atomic_write_json(state_path, {
                **state,
                "lease": {
                    **lease,
                    "renewed_at": current.isoformat(),
                    "expires_at": (current + timedelta(seconds=lease_seconds)).isoformat(),
                },
                "updated_at": current.isoformat(),
            })

    @staticmethod
    def _require_lease(
        state: Mapping[str, object], lease_token: str, current: datetime,
    ) -> Dict[str, object]:
        lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
        if not lease_token or lease.get("token") != lease_token:
            raise TaskLeaseLost("task lease token no longer owns this task")
        expires_at = _parse_time(lease.get("expires_at"))
        if expires_at is None or expires_at <= current:
            raise TaskLeaseLost("task lease expired before checkpoint")
        return dict(lease)

    def save_output(
        self,
        task_input: Mapping[str, object],
        output: Mapping[str, object],
        *,
        lease_token: str = "",
    ) -> None:
        output_copy = dict(output)
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
            if lease_token:
                lease = self._require_lease(state, lease_token, datetime.now(timezone.utc))
            elif lease:
                raise TaskLeaseLost("lease token required to save claimed task")
            atomic_write_json(task_dir / "output.json", output_copy)
            updated = {
                **state,
                "schema": self.schema,
                "task_id": task_input["task_id"],
                "status": "succeeded",
                "output_hash": stable_hash(output_copy),
                "last_error": "",
                "updated_at": utc_now(),
            }
            updated.pop("lease", None)
            if lease:
                updated["attempt_history"] = append_attempt_observation(
                    state, build_attempt_observation(lease, "succeeded"),
                )
            atomic_write_json(state_path, updated)

    def save_failure(
        self,
        task_input: Mapping[str, object],
        error: BaseException,
        status: str,
        *,
        lease_token: str = "",
    ) -> None:
        if status not in {"retryable_failed", "permanently_failed"}:
            raise ValueError(f"invalid durable task failure status: {status}")
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
            if lease_token:
                lease = self._require_lease(state, lease_token, datetime.now(timezone.utc))
            elif lease:
                raise TaskLeaseLost("lease token required to fail claimed task")
            updated = {
                **state,
                "schema": self.schema,
                "task_id": task_input["task_id"],
                "status": status,
                "last_error": f"{type(error).__name__}: {error}",
                "updated_at": utc_now(),
            }
            updated.pop("lease", None)
            if lease:
                updated["attempt_history"] = append_attempt_observation(
                    state,
                    build_attempt_observation(lease, status, error=error),
                )
            atomic_write_json(state_path, updated)

    def requeue_external_permanent_failure(
        self,
        task_input: Mapping[str, object],
        *,
        error_tokens,
    ) -> bool:
        """Requeue only allowlisted provider/infrastructure terminal errors."""
        task_dir = self.task_dir(task_input)
        with self._state_lock(task_dir):
            state_path = task_dir / "state.json"
            state = self.read_json(state_path)
            if state.get("status") != "permanently_failed":
                return False
            error = str(state.get("last_error") or "").lower()
            if not any(str(token).lower() in error for token in error_tokens):
                return False
            updated = {
                **state,
                "status": "retryable_failed",
                "requeue_count": int(state.get("requeue_count", 0) or 0) + 1,
                "requeue_reason": "allowlisted_external_failure",
                "updated_at": utc_now(),
            }
            updated.pop("lease", None)
            atomic_write_json(state_path, updated)
            return True

    @staticmethod
    def read_json(path: Path) -> Dict[str, object]:
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
