"""Messages panel widget for UCAgent TUI."""

from __future__ import annotations

import queue
import unicodedata
from collections import deque
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog

from ..mixins import AutoScrollMixin


class MessagesPanel(AutoScrollMixin, RichLog):
    """Scrollable panel for displaying agent messages."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel_scroll", "Cancel scroll", show=False),
        Binding("up", "scroll_messages_up", "Scroll messages up", show=False),
        Binding("down", "scroll_messages_down", "Scroll messages down", show=False),
    ]

    max_messages: int = 1000

    def __init__(self, **kwargs) -> None:
        super().__init__(
            highlight=True,
            markup=True,
            auto_scroll=True,
            wrap=False,
            max_lines=self.max_messages,
            **kwargs,
        )
        self.border_title = "Messages"
        self._render_history: deque[Text] = deque(maxlen=self.max_messages)
        self._batch_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._last_wrap_width: int = 0

    def _get_scrollable(self) -> Any:
        return self

    def _on_manual_scroll_changed(self, manual: bool) -> None:
        self._update_title()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._flush_batch)

    def on_unmount(self) -> None:
        self._flush_batch()

    def on_resize(self, event: events.Resize) -> None:
        new_width = self._current_wrap_width()
        if new_width == self._last_wrap_width:
            return
        self._last_wrap_width = new_width
        self._reflow_history()

    def append_message(self, msg: str) -> None:
        if not msg:
            return
        self._batch_queue.put_nowait(msg)

    def _flush_batch(self) -> None:
        messages: list[str] = []
        try:
            while True:
                messages.append(self._batch_queue.get_nowait())
        except queue.Empty:
            pass

        if messages:
            self._append_payload("".join(messages))

    def _update_title(self) -> None:
        self.border_title = "Messages"

    def _enter_manual_scroll_with_focus(self) -> None:
        if not self._manual_scroll:
            self._enter_manual_scroll()

    def _exit_manual_scroll(self) -> None:
        if self._manual_scroll:
            self._manual_scroll = False
            self.auto_scroll = True
            self.scroll_end()
            self._on_manual_scroll_changed(False)

    def move_focus(self, delta: int) -> None:
        total = len(self.lines)
        if total == 0:
            return

        if not self._manual_scroll:
            self._enter_manual_scroll_with_focus()

        self.scroll_relative(y=delta, animate=True)

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

        text = Text.from_ansi(payload)
        self._render_history.append(text.copy())
        self._write_wrapped_text(text, animate=True)

        self._update_title()

    def _current_wrap_width(self) -> int:
        return max(1, self.scrollable_content_region.width or self.content_region.width)

    def _write_wrapped_text(
            self,
            text: Text,
            *,
            animate: bool,
            scroll_end: bool | None = None,
    ) -> None:
        wrap_width = self._current_wrap_width()
        if wrap_width <= 1:
            self.write(text, animate=animate, scroll_end=scroll_end)
            return

        for wrapped_line in self._soft_wrap_text(text, wrap_width):
            self.write(wrapped_line, animate=animate, scroll_end=scroll_end)

    def _reflow_history(self) -> None:
        if not self._render_history:
            return

        self.clear()
        for text in self._render_history:
            self._write_wrapped_text(text, animate=False, scroll_end=False)

        if not self._manual_scroll:
            self.scroll_end(animate=False)

    @staticmethod
    def _soft_wrap_text(text: Text, width: int) -> list[Text]:
        if width <= 1:
            return [text]

        wrapped: list[Text] = []
        for source_line in text.split(allow_blank=True):
            plain = source_line.plain
            if not plain:
                wrapped.append(source_line)
                continue

            offsets: list[int] = []
            current_width = 0
            for i, ch in enumerate(plain):
                ch_width = MessagesPanel._char_display_width(ch)
                if current_width + ch_width > width and i > 0:
                    offsets.append(i)
                    current_width = ch_width
                else:
                    current_width += ch_width

            if offsets:
                wrapped.extend(source_line.divide(offsets))
            else:
                wrapped.append(source_line)
        return wrapped

    @staticmethod
    def _char_display_width(ch: str) -> int:
        if not ch:
            return 0
        if unicodedata.combining(ch):
            return 0
        if unicodedata.east_asian_width(ch) in {"F", "W"}:
            return 2
        return 1
