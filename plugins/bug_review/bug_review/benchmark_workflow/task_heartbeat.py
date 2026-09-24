"""Lease heartbeat shared by independent durable-task workers."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from .durable_task_store import TaskLeaseLost


class LeaseHeartbeat:
    """Renew a lease in the background and fail closed if ownership is lost."""

    def __init__(
        self,
        renew: Callable[[], None],
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._renew = renew
        self._interval = float(interval_seconds)
        self._stop = threading.Event()
        self._failure: Optional[BaseException] = None
        self._thread = threading.Thread(
            target=self._run,
            name="benchmark-task-heartbeat",
            daemon=True,
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._renew()
            except BaseException as exc:
                self._failure = exc
                self._stop.set()
                return

    def start(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval * 2.0))

    def ensure_owned(self) -> None:
        if self._failure is not None:
            raise TaskLeaseLost(
                f"task heartbeat lost lease ownership: {type(self._failure).__name__}: {self._failure}"
            ) from self._failure

    def __enter__(self) -> "LeaseHeartbeat":
        return self.start()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
        if exc is None:
            self.ensure_owned()
