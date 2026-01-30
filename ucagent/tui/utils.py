"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import logging
import threading
import traceback
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


class UIMsgLogger(logging.Logger):
    """Logger that directly forwards messages to the TUI message panel.

    This class inherits from logging.Logger and overrides log methods
    to directly call message_echo, bypassing the standard Handler/Formatter
    flow. This is necessary because uvicorn's AccessFormatter expects
    specific log record attributes that normal log records don't have.

    This implementation matches verify_ui.py's UIMsgLogger.
    """

    def __init__(self, ui: "VerifyApp", level: int | str = logging.INFO) -> None:
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        super().__init__(name="UIMsgLogger", level=level)  # type: ignore[arg-type]
        self.ui = ui

    def log(self, level: int, msg: object, *args: object, **kwargs: object) -> None:
        if args:
            try:
                formatted_msg = str(msg) % args
            except (TypeError, ValueError):
                formatted_msg = str(msg)
        else:
            formatted_msg = str(msg)
        self.ui.message_echo(f"[{logging.getLevelName(level)}] {formatted_msg}")

    def debug(self, msg: object, *args: object, **kwargs: object) -> None:
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: object, *args: object, **kwargs: object) -> None:
        self.log(logging.WARNING, msg, *args, **kwargs)

    def warn(self, msg: object, *args: object, **kwargs: object) -> None:
        self.warning(msg, *args, **kwargs)

    def error(self, msg: object, *args: object, **kwargs: object) -> None:
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: object, *args: object, **kwargs: object) -> None:
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: object, *args: object, exc_info: bool = True, **kwargs: object) -> None:
        self.error(msg, *args, **kwargs)
        if exc_info:
            self.ui.message_echo(traceback.format_exc())


def create_ui_logger(ui: "VerifyApp", level: int | str = logging.INFO) -> UIMsgLogger:
    """Create a logger that forwards messages to the TUI.

    Args:
        ui: The VerifyApp instance.
        level: Logging level (int or string like "INFO").

    Returns:
        UIMsgLogger instance.
    """
    return UIMsgLogger(ui, level)
