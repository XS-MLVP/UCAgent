"""Messages panel widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog

from ..utils import parse_ansi_to_rich

if TYPE_CHECKING:
    pass


class MessagesPanel(RichLog):
    """Scrollable panel for displaying agent messages."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel_scroll", "Cancel scroll", show=False),
        Binding("up", "scroll_messages_up", "Scroll messages up", show=False),
        Binding("down", "scroll_messages_down", "Scroll messages down", show=False),
    ]

    # Maximum number of messages to keep
    max_messages: int = 1000

    focus_index: reactive[int] = reactive(0)
    scroll_mode: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(
            highlight=True,
            markup=True,
            auto_scroll=True,
            wrap=True,
            max_lines=self.max_messages,
            **kwargs
        )
        self.border_title = "Messages"
        self._scroll_buffer: str = ""
        self._message_lines: list[str] = []

    def append_message(self, msg: str, end: str = "\n") -> None:
        """Append a message with ANSI support.

        Args:
            msg: Message text (may contain ANSI codes)
            end: Line ending character
        """
        if not msg and not end:
            return

        payload = f"{msg}{end}"

        if self.scroll_mode:
            self._scroll_buffer += payload
            max_buffer_size = 1024 * self.max_messages
            if len(self._scroll_buffer) > max_buffer_size:
                self._scroll_buffer = self._scroll_buffer[-max_buffer_size:]
            return

        if self._scroll_buffer:
            payload = self._scroll_buffer + payload
            self._scroll_buffer = ""

        self._append_payload(payload)

    def flush_buffer(self) -> None:
        """Flush any buffered messages when exiting scroll mode."""
        if self._scroll_buffer:
            payload = self._scroll_buffer
            self._scroll_buffer = ""
            self._append_payload(payload)

    def _update_title(self) -> None:
        """Update the border title with message count."""
        total = len(self._message_lines)
        if total == 0:
            self.border_title = "Messages (0)"
            return
        if self.scroll_mode:
            self.border_title = f"Messages ({self.focus_index + 1}/{total})"
        else:
            self.border_title = f"Messages ({total})"

    def scroll_to_end(self) -> None:
        """Scroll to the end and exit scroll mode."""
        self.scroll_mode = False
        self.auto_scroll = True
        self.flush_buffer()
        if self._message_lines:
            self.focus_index = len(self._message_lines) - 1
        super().scroll_end(animate=False)
        self._update_title()

    def move_focus(self, delta: int) -> None:
        """Move focus in scroll mode.

        Args:
            delta: Lines to move (negative = up, positive = down)
        """
        total = len(self._message_lines)
        if not self.scroll_mode:
            self.scroll_mode = True
            self.auto_scroll = False
            if total:
                self.focus_index = total - 1

        if total == 0:
            return

        old_index = min(self.focus_index, total - 1)
        new_index = max(0, min(total - 1, old_index + delta))
        if new_index == old_index:
            return
        self.focus_index = new_index
        self._update_title()

        # Scroll by delta to ensure immediate visual feedback.
        self.scroll_relative(y=new_index - old_index, animate=False)

    def action_scroll_messages_up(self) -> None:
        """Scroll messages up (binding target)."""
        self.move_focus(-1)

    def action_scroll_messages_down(self) -> None:
        """Scroll messages down (binding target)."""
        self.move_focus(1)

    def action_cancel_scroll(self) -> None:
        """Exit scroll mode and jump to end (binding target)."""
        if self.scroll_mode:
            self.scroll_to_end()

    def _append_payload(self, payload: str) -> None:
        if not payload:
            return

        lines = payload.split("\n")

        updated_last = False
        if self._message_lines:
            self._message_lines[-1] += lines[0]
            updated_last = True
            lines = lines[1:]

        self._message_lines.extend(lines)

        if len(self._message_lines) > self.max_messages:
            self._message_lines = self._message_lines[-self.max_messages:]

        if updated_last:
            self._render_lines()
        else:
            for line in lines:
                self.write(parse_ansi_to_rich(line))

        if not self.scroll_mode:
            if self._message_lines:
                self.focus_index = len(self._message_lines) - 1
            else:
                self.focus_index = 0
            super().scroll_end(animate=False)
        self._update_title()

    def _render_lines(self) -> None:
        self.clear()
        for line in self._message_lines:
            self.write(parse_ansi_to_rich(line))
