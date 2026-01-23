"""TUI widgets for UCAgent."""

from .task_panel import TaskPanel
from .status_panel import StatusPanel
from .messages_panel import MessagesPanel
from .console import ConsoleWidget
from .console_input import ConsoleInput
from .splitter import VerticalSplitter, HorizontalSplitter

__all__ = [
    "TaskPanel",
    "StatusPanel",
    "MessagesPanel",
    "ConsoleWidget",
    "ConsoleInput",
    "VerticalSplitter",
    "HorizontalSplitter",
]
