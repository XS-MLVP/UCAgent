"""Console widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import textwrap

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static
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
        overflow-y: auto;
    }

    ConsoleWidget #console-output-text {
        width: 100%;
    }

    ConsoleWidget #console-input {
        height: 1;
        border: none;
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
    output_buffer: reactive[str] = reactive("")

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Console"
        self.prompt = prompt
        self._busy_frame_index: int = 0
        self._output_lines: list[str] = []
        self._partial_line: str | None = None
        self._page_cache: list[str] | None = None
        self._page_index: int = 0
        self._max_output_lines: int = 1000
        self._suggestions_visible: bool = False
        self._suggestions_text: str = ""

    def compose(self) -> ComposeResult:
        """Compose the console widget."""
        with VerticalScroll(id="console-output"):
            yield Static(id="console-output-text")
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
        # Process and store
        processed = text.replace("\t", "    ").replace("\r", "\n")

        if self._partial_line is not None:
            if self._output_lines:
                self._output_lines.pop()
            processed = self._partial_line + processed
            self._partial_line = None

        lines = processed.split("\n")
        if processed.endswith("\n"):
            self._partial_line = None
        else:
            self._partial_line = lines[-1]

        for line in lines:
            self._output_lines.append(line)

        # Trim if over limit
        if len(self._output_lines) > self._max_output_lines:
            self._output_lines = self._output_lines[-self._max_output_lines:]

        self._update_display()

    def clear_output(self) -> None:
        """Clear console output."""
        self._output_lines = []
        self._partial_line = None
        self._page_cache = None
        self._page_index = 0
        self._update_display()
        self._update_prompt()

    def _update_display(self) -> None:
        """Update the console output display."""
        if self._page_cache is not None:
            # Page mode
            lines = self._page_cache
        else:
            # Normal mode - show all buffered lines
            lines = self._output_lines

        # Parse ANSI and update
        rich_content = parse_ansi_to_rich("\n".join(lines))
        self.query_one("#console-output-text", Static).update(rich_content)

        output_scroll = self.query_one("#console-output", VerticalScroll)
        if self._page_cache is None:
            output_scroll.scroll_end(animate=False)
        else:
            output_scroll.scroll_to(y=self._page_index, animate=False)

    def _update_prompt(self) -> None:
        """Update the input prompt based on state."""
        input_widget = self.query_one("#console-input", Input)

        prefix = ""
        if self.is_busy:
            frame = self.BUSY_FRAMES[self._busy_frame_index % len(self.BUSY_FRAMES)]
            self._busy_frame_index += 1
            prefix = f"{frame} "

        if self._page_cache is not None:
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
        if self._page_cache is None:
            self._page_cache = self._output_lines.copy()
            app: VerifyApp = self.app  # type: ignore
            self._page_index = max(0, len(self._page_cache) - app.console_height)
            self._update_display()
            self._update_prompt()

    def exit_page_mode(self) -> None:
        """Exit paginated output mode."""
        self._page_cache = None
        self._page_index = 0
        self._update_display()
        self._update_prompt()

    def page_scroll(self, delta: int, auto_enter: bool = False) -> bool:
        """Scroll in page mode.

        Args:
            delta: Lines to scroll (negative = up, positive = down)
            auto_enter: Enter page mode if not already active

        Returns:
            True if in page mode and scrolled
        """
        if self._page_cache is None:
            if not auto_enter:
                return False
            app: VerifyApp = self.app  # type: ignore
            if len(self._output_lines) <= app.console_height:
                return False
            self.enter_page_mode()
            if self._page_cache is None:
                return False

        app: VerifyApp = self.app  # type: ignore
        max_index = max(0, len(self._page_cache) - app.console_height)
        self._page_index = max(0, min(max_index, self._page_index + delta))
        output_scroll = self.query_one("#console-output", VerticalScroll)
        output_scroll.scroll_to(y=self._page_index, animate=False)
        return True

    def output_line_count(self) -> int:
        """Return the number of buffered output lines."""
        return len(self._output_lines)

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

    def watch_is_busy(self, busy: bool) -> None:
        """React to busy state changes."""
        self._update_prompt()

    def refresh_prompt(self) -> None:
        """Refresh the input prompt display."""
        self._update_prompt()
