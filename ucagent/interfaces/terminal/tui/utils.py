"""Utility functions for UCAgent TUI."""

from __future__ import annotations

import logging
import queue
import traceback
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ucagent.interfaces.terminal.tui.app import VerifyApp


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


def agent_display_name(agent: Any) -> str:
    """Return a stable, user-facing identity for the current Agent or worker."""
    explicit = getattr(agent, "message_sender", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    cfg = getattr(agent, "cfg", None)
    mission_id = cfg.get_value("agent_run.id", None) if cfg is not None else None
    if getattr(agent, "global_agent_settings", None) is not None:
        return "Global"
    if getattr(agent, "multi_agent_settings", None) is not None:
        return f"Super:{mission_id or 'DUT'}"
    return "Agent"


def format_check_result(check_info: Any, sender: str) -> str:
    """Render the latest Check result as compact, attributable context."""
    from ucagent.core.stage.display import format_check_result as render
    return render(check_info, sender=sender)
