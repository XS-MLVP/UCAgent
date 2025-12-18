"""
Lightweight broadcast bus for headless mode.

This module keeps an optional broadcaster (e.g., HeadlessServer) and exposes
emit_* helpers that are safe to call even when headless is disabled.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


class _Broadcaster(Protocol):
    def emit_log(self, data: Any) -> None: ...
    def emit_state(self, data: Any) -> None: ...
    def emit_exit(self, code: int) -> None: ...


_server: Optional[_Broadcaster] = None


def register(server: _Broadcaster) -> None:
    global _server
    _server = server


def unregister(server: _Broadcaster) -> None:
    global _server
    if _server is server:
        _server = None


def emit_log(data: Any) -> None:
    if _server:
        try:
            _server.emit_log(data)
        except Exception:
            pass


def emit_state(data: Any) -> None:
    if _server:
        try:
            _server.emit_state(data)
        except Exception:
            pass


def emit_exit(code: int) -> None:
    if _server:
        try:
            _server.emit_exit(code)
        except Exception:
            pass
