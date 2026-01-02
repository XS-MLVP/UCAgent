from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Placeholder, Log, Input, Label


class CommandPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Placeholder("Command Logs", classes="command")
        yield Input()
