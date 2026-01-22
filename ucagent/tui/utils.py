"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import threading
import logging
import traceback

from rich.text import Text


def parse_ansi_to_rich(text: str) -> Text:
    """Parse ANSI escape sequences and convert to Rich Text.

    Uses Rich's built-in ANSI parsing for better compatibility and performance.

    Args:
        text: String potentially containing ANSI escape codes

    Returns:
        Rich Text object with proper styling
    """
    if not text:
        return Text()

    # Rich's Text.from_ansi() handles all ANSI codes natively
    return Text.from_ansi(text)




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
    """Logger that forwards messages into the TUI message panel."""

    def __init__(self, ui, level=logging.getLevelName("INFO")):
        super().__init__(name="UIMsgLogger", level=level)
        self.ui = ui

    def log(self, level, msg, *args, **kwargs):
        self.ui.message_echo(f"[{logging.getLevelName(level)}] {msg % args if args else msg}")

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        self.error(msg, *args, **kwargs)
        if exc_info:
            traceback.print_exc()
