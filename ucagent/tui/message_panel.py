from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Placeholder, Log


class MessagePanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Placeholder("Messages")
