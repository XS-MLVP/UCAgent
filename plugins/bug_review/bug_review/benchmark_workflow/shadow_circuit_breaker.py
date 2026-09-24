"""Deterministic, read-only circuit-breaker simulation over saved requests."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional, Sequence


SCHEMA = "benchmark_shadow_circuit_breaker.v1"
PRESSURE_ERRORS = {
    "rate_limited",
    "upstream_unavailable",
    "timeout",
    "connection_error",
}


def _timestamp(value: object) -> Optional[float]:
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
    return parsed.astimezone(timezone.utc).timestamp()


def _is_pressure_failure(observation: Mapping[str, object]) -> bool:
    return str(observation.get("error_category") or "") in PRESSURE_ERRORS


def simulate_shadow_circuit(
    observations: Sequence[Mapping[str, object]],
    *,
    window_size: int = 20,
    minimum_pressure_failures: int = 5,
    open_failure_rate: float = 0.30,
    cooldown_seconds: float = 120.0,
    half_open_successes: int = 3,
) -> Dict[str, object]:
    """Replay observations without rejecting, sleeping, or mutating capacity."""
    window_size = max(1, int(window_size))
    minimum_pressure_failures = max(1, int(minimum_pressure_failures))
    open_failure_rate = min(1.0, max(0.0, float(open_failure_rate)))
    cooldown_seconds = max(0.0, float(cooldown_seconds))
    half_open_successes = max(1, int(half_open_successes))
    rolling = deque(maxlen=window_size)
    state = "closed"
    opened_at: Optional[float] = None
    probe_successes = 0
    counterfactual_blocks = 0
    transitions = []

    def transition(next_state: str, index: int, row: Mapping[str, object], reason: str) -> None:
        nonlocal state
        previous = state
        state = next_state
        transitions.append({
            "sequence": index,
            "at": str(row.get("finished_at") or ""),
            "from": previous,
            "to": next_state,
            "reason": reason,
        })

    indexed_rows = list(enumerate(observations))
    indexed_rows.sort(key=lambda item: (
        _timestamp(item[1].get("finished_at")) is None,
        _timestamp(item[1].get("finished_at")) or 0.0,
        item[0],
    ))
    for index, (_, row) in enumerate(indexed_rows, 1):
        now = _timestamp(row.get("finished_at"))
        if state == "open":
            cooldown_elapsed = (
                opened_at is not None and now is not None
                and now - opened_at >= cooldown_seconds
            )
            if not cooldown_elapsed:
                counterfactual_blocks += 1
                continue
            transition("half_open", index, row, "cooldown elapsed; request treated as probe")
            probe_successes = 0

        if state == "half_open":
            if str(row.get("outcome") or "") != "succeeded":
                transition("open", index, row, "half-open probe failed")
                opened_at = now
                probe_successes = 0
                continue
            probe_successes += 1
            if probe_successes >= half_open_successes:
                transition("closed", index, row, "required half-open probes succeeded")
                rolling.clear()
                opened_at = None
                probe_successes = 0
            continue

        pressure_failure = _is_pressure_failure(row)
        rolling.append(pressure_failure)
        pressure_count = sum(1 for value in rolling if value)
        pressure_rate = pressure_count / len(rolling) if rolling else 0.0
        if (
            len(rolling) >= window_size
            and pressure_count >= minimum_pressure_failures
            and pressure_rate >= open_failure_rate
        ):
            transition(
                "open", index, row,
                f"rolling pressure failures reached {pressure_count}/{len(rolling)}",
            )
            opened_at = now
            probe_successes = 0

    pressure_count = sum(1 for value in rolling if value)
    pressure_rate = pressure_count / len(rolling) if rolling else 0.0
    return {
        "schema": SCHEMA,
        "mode": "shadow_read_only",
        "state": state,
        "would_reject_now": state == "open",
        "automatic_apply": False,
        "request_rejection_enabled": False,
        "sample_count": len(indexed_rows),
        "rolling_sample_count": len(rolling),
        "rolling_pressure_failure_count": pressure_count,
        "rolling_pressure_failure_rate": round(pressure_rate, 4),
        "counterfactual_block_count": counterfactual_blocks,
        "half_open_probe_successes": probe_successes,
        "policy": {
            "window_size": window_size,
            "minimum_pressure_failures": minimum_pressure_failures,
            "open_failure_rate": open_failure_rate,
            "cooldown_seconds": cooldown_seconds,
            "half_open_successes": half_open_successes,
        },
        "transitions": transitions[-20:],
    }
