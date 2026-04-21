"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import logging
import queue
import traceback
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import VerifyApp
    from ucagent.verify_pdb import VerifyPDB


class ConsoleCapture:
    """Thread-safe stdout/stderr capture using queue.SimpleQueue."""

    def __init__(
            self,
            vpdb: "VerifyPDB | None" = None,
            *,
            record_to_vpdb: bool = True,
    ) -> None:
        self._queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._history: list[str] = []
        self._vpdb = vpdb
        self._record_to_vpdb = record_to_vpdb

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._queue.put_nowait(text)
        self._history.append(text)
        if self._record_to_vpdb and self._vpdb is not None:
            self._vpdb.record_console_output(text)
        return len(text)

    def flush(self) -> None:
        pass

    def get_and_clear(self) -> str:
        items: list[str] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return "".join(items)

    def get_history(self) -> str:
        return "".join(self._history)

    def isatty(self) -> bool:
        return False


class PersistentConsoleMirror:
    """Forward stdout/stderr to the real stream while recording shared console history."""

    def __init__(self, vpdb: "VerifyPDB", original: Any) -> None:
        self._vpdb = vpdb
        while isinstance(original, PersistentConsoleMirror):
            original = original._original
        self._original = original
        self.encoding = getattr(self._original, "encoding", "utf-8")
        self.errors = getattr(self._original, "errors", "replace")

    def write(self, text: str) -> int:
        if not text:
            return 0
        if self._vpdb.should_record_console_output():
            self._vpdb.record_console_output(text)
        return self._original.write(text)

    def flush(self) -> None:
        flush = getattr(self._original, "flush", None)
        if callable(flush):
            flush()

    def isatty(self) -> bool:
        isatty = getattr(self._original, "isatty", None)
        if callable(isatty):
            return bool(isatty())
        return False

    def fileno(self) -> int:
        fileno = getattr(self._original, "fileno", None)
        if callable(fileno):
            return fileno()
        raise OSError("Underlying stream does not support fileno()")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class UIMsgLogger(logging.Logger):
    """Logger that directly forwards messages to the TUI message panel.

    This class inherits from logging.Logger and overrides log methods
    to directly call message_echo, bypassing the standard Handler/Formatter
    flow. This is necessary because uvicorn's AccessFormatter expects
    specific log record attributes that normal log records don't have.

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

    def exception(
            self, msg: object, *args: object, exc_info: bool = True, **kwargs: object
    ) -> None:
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
