"""Console widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import textwrap

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static, RichLog
from textual.message import Message
from textual.reactive import reactive

from ..utils import parse_ansi_to_rich

if TYPE_CHECKING:
    from ..app import VerifyApp


class ConsoleWidget(Vertical):
    """Console widget with command input and output display."""

    DEFAULT_CSS = """
    ConsoleWidget {
        border: solid $primary;
        border-title-color: $text;
        border-title-align: center;
        height: 15;
    }

    ConsoleWidget #console-output {
        height: 1fr;
        padding: 0 1;
    }

    ConsoleWidget #console-input {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }

    ConsoleWidget #console-suggest {
        padding: 0 1;
        color: $text;
        background: $surface;
        height: auto;
    }

    ConsoleWidget #console-input.busy {
        color: $warning;
    }
    """

    # Custom messages
    class CommandSubmitted(Message):
        """Message sent when a command is submitted."""
        def __init__(self, command: str, daemon: bool = False) -> None:
            super().__init__()
            self.command = command
            self.daemon = daemon

    # Busy indicator frames
    BUSY_FRAMES: ClassVar[list[str]] = ['⣷', '⣯', '⣟', '⡿', '⢿', '⣻', '⣽', '⣾']
    # State
    is_busy: reactive[bool] = reactive(False)

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Console"
        self.prompt = prompt
        self._busy_frame_index: int = 0
        self._page_mode: bool = False
        self._suggestions_visible: bool = False
        self._suggestions_text: str = ""

    def compose(self) -> ComposeResult:
        """Compose the console widget."""
        # Use RichLog for output with built-in line limiting and scrolling
        yield RichLog(
            id="console-output",
            max_lines=1000,
            auto_scroll=True,
            wrap=True,
            markup=False,
            highlight=False
        )
        yield Input(placeholder=self.prompt, id="console-input")
        yield Static(id="console-suggest")

    def on_mount(self) -> None:
        """Setup after mounting."""
        self._update_prompt()
        self._hide_suggestions()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command submission."""
        cmd = event.value.strip()
        input_widget = self.query_one("#console-input", Input)
        input_widget.value = ""
        self.clear_suggestions()

        if not cmd:
            return

        # Check for daemon command (ends with &)
        daemon = cmd.endswith("&")
        if daemon:
            cmd = cmd[:-1].strip()

        # Echo command to output
        self.append_output(f"{self.prompt}{cmd}\n")

        # Post command message
        self.post_message(self.CommandSubmitted(cmd, daemon))

    def append_output(self, text: str) -> None:
        """Append text to console output.

        Args:
            text: Text to append (may contain ANSI codes)
        """
        if not text:
            return

        # Process text
        processed = text.replace("\t", "    ")
        processed = processed.replace("\r\n", "\n").replace("\r", "\n")

        # Get RichLog widget and write with ANSI parsing
        output_log = self.query_one("#console-output", RichLog)

        # RichLog handles line limiting automatically via max_lines
        # Split by lines and write each with ANSI parsing
        lines = processed.split("\n")
        for i, line in enumerate(lines):
            # Don't add extra newline for last empty line
            if i == len(lines) - 1 and not line:
                continue
            output_log.write(parse_ansi_to_rich(line))

    def clear_output(self) -> None:
        """Clear console output."""
        output_log = self.query_one("#console-output", RichLog)
        output_log.clear()
        self._page_mode = False
        self._update_prompt()

    def _update_prompt(self) -> None:
        """Update the input prompt based on state."""
        input_widget = self.query_one("#console-input", Input)

        prefix = ""
        if self.is_busy:
            frame = self.BUSY_FRAMES[self._busy_frame_index % len(self.BUSY_FRAMES)]
            self._busy_frame_index += 1
            prefix = f"{frame} "

        if self._page_mode:
            prefix += "<Up/Down: scroll, Esc: exit> "

        input_widget.placeholder = f"{prefix}{self.prompt}"

    def set_busy(self, busy: bool) -> None:
        """Set busy state."""
        self.is_busy = busy
        input_widget = self.query_one("#console-input", Input)
        input_widget.set_class(busy, "busy")
        self._update_prompt()

    def enter_page_mode(self) -> None:
        """Enter paginated output mode."""
        if not self._page_mode:
            self._page_mode = True
            output_log = self.query_one("#console-output", RichLog)
            output_log.auto_scroll = False
            self._update_prompt()

    def exit_page_mode(self) -> None:
        """Exit paginated output mode."""
        if self._page_mode:
            self._page_mode = False
            output_log = self.query_one("#console-output", RichLog)
            output_log.auto_scroll = True
            output_log.scroll_end(animate=False)
            self._update_prompt()

    def page_scroll(self, delta: int, auto_enter: bool = False) -> bool:
        """Scroll in page mode.

        Args:
            delta: Lines to scroll (negative = up, positive = down)
            auto_enter: Enter page mode if not already active

        Returns:
            True if in page mode and scrolled
        """
        if not self._page_mode:
            if not auto_enter:
                return False
            self.enter_page_mode()

        output_log = self.query_one("#console-output", RichLog)

        # Use RichLog's built-in scroll methods
        if delta < 0:
            output_log.scroll_relative(y=delta, animate=False)
        else:
            output_log.scroll_relative(y=delta, animate=False)

        return True

    def output_line_count(self) -> int:
        """Return the number of buffered output lines."""
        output_log = self.query_one("#console-output", RichLog)
        return len(output_log.lines)

    @property
    def has_suggestions(self) -> bool:
        return self._suggestions_visible

    def show_suggestions(self, suggestions: list[str]) -> None:
        if not suggestions:
            self.clear_suggestions()
            return
        text = " ".join(suggestions)
        self._suggestions_text = text
        self.query_one("#console-suggest", Static).update(text)
        self._show_suggestions()

        extra_lines = self._measure_suggestion_lines(text)
        app: VerifyApp = self.app  # type: ignore
        app.set_console_extra_height(extra_lines)

    def clear_suggestions(self) -> None:
        if not self._suggestions_visible:
            return
        self.query_one("#console-suggest", Static).update("")
        self._hide_suggestions()
        app: VerifyApp = self.app  # type: ignore
        app.set_console_extra_height(0)

    def _show_suggestions(self) -> None:
        self._suggestions_visible = True
        widget = self.query_one("#console-suggest")
        widget.styles.display = "block"

    def _hide_suggestions(self) -> None:
        self._suggestions_visible = False
        widget = self.query_one("#console-suggest")
        widget.styles.display = "none"

    def _measure_suggestion_lines(self, text: str) -> int:
        width = max(20, self.size.width - 2)
        wrapped = textwrap.wrap(text, width=width)
        return max(1, len(wrapped))

    def watch_is_busy(self, _busy: bool) -> None:
        """React to busy state changes."""
        self._update_prompt()

    def refresh_prompt(self) -> None:
        """Refresh the input prompt display."""
        self._update_prompt()
