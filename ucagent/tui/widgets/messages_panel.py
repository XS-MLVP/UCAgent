"""Messages panel widget for UCAgent TUI."""

from __future__ import annotations

import queue
from typing import Any, ClassVar

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog

from rich.text import Text

from ..mixins import AutoScrollMixin


class MessagesPanel(AutoScrollMixin, RichLog):
    """Scrollable panel for displaying agent messages."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel_scroll", "Cancel scroll", show=False),
        Binding("up", "scroll_messages_up", "Scroll messages up", show=False),
        Binding("down", "scroll_messages_down", "Scroll messages down", show=False),
    ]

    max_messages: int = 1000

    focus_index: reactive[int] = reactive(0)

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

    def _get_scrollable(self) -> Any:
        return self

    def _on_manual_scroll_changed(self, manual: bool) -> None:
        self._update_title()

    def on_mount(self) -> None:
        self._batch_timer = self.set_interval(self.BATCH_INTERVAL_S, self._flush_batch)

    def on_unmount(self) -> None:
        self._flush_batch()

    def append_message(self, msg: str, end: str = "\n") -> None:
        if not msg and not end:
            return
        self._batch_queue.put_nowait((msg, end))

    def _flush_batch(self) -> None:
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
        total = len(self._message_lines)
        if total == 0:
            self.border_title = "Messages (0)"
            return
        if self._manual_scroll:
            self.border_title = f"Messages ({self.focus_index + 1}/{total})"
        else:
            self.border_title = f"Messages ({total})"

    def _enter_manual_scroll_with_focus(self) -> None:
        if not self._manual_scroll:
            self._enter_manual_scroll()
            total = len(self._message_lines)
            if total:
                self.focus_index = total - 1

    def _exit_manual_scroll(self) -> None:
        if self._manual_scroll:
            self._manual_scroll = False
            self.auto_scroll = True
            if self._message_lines:
                self.focus_index = len(self._message_lines) - 1
            self.scroll_end(animate=False)
            self._on_manual_scroll_changed(False)

    def move_focus(self, delta: int) -> None:
        total = len(self._message_lines)
        if not self._manual_scroll:
            self._enter_manual_scroll_with_focus()

        if total == 0:
            return

        old_index = min(self.focus_index, total - 1)
        new_index = max(0, min(total - 1, old_index + delta))
        if new_index == old_index:
            return
        self.focus_index = new_index
        self._update_title()

        self.scroll_relative(y=new_index - old_index, animate=False)

        if delta > 0:
            self._check_and_restore_auto_scroll()

    def action_scroll_messages_up(self) -> None:
        self.move_focus(-1)

    def action_scroll_messages_down(self) -> None:
        self.move_focus(1)

    def action_cancel_scroll(self) -> None:
        self._exit_manual_scroll()

    def on_mouse_scroll_up(self, event) -> None:
        self._enter_manual_scroll_with_focus()
        self._update_title()
        self.scroll_up()

    def on_mouse_scroll_down(self, event) -> None:
        self._enter_manual_scroll_with_focus()
        self._update_title()
        self.scroll_down()
        self._check_and_restore_auto_scroll()

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

        if complete_lines and not self._manual_scroll:
            if self._message_lines:
                self.focus_index = len(self._message_lines) - 1
            else:
                self.focus_index = 0

        if complete_lines:
            self._update_title()
        elif self._manual_scroll:
            self._update_title()
