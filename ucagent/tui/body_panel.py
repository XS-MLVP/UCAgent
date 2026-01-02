from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Placeholder, Static

from ucagent.tui.command_panel import CommandPanel
from ucagent.tui.message_panel import MessagePanel


class BodyPanel(Vertical):
    """Body to display `Messages` and `Command` panel"""

    def compose(self) -> ComposeResult:
        yield MessagePanel(classes="messages")
        yield CommandPanel(classes="command")
