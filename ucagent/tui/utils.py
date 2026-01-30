"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import VerifyApp


class ConsoleCapture:
    """Thread-safe stdout/stderr capture for console output."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer: list[str] = []

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            self._buffer.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def get_and_clear(self) -> str:
        with self._lock:
            if not self._buffer:
                return ""
            data = "".join(self._buffer)
            self._buffer = []
        return data

    def isatty(self) -> bool:
        return False


class UILogHandler(logging.Handler):
    """Logging handler that forwards messages to the TUI message panel."""

    def __init__(self, ui: "VerifyApp", level: int = logging.INFO) -> None:
        super().__init__(level)
        self.ui = ui
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.ui.message_echo(msg)
        except Exception:
            self.handleError(record)


def create_ui_logger(ui: "VerifyApp", level: int | str = logging.INFO) -> logging.Logger:
    """Create a logger that forwards messages to the TUI.

    Args:
        ui: The VerifyApp instance.
        level: Logging level (int or string like "INFO").

    Returns:
        Configured Logger instance.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(f"UCAgent.TUI.{id(ui)}")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(UILogHandler(ui, level))  # type: ignore[arg-type]
    logger.propagate = False
    return logger
