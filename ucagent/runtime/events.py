"""Bounded, independently retained activity, system and raw output transcripts."""

from collections import deque
import threading
import time
from uuid import uuid4


class EventBuffer:
    """Retain chunk events with restart-aware cursors and per-view eviction markers."""

    def __init__(self, *, max_records=10000, max_bytes=1024 * 1024):
        """Give each view its own record and UTF-8 byte budget."""
        if max_records < 1 or max_bytes < 4:
            raise ValueError("Event budgets must allow at least one UTF-8 character")
        self.generation = uuid4().hex
        self.max_records = max_records
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._rows = {view: deque() for view in ("activity", "system", "raw")}
        self._sizes = dict.fromkeys(self._rows, 0)
        self._evicted = dict.fromkeys(self._rows, 0)
        self._last = dict.fromkeys(self._rows, 0)
        self._sequence = 0
        self._notice = None

    def append(self, text, *, view="activity", source="model", kind="message", level=None,
               operation_id=None, session_id=None, stream=None, scope="instance"):
        """Record partial lines immediately, bounding oversized text without hiding truncation."""
        if not text:
            return
        if view not in self._rows:
            raise ValueError("Unknown event view")
        encoded = str(text).encode("utf-8", errors="replace")
        truncated = len(encoded) > self.max_bytes
        text = encoded[-self.max_bytes:].decode("utf-8", errors="ignore")
        size = len(text.encode("utf-8"))
        with self._lock:
            self._sequence += 1
            row = dict(id=self._sequence, time=time.time(), source=source, kind=kind,
                       text=text, level=level, operation_id=operation_id, session_id=session_id,
                       stream=stream, scope=scope, truncated=truncated)
            self._rows[view].append(row)
            self._sizes[view] += size
            self._last[view] = row["id"]
            if view == "system" and level in ("WARNING", "ERROR", "CRITICAL"):
                self._notice = {"id": row["id"], "level": level}
            while len(self._rows[view]) > self.max_records or self._sizes[view] > self.max_bytes:
                removed = self._rows[view].popleft()
                self._sizes[view] -= len(removed["text"].encode("utf-8"))
                self._evicted[view] = removed["id"]

    def read(self, view, *, after=None, generation=None, limit=200, tail=False):
        """Return a detached page; reset stale generations and explicitly report lost history."""
        if view not in self._rows or not 1 <= limit <= 1000 or (after is not None and after < 0):
            raise ValueError("Invalid event view, cursor or page limit")
        with self._lock:
            reset = generation is not None and generation != self.generation
            if reset:
                after = None
            rows = list(self._rows[view])
            if tail:
                selected = []
            elif after is None:
                selected = rows[-limit:]
            else:
                selected = [row for row in rows if row["id"] > after][:limit]
            cursor = selected[-1]["id"] if selected else self._last[view]
            return {"generation": self.generation, "data": [dict(row) for row in selected],
                    "cursor": cursor, "reset": reset,
                    "gap": not tail and (self._evicted[view] > (after or 0) or
                                          (after is None and len(rows) > limit)),
                    "has_more": cursor < self._last[view],
                    "system_notice": dict(self._notice) if self._notice else None}
