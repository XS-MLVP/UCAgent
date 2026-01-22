"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import re
from typing import Any
import threading
import logging
import traceback

from rich.text import Text
from rich.style import Style


# ANSI escape sequence pattern
ANSI_ESCAPE_RE = re.compile(r'\x1b\[(\d+)(;\d+)*m')

# ANSI color code to Rich style mapping
ANSI_COLOR_MAP: dict[str, str] = {
    '30': 'black',
    '31': 'red',
    '32': 'green',
    '33': 'yellow',
    '34': 'blue',
    '35': 'magenta',
    '36': 'cyan',
    '37': 'white',
    '90': 'bright_black',
    '91': 'bright_red',
    '92': 'bright_green',
    '93': 'bright_yellow',
    '94': 'bright_blue',
    '95': 'bright_magenta',
    '96': 'bright_cyan',
    '97': 'bright_white',
}

# Reset code
RESET_CODE = '0'


def parse_ansi_to_rich(text: str) -> Text:
    """Parse ANSI escape sequences and convert to Rich Text.

    Args:
        text: String potentially containing ANSI escape codes

    Returns:
        Rich Text object with proper styling
    """
    if not text:
        return Text()

    result = Text()
    current_style: str | None = None
    pos = 0

    for match in ANSI_ESCAPE_RE.finditer(text):
        start, end = match.span()

        # Add text before this escape sequence
        if start > pos:
            result.append(text[pos:start], style=current_style)

        # Parse escape code
        codes = match.group(0)[2:-1].split(';')
        primary_code = codes[0] if codes else RESET_CODE

        if primary_code == RESET_CODE or primary_code == '':
            current_style = None
        else:
            current_style = ANSI_COLOR_MAP.get(primary_code)

        pos = end

    # Add remaining text
    if pos < len(text):
        result.append(text[pos:], style=current_style)

    return result


def ansi_to_markup(text: str) -> str:
    """Convert ANSI escape sequences to Rich markup.

    Args:
        text: String with ANSI codes

    Returns:
        String with Rich markup tags
    """
    if not text:
        return ""

    result = []
    current_color: str | None = None
    pos = 0

    for match in ANSI_ESCAPE_RE.finditer(text):
        start, end = match.span()

        # Add text before escape
        if start > pos:
            segment = text[pos:start]
            if current_color:
                result.append(f"[{current_color}]{segment}[/{current_color}]")
            else:
                result.append(segment)

        # Parse code
        codes = match.group(0)[2:-1].split(';')
        primary_code = codes[0] if codes else RESET_CODE

        if primary_code == RESET_CODE or primary_code == '':
            current_color = None
        else:
            current_color = ANSI_COLOR_MAP.get(primary_code)

        pos = end

    # Add remaining text
    if pos < len(text):
        segment = text[pos:]
        if current_color:
            result.append(f"[{current_color}]{segment}[/{current_color}]")
        else:
            result.append(segment)

    return "".join(result)


class MessageQueue:
    """Thread-safe message queue for UI updates.

    Note: In textual, we typically use call_from_thread() or post_message()
    instead of a manual queue, but this class provides compatibility
    with the existing architecture if needed.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        import queue
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=maxsize)

    def put(self, msg: str, end: str = "\n") -> None:
        """Add message to queue."""
        try:
            self._queue.put_nowait((msg, end))
        except Exception:
            pass  # Queue full, drop message

    def get_all(self) -> list[tuple[str, str]]:
        """Get all pending messages."""
        messages = []
        while True:
            try:
                messages.append(self._queue.get_nowait())
            except Exception:
                break
        return messages

    @property
    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()


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
