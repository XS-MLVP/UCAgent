"""Console widget for UCAgent TUI."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog

from .console_input import ConsoleInput
from ..utils import parse_ansi_to_rich


class ConsoleWidget(Vertical):
    """Console widget with output display and input area."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("pageup", "console_page_prev", "Console page prev", show=False),
        Binding("pagedown", "console_page_next", "Console page next", show=False),
        Binding("shift+right", "clear_console", "Clear console", show=False),
    ]

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Console"
        self._page_mode: bool = False
        self._prompt = prompt
        self._extra_height: int = 0

    def compose(self) -> ComposeResult:
        """Compose the console widget."""
        yield RichLog(
            id="console-output",
            max_lines=1000,
            auto_scroll=True,
            wrap=True,
            markup=False,
            highlight=False,
        )
        yield ConsoleInput(prompt=self._prompt)

    def on_mount(self) -> None:
        self.watch(self.app, "console_height", self._apply_console_height)
        self._apply_console_height(self.app.console_height)

    def _apply_console_height(self, value: int) -> None:
        if not self.is_mounted:
            return
        self.styles.height = value + self._extra_height

    def set_extra_height(self, extra_lines: int) -> None:
        self._extra_height = max(0, extra_lines)
        if not self.is_mounted:
            return
        self.styles.height = self.app.console_height + self._extra_height

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
        self.exit_page_mode()

    def action_clear_console(self) -> None:
        """Clear console output (binding target)."""
        self.clear_output()

    def enter_page_mode(self) -> None:
        """Enter paginated output mode."""
        if not self._page_mode:
            self._page_mode = True
            output_log = self.query_one("#console-output", RichLog)
            output_log.auto_scroll = False
            self.query_one(ConsoleInput).set_page_mode(True)

    def exit_page_mode(self) -> None:
        """Exit paginated output mode."""
        if self._page_mode:
            self._page_mode = False
            output_log = self.query_one("#console-output", RichLog)
            output_log.auto_scroll = True
            output_log.scroll_end(animate=False)
            self.query_one(ConsoleInput).set_page_mode(False)

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
        output_log.scroll_relative(y=delta, animate=False)

        return True

    def action_console_page_prev(self) -> None:
        """Scroll console output up by a page."""
        delta = -self.app.console_height
        self.page_scroll(delta, auto_enter=True)

    def action_console_page_next(self) -> None:
        """Scroll console output down by a page."""
        delta = self.app.console_height
        self.page_scroll(delta, auto_enter=True)

    def output_line_count(self) -> int:
        """Return the number of buffered output lines."""
        output_log = self.query_one("#console-output", RichLog)
        return len(output_log.lines)

    def set_busy(self, busy: bool) -> None:
        """Set busy state."""
        self.query_one(ConsoleInput).set_busy(busy)

    def set_running_command(self, command: str | None) -> None:
        """Set the running command shown in the input field."""
        self.query_one(ConsoleInput).set_running_command(command)

    def refresh_prompt(self) -> None:
        """Refresh the input prompt display."""
        self.query_one(ConsoleInput).refresh_prompt()
