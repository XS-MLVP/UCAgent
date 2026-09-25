"""Read structured evidence and serialize workflow state changes."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
from pathlib import Path


def read_object(path):
    """Read a JSON object and reject non-object artifacts."""
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


@contextmanager
def task_lock(path):
    """Hold an exclusive lock while changing workflow or judgment state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
