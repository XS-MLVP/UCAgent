"""Process-local fixed capacity pools and conservative read-only advice."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import functools
import math
import threading
import time
from typing import Dict, Iterator, Mapping

from .task_resources import replay_resource_profile


ADVISORY_SCHEMA = "benchmark_resource_capacity_advisory.v1"


def normalize_capacity_limit(value: object, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(default))


@dataclass(frozen=True)
class PoolLease:
    pool_key: str
    configured_limit: int
    wait_seconds: float


class FixedCapacityPool:
    """A shared ceiling that may become stricter but never auto-expands."""

    def __init__(self, pool_key: str, resource_class: str, limit: int) -> None:
        self.pool_key = str(pool_key)
        self.resource_class = str(resource_class or "unknown")
        self._limit = normalize_capacity_limit(limit, 1)
        self._active = 0
        self._condition = threading.Condition()

    @property
    def limit(self) -> int:
        with self._condition:
            return self._limit

    def restrict_to(self, limit: int) -> int:
        """Accept stricter callers without allowing order-dependent expansion."""
        requested = normalize_capacity_limit(limit, self._limit)
        with self._condition:
            if requested < self._limit:
                self._limit = requested
                self._condition.notify_all()
            return self._limit

    @contextmanager
    def acquire(self) -> Iterator[PoolLease]:
        started = time.monotonic()
        with self._condition:
            while self._active >= self._limit:
                self._condition.wait()
            self._active += 1
            limit = self._limit
        lease = PoolLease(
            pool_key=self.pool_key,
            configured_limit=limit,
            wait_seconds=round(max(0.0, time.monotonic() - started), 6),
        )
        try:
            yield lease
        finally:
            with self._condition:
                self._active = max(0, self._active - 1)
                self._condition.notify()

    def snapshot(self) -> Dict[str, object]:
        with self._condition:
            return {
                "pool_key": self.pool_key,
                "resource_class": self.resource_class,
                "configured_limit": self._limit,
                "active": self._active,
                "available": max(0, self._limit - self._active),
            }


class ResourcePoolRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pools: Dict[str, FixedCapacityPool] = {}

    def get(self, profile: Mapping[str, object], limit: int) -> FixedCapacityPool:
        pool_key = str(profile.get("pool_key") or "unclassified")
        resource_class = str(profile.get("resource_class") or "unknown")
        requested = normalize_capacity_limit(limit, 1)
        with self._lock:
            pool = self._pools.get(pool_key)
            if pool is None:
                pool = FixedCapacityPool(pool_key, resource_class, requested)
                self._pools[pool_key] = pool
            else:
                pool.restrict_to(requested)
            return pool

    def snapshots(self) -> list:
        with self._lock:
            pools = list(self._pools.values())
        return [pool.snapshot() for pool in sorted(pools, key=lambda item: item.pool_key)]

    def clear(self) -> None:
        with self._lock:
            if any(pool.snapshot()["active"] for pool in self._pools.values()):
                raise RuntimeError("cannot clear resource pools while work is active")
            self._pools.clear()


RESOURCE_POOLS = ResourcePoolRegistry()


def build_read_only_capacity_advisory(
    pool_summary: Mapping[str, object], *, minimum_samples: int = 20,
) -> Dict[str, object]:
    """Recommend keep/reduce only; this function never mutates a live pool."""
    profile = pool_summary.get("resource_profile")
    profile = profile if isinstance(profile, dict) else {}
    current_limit = normalize_capacity_limit(profile.get("configured_limit"), 1)
    sample_count = int(pool_summary.get("request_count", 0) or 0)
    errors = pool_summary.get("error_category_counts")
    errors = errors if isinstance(errors, dict) else {}
    pressure_errors = sum(
        int(errors.get(category, 0) or 0)
        for category in ("rate_limited", "upstream_unavailable", "timeout", "connection_error")
    )
    pressure_rate = pressure_errors / sample_count if sample_count else 0.0
    if sample_count < max(1, int(minimum_samples)):
        action = "insufficient_samples"
        recommended = current_limit
        reason = "minimum request sample count not reached"
    elif pressure_errors >= 2 and pressure_rate >= 0.20:
        action = "reduce"
        recommended = max(1, math.ceil(current_limit / 2))
        reason = "provider pressure error rate is at least 20%"
    elif pressure_errors >= 2 and pressure_rate >= 0.05:
        action = "reduce"
        recommended = max(1, current_limit - 1)
        reason = "provider pressure error rate is at least 5%"
    else:
        action = "keep"
        recommended = current_limit
        reason = "observed pressure does not justify reducing the fixed ceiling"
    return {
        "schema": ADVISORY_SCHEMA,
        "mode": "read_only",
        "pool_key": str(pool_summary.get("pool_key") or profile.get("pool_key") or "unclassified"),
        "sample_count": sample_count,
        "minimum_samples": max(1, int(minimum_samples)),
        "pressure_error_count": pressure_errors,
        "pressure_error_rate": round(pressure_rate, 4),
        "configured_limit": current_limit,
        "recommended_limit": min(current_limit, recommended),
        "action": action,
        "reason": reason,
        "automatic_apply": False,
        "can_increase_capacity": False,
    }


def replay_resource_isolated(function):
    """Wrap one replay dispatch in a runtime-specific process-local pool."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        limit = normalize_capacity_limit(kwargs.pop("resource_pool_limit", 1), 1)
        profile = replay_resource_profile(
            execution_mode=str(kwargs.get("execution_mode") or "auto"),
            target_arch=str(kwargs.get("target_arch") or "auto"),
            runtime_root=str(kwargs.get("runtime_root") or ""),
            runtime_profile=kwargs.get("runtime_profile"),
            qemu_binary=str(kwargs.get("qemu_binary") or ""),
            target_python=str(kwargs.get("target_python") or ""),
            sysroot=str(kwargs.get("sysroot") or ""),
            configured_limit=limit,
        )
        pool = RESOURCE_POOLS.get(profile, limit)
        with pool.acquire():
            return function(*args, **kwargs)
    return wrapped
