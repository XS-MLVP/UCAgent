"""Explicit confirmation for interactive commands that require user consent."""

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmationScreen(ModalScreen[bool]):
    """Require an affirmative action for exactly the command shown in the dialog."""

    DEFAULT_CSS = """
    ConfirmationScreen { align: center middle; }
    #command-confirmation { width: 76; height: auto; padding: 1 2;
        border: solid $warning; background: $surface; }
    #confirmation-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    #confirmation-buttons Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, command):
        """Retain the exact submitted command, including arguments, until dismissal."""
        super().__init__()
        self.command = command

    def compose(self):
        """Display literal command text and separate confirm and cancel actions."""
        with Vertical(id="command-confirmation"):
            yield Static("Confirm this command?")
            yield Static(self.command, markup=False)
            with Horizontal(id="confirmation-buttons"):
                yield Button("Run command", id="confirm-command", variant="warning")
                yield Button("Cancel", id="cancel-command")

    def on_mount(self):
        """Default keyboard focus to cancellation, never implicit approval."""
        self.query_one("#cancel-command", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        """Return the explicit choice without running work inside the dialog."""
        self.dismiss(event.button.id == "confirm-command")

    def action_cancel(self):
        """Escape dismisses the command without executing it."""
        self.dismiss(False)
