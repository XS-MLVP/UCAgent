"""Pytest plugin for recording runtime DUT API calls per test node."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from types import FrameType


_LOCK = threading.Lock()
_CURRENT_NODE = threading.local()
_CALLS: dict[str, set[str]] = {}
_API_NAMES: set[str] = set()
_TRACE_FILES: set[str] = set()


def _configured_json(name: str, default):
    """Load a JSON environment setting, returning default when absent."""
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _trace(frame: FrameType, event: str, arg):
    """Record calls entering configured API source files during a test."""
    if event == "call":
        source = os.path.abspath(frame.f_code.co_filename)
        node_id = getattr(_CURRENT_NODE, "node_id", None)
        if node_id and source in _TRACE_FILES and frame.f_code.co_name in _API_NAMES:
            with _LOCK:
                _CALLS.setdefault(node_id, set()).add(frame.f_code.co_name)
    return _trace


def pytest_sessionstart(session):
    """Install the runtime tracer for the API checker pytest session."""
    global _API_NAMES, _TRACE_FILES
    _API_NAMES = set(_configured_json("UCAGENT_API_TRACE_NAMES", []))
    _TRACE_FILES = {
        os.path.abspath(path)
        for path in _configured_json("UCAGENT_API_TRACE_FILES", [])
    }
    sys.settrace(_trace)
    threading.settrace(_trace)


def pytest_runtest_protocol(item, nextitem):
    """Associate fixture, call, and teardown events with the current node."""
    _CURRENT_NODE.node_id = item.nodeid
    return None


def pytest_runtest_teardown(item, nextitem):
    """Clear the node association after a test has fully torn down."""
    _CURRENT_NODE.node_id = None


def pytest_sessionfinish(session, exitstatus):
    """Persist the bounded runtime call receipt atomically."""
    receipt_name = os.environ.get("UCAGENT_API_TRACE_RECEIPT")
    if not receipt_name:
        return
    receipt = Path(receipt_name)
    with _LOCK:
        payload = {
            "version": 1,
            "calls": {
                node_id: sorted(api_names)
                for node_id, api_names in sorted(_CALLS.items())
            },
        }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_suffix(receipt.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(receipt)