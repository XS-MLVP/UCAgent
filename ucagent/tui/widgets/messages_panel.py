"""Messages panel widget for UCAgent TUI."""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog

from rich.text import Text

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

    BATCH_INTERVAL_S = 0.2

    def __init__(
        self,
        message_queue: queue.SimpleQueue[tuple[str, str]],
        **kwargs,
    ) -> None:
        super().__init__(
            highlight=True,
            markup=True,
            auto_scroll=True,
            wrap=True,
            max_lines=self.max_messages,
            **kwargs,
        )
        self.border_title = "Messages"
        self._message_lines: list[str] = []
        self._batch_queue: queue.SimpleQueue[tuple[str, str]] = message_queue
        self._partial_line: str = ""

    def on_mount(self) -> None:
        self._batch_timer = self.set_interval(self.BATCH_INTERVAL_S, self._flush_batch)

    def on_unmount(self) -> None:
        self._flush_batch()

    def append_message(self, msg: str, end: str = "\n") -> None:
        """Append a message with ANSI support. Messages are queued and
        flushed in batches every BATCH_INTERVAL_S seconds.

        Args:
            msg: Message text (may contain ANSI codes)
            end: Line ending character
        """
        if not msg and not end:
            return
        self._batch_queue.put_nowait((msg, end))

    def _flush_batch(self) -> None:
        """Flush all queued messages in one batch."""
        messages: list[tuple[str, str]] = []
        while True:
            try:
                messages.append(self._batch_queue.get_nowait())
            except queue.Empty:
                break

        if not messages:
            return

        combined = "".join(f"{msg}{end}" for msg, end in messages)
        self._append_payload(combined)

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

        payload = f"{self._partial_line}{payload}"

        parts = payload.split("\n")
        complete_lines = parts[:-1]
        new_partial = parts[-1]

        if complete_lines:
            combined = "\n".join(complete_lines)
            self._message_lines.extend(complete_lines)
            if len(self._message_lines) > self.max_messages:
                self._message_lines = self._message_lines[-self.max_messages :]
            self.write(Text.from_ansi(combined))

        self._partial_line = new_partial

        if complete_lines and not self.scroll_mode:
            if self._message_lines:
                self.focus_index = len(self._message_lines) - 1
            else:
                self.focus_index = 0

        if complete_lines:
            self._update_title()
        elif self.scroll_mode:
            self._update_title()
