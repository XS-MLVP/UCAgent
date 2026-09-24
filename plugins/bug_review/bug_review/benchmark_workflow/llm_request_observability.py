"""Credential-free, request-level LLM capacity observations.

The observer is deliberately independent from semantic business logic.  It
stores timing/status metadata only; prompts, responses, headers, credentials,
and candidate identifiers never enter the database.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
from typing import Dict, Iterator, Mapping, Optional
import uuid

from .task_resources import classify_task_error, llm_resource_profile
from .resource_pools import (
    RESOURCE_POOLS,
    build_read_only_capacity_advisory,
    normalize_capacity_limit,
)
from .shadow_circuit_breaker import simulate_shadow_circuit


SCHEMA = "benchmark_llm_request_observations.v2"
DEFAULT_MAX_RECORDS_PER_POOL = 5000
_REQUEST_CONTEXT: ContextVar[Dict[str, str]] = ContextVar(
    "benchmark_llm_request_context", default={},
)
_POOL_WAIT_SECONDS: ContextVar[float] = ContextVar(
    "benchmark_llm_pool_wait_seconds", default=0.0,
)
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def llm_request_context(operation: str) -> Iterator[None]:
    """Label calls made inside one semantic operation without carrying input."""
    token = _REQUEST_CONTEXT.set({"operation": str(operation or "unknown")})
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


class _ObservedHTTPStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP status {status_code}")
        self.status_code = status_code


class LLMRequestObservationStore:
    """Small SQLite event store with bounded retention per resource pool."""

    def __init__(self, path: Path, max_records_per_pool: int = DEFAULT_MAX_RECORDS_PER_POOL) -> None:
        raw = Path(path).expanduser()
        self.path = (
            raw if raw.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            else raw / "llm_requests.sqlite3"
        )
        self.max_records_per_pool = max(1, int(max_records_per_pool))
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS request_observations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    schema_name TEXT NOT NULL,
                    pool_key TEXT NOT NULL,
                    resource_profile TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_seconds REAL,
                    queue_wait_seconds REAL,
                    error_category TEXT,
                    error_type TEXT,
                    status_code INTEGER
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS request_pool_sequence "
                "ON request_observations(pool_key, sequence DESC)"
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(request_observations)"
                ).fetchall()
            }
            if "queue_wait_seconds" not in columns:
                connection.execute(
                    "ALTER TABLE request_observations "
                    "ADD COLUMN queue_wait_seconds REAL"
                )
            connection.commit()
            self._initialized = True

    def append(self, observation: Mapping[str, object]) -> None:
        profile = observation.get("resource_profile")
        profile = dict(profile) if isinstance(profile, dict) else {}
        pool_key = str(profile.get("pool_key") or "unclassified")
        with self._connect() as connection:
            self._initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO request_observations (
                    request_id, schema_name, pool_key, resource_profile,
                    operation, transport, outcome, started_at, finished_at,
                    duration_seconds, queue_wait_seconds, error_category,
                    error_type, status_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(observation.get("request_id") or uuid.uuid4().hex),
                    SCHEMA,
                    pool_key,
                    json.dumps(profile, ensure_ascii=False, sort_keys=True),
                    str(observation.get("operation") or "unknown"),
                    str(observation.get("transport") or "unknown"),
                    str(observation.get("outcome") or "unknown"),
                    str(observation.get("started_at") or ""),
                    str(observation.get("finished_at") or ""),
                    observation.get("duration_seconds"),
                    observation.get("queue_wait_seconds"),
                    observation.get("error_category"),
                    observation.get("error_type"),
                    observation.get("status_code"),
                ),
            )
            connection.execute(
                """
                DELETE FROM request_observations
                WHERE pool_key = ? AND sequence NOT IN (
                    SELECT sequence FROM request_observations
                    WHERE pool_key = ? ORDER BY sequence DESC LIMIT ?
                )
                """,
                (pool_key, pool_key, self.max_records_per_pool),
            )
            connection.commit()

    def read_all(self) -> list:
        if not self.path.is_file():
            return []
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=30.0) as connection:
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(request_observations)"
                ).fetchall()
            }
            queue_wait_expression = (
                "queue_wait_seconds" if "queue_wait_seconds" in columns
                else "NULL AS queue_wait_seconds"
            )
            rows = connection.execute(
                f"""
                SELECT request_id, pool_key, resource_profile, operation,
                       transport, outcome, started_at, finished_at,
                       duration_seconds, {queue_wait_expression}, error_category,
                       error_type, status_code
                FROM request_observations ORDER BY sequence
                """
            ).fetchall()
        observations = []
        for row in rows:
            try:
                profile = json.loads(row[2])
            except (TypeError, json.JSONDecodeError):
                profile = {}
            observations.append({
                "schema": SCHEMA,
                "request_id": row[0],
                "pool_key": row[1],
                "resource_profile": profile if isinstance(profile, dict) else {},
                "operation": row[3],
                "transport": row[4],
                "outcome": row[5],
                "started_at": row[6],
                "finished_at": row[7],
                "duration_seconds": row[8],
                "queue_wait_seconds": row[9],
                "error_category": row[10],
                "error_type": row[11],
                "status_code": row[12],
            })
        return observations


def _percentile(values: list, quantile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 6)


def summarize_llm_request_observations(paths) -> Dict[str, object]:
    """Read one or more stores without exposing individual request content."""
    observations = []
    errors = []
    resolved_sources = []
    for raw_path in paths:
        store = LLMRequestObservationStore(Path(raw_path))
        resolved_sources.append(str(store.path.resolve()))
        try:
            observations.extend(store.read_all())
        except (OSError, sqlite3.DatabaseError) as exc:
            errors.append({
                "path": str(store.path.resolve()),
                "error": f"{type(exc).__name__}: {exc}",
            })
    # Multiple CLI paths may name the same database. Request IDs prevent
    # inflated capacity statistics without discarding provenance.
    by_id = {
        str(item.get("request_id") or f"anonymous-{index}"): item
        for index, item in enumerate(observations)
    }
    grouped = defaultdict(list)
    for item in by_id.values():
        grouped[str(item.get("pool_key") or "unclassified")].append(item)
    pools = []
    for pool_key, rows in sorted(grouped.items()):
        outcomes = Counter(str(row.get("outcome") or "unknown") for row in rows)
        errors_by_category = Counter(
            str(row.get("error_category"))
            for row in rows if row.get("error_category")
        )
        status_codes = Counter(
            str(row.get("status_code"))
            for row in rows if row.get("status_code") is not None
        )
        operations = Counter(str(row.get("operation") or "unknown") for row in rows)
        transports = Counter(str(row.get("transport") or "unknown") for row in rows)
        durations = [
            float(row["duration_seconds"])
            for row in rows
            if isinstance(row.get("duration_seconds"), (int, float))
        ]
        queue_waits = [
            float(row["queue_wait_seconds"])
            for row in rows
            if isinstance(row.get("queue_wait_seconds"), (int, float))
        ]
        succeeded = int(outcomes.get("succeeded", 0))
        profile = next(
            (row.get("resource_profile") for row in rows if isinstance(row.get("resource_profile"), dict)),
            {},
        )
        profile = dict(profile)
        observed_limits = [
            int(row.get("resource_profile", {}).get("configured_limit"))
            for row in rows
            if isinstance(row.get("resource_profile"), dict)
            and isinstance(row.get("resource_profile", {}).get("configured_limit"), int)
        ]
        if observed_limits:
            profile["configured_limit"] = min(observed_limits)
        pool_summary = {
            "pool_key": pool_key,
            "resource_profile": profile,
            "request_count": len(rows),
            "succeeded_request_count": succeeded,
            "success_rate": round(succeeded / len(rows), 4) if rows else None,
            "outcome_counts": dict(sorted(outcomes.items())),
            "operation_counts": dict(sorted(operations.items())),
            "transport_counts": dict(sorted(transports.items())),
            "error_category_counts": dict(sorted(errors_by_category.items())),
            "status_code_counts": dict(sorted(status_codes.items())),
            "latency_seconds": {
                "sample_count": len(durations),
                "p50": _percentile(durations, 0.50),
                "p95": _percentile(durations, 0.95),
                "max": round(max(durations), 6) if durations else None,
            },
            "queue_wait_seconds": {
                "sample_count": len(queue_waits),
                "contended_count": sum(value >= 0.001 for value in queue_waits),
                "contention_rate": (
                    round(sum(value >= 0.001 for value in queue_waits) / len(queue_waits), 4)
                    if queue_waits else None
                ),
                "p50": _percentile(queue_waits, 0.50),
                "p95": _percentile(queue_waits, 0.95),
                "max": round(max(queue_waits), 6) if queue_waits else None,
            },
        }
        pool_summary["capacity_advisory"] = build_read_only_capacity_advisory(
            pool_summary,
        )
        pool_summary["shadow_circuit"] = simulate_shadow_circuit(rows)
        pools.append(pool_summary)
    return {
        "schema": SCHEMA,
        "scope": "llm_http_response_or_sdk_call",
        "transport_retry_visibility": "httpx_responses_visible_transport_exceptions_final_only",
        "source_paths": sorted(set(resolved_sources)),
        "request_count": len(by_id),
        "read_errors": errors,
        "resource_pools": pools,
    }


class LLMRequestObserver:
    def __init__(self, config: Mapping[str, object]) -> None:
        self.resource_profile = llm_resource_profile(config)
        self.execution_pool = RESOURCE_POOLS.get(
            self.resource_profile,
            normalize_capacity_limit(config.get("resource_pool_limit"), 10),
        )
        self.resource_profile["configured_limit"] = self.execution_pool.limit
        try:
            retention = int(
                config.get("request_observation_max_records_per_pool")
                or DEFAULT_MAX_RECORDS_PER_POOL
            )
        except (TypeError, ValueError):
            retention = DEFAULT_MAX_RECORDS_PER_POOL
        observation_dir = str(config.get("request_observation_dir") or "").strip()
        self.store = (
            LLMRequestObservationStore(Path(observation_dir), retention)
            if observation_dir else None
        )
        self._storage_warning_emitted = False

    def _safe_append(self, observation: Mapping[str, object]) -> None:
        """Observability must never turn a valid provider call into a failure."""
        if self.store is None:
            return
        try:
            self.store.append(observation)
        except (OSError, sqlite3.DatabaseError) as exc:
            if not self._storage_warning_emitted:
                self._storage_warning_emitted = True
                logger.warning(
                    "LLM request observation disabled after storage failure at %s: %s",
                    self.store.path,
                    exc,
                )

    @staticmethod
    def _request_timing(request: object) -> tuple:
        extensions = getattr(request, "extensions", None)
        extensions = extensions if isinstance(extensions, dict) else {}
        return (
            str(extensions.get("benchmark_started_at") or utc_now()),
            extensions.get("benchmark_started_monotonic"),
            str(extensions.get("benchmark_operation") or "unknown"),
        )

    def on_http_request(self, request: object) -> None:
        extensions = getattr(request, "extensions", None)
        if not isinstance(extensions, dict):
            return
        extensions["benchmark_started_at"] = utc_now()
        extensions["benchmark_started_monotonic"] = time.monotonic()
        extensions["benchmark_operation"] = str(
            _REQUEST_CONTEXT.get({}).get("operation") or "unknown"
        )
        extensions["benchmark_pool_wait_seconds"] = float(
            _POOL_WAIT_SECONDS.get(0.0) or 0.0
        )

    def on_http_response(self, response: object) -> None:
        request = getattr(response, "request", None)
        started_at, started_monotonic, operation = self._request_timing(request)
        finished_at = utc_now()
        duration = (
            max(0.0, time.monotonic() - float(started_monotonic))
            if isinstance(started_monotonic, (int, float)) else None
        )
        try:
            status_code = int(getattr(response, "status_code"))
        except (TypeError, ValueError):
            status_code = None
        outcome = "succeeded" if status_code is not None and status_code < 400 else "failed"
        request_extensions = getattr(request, "extensions", None)
        request_extensions = request_extensions if isinstance(request_extensions, dict) else {}
        observation = {
            "request_id": uuid.uuid4().hex,
            "resource_profile": self.resource_profile,
            "operation": operation,
            "transport": "httpx_response",
            "outcome": outcome,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(duration, 6) if duration is not None else None,
            "queue_wait_seconds": float(
                request_extensions.get(
                    "benchmark_pool_wait_seconds", 0.0,
                ) or 0.0
            ),
            "status_code": status_code,
        }
        if outcome == "failed" and status_code is not None:
            observation.update(classify_task_error(_ObservedHTTPStatusError(status_code)))
        self._safe_append(observation)

    def observe_sdk_call(self, operation: str, function, args: tuple, kwargs: dict, *, record_success: bool):
        started_at = utc_now()
        started = time.monotonic()
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            # TypeError is commonly the local response_format compatibility
            # fallback and does not prove that a network request occurred.
            response = getattr(exc, "response", None)
            if not isinstance(exc, TypeError) and response is None:
                self._append_sdk_observation(
                    operation, started_at, started, "failed", error=exc,
                )
            raise
        if record_success:
            self._append_sdk_observation(operation, started_at, started, "succeeded")
        return result

    def _append_sdk_observation(
        self, operation: str, started_at: str, started: float, outcome: str,
        error: Optional[BaseException] = None,
    ) -> None:
        observation = {
            "request_id": uuid.uuid4().hex,
            "resource_profile": self.resource_profile,
            "operation": operation,
            "transport": "sdk_call",
            "outcome": outcome,
            "started_at": started_at,
            "finished_at": utc_now(),
            "duration_seconds": round(max(0.0, time.monotonic() - started), 6),
            "queue_wait_seconds": float(_POOL_WAIT_SECONDS.get(0.0) or 0.0),
        }
        if error is not None:
            observation.update(classify_task_error(error))
        self._safe_append(observation)


class _ObservedCreateProxy:
    def __init__(self, target: object, observer: LLMRequestObserver, record_success: bool) -> None:
        self._target = target
        self._observer = observer
        self._record_success = record_success

    def create(self, *args, **kwargs):
        operation = str(_REQUEST_CONTEXT.get({}).get("operation") or "unknown")
        with self._observer.execution_pool.acquire() as lease:
            token = _POOL_WAIT_SECONDS.set(lease.wait_seconds)
            try:
                return self._observer.observe_sdk_call(
                    operation, self._target.create, args, kwargs,
                    record_success=self._record_success,
                )
            finally:
                _POOL_WAIT_SECONDS.reset(token)

    def __getattr__(self, name: str):
        return getattr(self._target, name)


class ObservedLLMClient:
    """Shape-preserving proxy for OpenAI-compatible client surfaces."""

    def __init__(self, client: object, observer: LLMRequestObserver, *, transport_hooks: bool) -> None:
        self._client = client
        self.request_observer = observer
        record_success = not transport_hooks
        chat = getattr(client, "chat", None)
        completions = getattr(chat, "completions", None)
        self.chat = (
            SimpleNamespace(completions=_ObservedCreateProxy(completions, observer, record_success))
            if completions is not None else chat
        )
        responses = getattr(client, "responses", None)
        self.responses = (
            _ObservedCreateProxy(responses, observer, record_success)
            if responses is not None else responses
        )

    def __getattr__(self, name: str):
        return getattr(self._client, name)


def observe_llm_client(
    client: object, config: Mapping[str, object], *, transport_hooks: bool,
) -> object:
    if not str(config.get("request_observation_dir") or "").strip():
        return client
    return ObservedLLMClient(
        client, LLMRequestObserver(config), transport_hooks=transport_hooks,
    )
