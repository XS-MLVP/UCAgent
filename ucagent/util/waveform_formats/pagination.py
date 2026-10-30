"""Deterministic bounded pages for backends that return a full signal mapping."""

from collections.abc import Mapping
from typing import Any

from .protocols import WaveformSignal, WaveformSignalMatches


DEFAULT_SIGNAL_LIMIT = 100
MAX_SIGNAL_LIMIT = 1000


def paginate_signal_matches(
    signals: Mapping[Any, WaveformSignal],
    *,
    offset: int = 0,
    limit: int = DEFAULT_SIGNAL_LIMIT,
) -> WaveformSignalMatches:
    """Sort by full path and return ``[offset, offset + limit)`` plus total.

    Use this helper when a library has no native query pagination. Native-page
    backends can implement the same result directly. The mapping's original
    keys and descriptor objects are preserved, and no trace values are loaded.
    """
    if type(offset) is not int or offset < 0:
        raise ValueError("signal offset must be a nonnegative integer")
    if type(limit) is not int or not 1 <= limit <= MAX_SIGNAL_LIMIT:
        raise ValueError(f"signal limit must be an integer from 1 to {MAX_SIGNAL_LIMIT}")
    ordered = sorted(signals.items(), key=lambda item: item[1].full_name)
    return {
        "signals": dict(ordered[offset:offset + limit]),
        "total": len(ordered),
        "offset": offset,
        "limit": limit,
    }
