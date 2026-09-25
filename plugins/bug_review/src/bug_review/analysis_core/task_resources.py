"""Credential-free resource identities and bounded task attempt metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional
from urllib.parse import urlparse

from .task_manifest import stable_hash


PROFILE_SCHEMA = "benchmark_task_resource_profile.v1"
OBSERVATION_SCHEMA = "benchmark_task_attempt_observation.v1"
MAX_ATTEMPT_HISTORY = 50


def llm_resource_profile(config: Mapping[str, object]) -> Dict[str, object]:
    provider = str(config.get("provider") or "unknown").strip().lower()
    profile = str(config.get("active_profile") or "").strip()
    model = str(config.get("model") or "unknown").strip()
    endpoint_host = urlparse(str(config.get("base_url") or "")).hostname or "default"
    identity = {
        "resource_class": "llm_network",
        "provider": provider,
        "profile": profile,
        "model": model,
        "endpoint_host": endpoint_host.lower(),
    }
    try:
        configured_limit = max(1, int(config.get("resource_pool_limit") or 10))
    except (TypeError, ValueError):
        configured_limit = 10
    return {
        "schema": PROFILE_SCHEMA,
        **identity,
        "pool_key": "llm-" + stable_hash(identity)[:16],
        "configured_limit": configured_limit,
    }


def replay_resource_profile(
    *,
    execution_mode: str,
    target_arch: str,
    runtime_root: str = "",
    runtime_profile: Optional[Mapping[str, object]] = None,
    qemu_binary: str = "",
    target_python: str = "",
    sysroot: str = "",
    configured_limit: int = 1,
) -> Dict[str, object]:
    profile = dict(runtime_profile or {})
    runtime_identity = {
        "runtime_root": str(runtime_root or profile.get("runtime_root") or ""),
        "python_executable": str(profile.get("python_executable") or target_python or ""),
        "qemu_binary": str(qemu_binary or profile.get("qemu_binary") or ""),
        "sysroot": str(sysroot or profile.get("sysroot") or ""),
    }
    identity = {
        "resource_class": "replay_runtime",
        "execution_mode": str(execution_mode or "auto"),
        "target_arch": str(target_arch or "auto"),
        "runtime_fingerprint": stable_hash(runtime_identity)[:16],
        # Basenames aid diagnostics without persisting absolute machine paths.
        "python_name": Path(runtime_identity["python_executable"]).name,
        "qemu_name": Path(runtime_identity["qemu_binary"]).name,
    }
    return {
        "schema": PROFILE_SCHEMA,
        **identity,
        "pool_key": "replay-" + stable_hash(identity)[:16],
        "configured_limit": max(1, int(configured_limit or 1)),
    }


def classify_task_error(error: BaseException) -> Dict[str, object]:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        code = None
    text = f"{type(error).__name__}: {error}".lower()
    if not isinstance(error, Exception):
        category = "interrupted"
    elif getattr(error, "retryable_task_claim", False):
        category = "task_claim_contention"
    elif type(error).__name__ == "TaskLeaseLost":
        category = "task_lease_lost"
    elif code == 402 or "insufficient balance" in text:
        category = "payment_required"
    elif code in {401, 403}:
        category = "authentication_or_permission"
    elif code == 429 or "rate limit" in text:
        category = "rate_limited"
    elif code in {408, 504} or "timeout" in text or "timed out" in text:
        category = "timeout"
    elif code in {500, 502, 503} or "service unavailable" in text or "too busy" in text:
        category = "upstream_unavailable"
    elif "connection" in text or "network" in text or "dns" in text:
        category = "connection_error"
    elif any(token in text for token in ("schema", "citation", "jsondecode", "invalid response")):
        category = "response_validation"
    elif any(token in text for token in ("runtime root", "sysroot", "qemu", "infrastructure")):
        category = "runtime_infrastructure"
    else:
        category = "unknown_error"
    return {
        "error_category": category,
        "error_type": type(error).__name__,
        "status_code": code,
    }


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


def build_attempt_observation(
    lease: Mapping[str, object],
    outcome: str,
    *,
    error: Optional[BaseException] = None,
    finished_at: Optional[datetime] = None,
) -> Dict[str, object]:
    finished = finished_at or datetime.now(timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    finished = finished.astimezone(timezone.utc)
    started = _parse_time(lease.get("acquired_at"))
    duration = max(0.0, (finished - started).total_seconds()) if started else None
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "outcome": str(outcome),
        "started_at": str(lease.get("acquired_at") or ""),
        "finished_at": finished.isoformat(),
        "duration_seconds": round(duration, 6) if duration is not None else None,
        "worker_id": str(lease.get("worker_id") or ""),
    }
    if error is not None:
        observation.update(classify_task_error(error))
    return observation


def append_attempt_observation(
    state: Mapping[str, object], observation: Mapping[str, object],
) -> list:
    history = [
        dict(item) for item in state.get("attempt_history", []) or []
        if isinstance(item, dict)
    ]
    history.append(dict(observation))
    return history[-MAX_ATTEMPT_HISTORY:]
