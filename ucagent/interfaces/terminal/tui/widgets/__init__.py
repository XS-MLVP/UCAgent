"""TUI widgets for UCAgent."""

from ucagent.interfaces.terminal.tui.widgets.console import ConsoleWidget
from ucagent.interfaces.terminal.tui.widgets.console_input import ConsoleInput
from ucagent.interfaces.terminal.tui.widgets.messages_panel import MessagesPanel
from ucagent.interfaces.terminal.tui.widgets.splitter import VerticalSplitter, HorizontalSplitter
from ucagent.interfaces.terminal.tui.widgets.status_bar import StatusBar
from ucagent.interfaces.terminal.tui.widgets.task_panel import TaskPanel

__all__ = [
    "TaskPanel",
    "MessagesPanel",
    "ConsoleWidget",
    "ConsoleInput",
    "VerticalSplitter",
    "HorizontalSplitter",
    "StatusBar",
]
