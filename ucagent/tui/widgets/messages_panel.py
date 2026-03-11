"""Messages panel widget for UCAgent TUI."""

from __future__ import annotations

import queue
import unicodedata
from collections import deque
from typing import Any, ClassVar

from rich.segment import Segment
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.cache import LRUCache
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..mixins import AutoScrollMixin


class MessagesPanel(AutoScrollMixin, ScrollView, can_focus=True):
    """Scrollable panel for displaying agent messages with inline append support."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel_scroll", "Cancel scroll", show=False),
        Binding("up", "scroll_messages_up", "Scroll messages up", show=False),
        Binding("down", "scroll_messages_down", "Scroll messages down", show=False),
    ]

    auto_scroll: bool = True  # Required by AutoScrollMixin
    max_messages: int = 1000

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Messages"

        # Rendering state
        self._lines: list[Strip] = []  # Finalized rendered lines
        self._line_cache: LRUCache = LRUCache(1024)
        self._render_history: deque[Text] = deque(maxlen=self.max_messages)

        # Batch queue (thread-safe)
        self._batch_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

        # Inline append state
        self._current_line_buffer: str = ""  # Raw string accumulator
        self._pending_strips: list[Strip] = []  # Strips for current incomplete line

        # Layout state
        self._last_wrap_width: int = 0
        self._widest_line_width: int = 0
        self._start_line: int = 0  # For line pruning

        # Deferred rendering
        self._size_known: bool = False
        self._deferred_payloads: list[str] = []

    def render_line(self, y: int) -> Strip:
        """Render a line of content (ScrollView contract)."""
        scroll_x, scroll_y = self.scroll_offset
        content_y = scroll_y + y

        # Total lines = finalized + pending
        total_finalized = len(self._lines)
        total_pending = len(self._pending_strips)
        total_lines = total_finalized + total_pending

        if content_y >= total_lines:
            width = self.scrollable_content_region.width
            return Strip.blank(width, self.rich_style)

        # Check cache
        key = (
            content_y + self._start_line,
            scroll_x,
            self.scrollable_content_region.width,
            self._widest_line_width,
        )
        if key in self._line_cache:
            return self._line_cache[key].apply_style(self.rich_style)

        # Get line: finalized or pending
        if content_y < total_finalized:
            line = self._lines[content_y]
        else:
            pending_index = content_y - total_finalized
            line = self._pending_strips[pending_index]

        # Crop and cache
        width = self.scrollable_content_region.width
        cropped = line.crop_extend(scroll_x, scroll_x + width, self.rich_style)
        self._line_cache[key] = cropped
        return cropped.apply_style(self.rich_style)

    def _render_text_to_strips(self, text: Text) -> list[Strip]:
        """Convert Rich Text to Strip objects."""
        if not self.app or not self.app.console:
            return [Strip.blank(1)]

        width = max(1, self.scrollable_content_region.width or 80)
        render_options = self.app.console.options.update(
            overflow="ignore",
            no_wrap=True,
            width=width,
        )

        segments = self.app.console.render(text, render_options)
        lines = list(Segment.split_lines(segments))
        strips = Strip.from_lines(lines)

        return strips if strips else [Strip.blank(width)]

    def _get_scrollable(self) -> Any:
        return self

    def _on_manual_scroll_changed(self, manual: bool) -> None:
        self._update_title()

    def on_mount(self) -> None:
        """Initialize periodic batch flushing."""
        self.set_interval(0.2, self._flush_batch)
        self._size_known = True

        # Flush any deferred payloads
        if self._deferred_payloads:
            for payload in self._deferred_payloads:
                self._process_payload(payload)
            self._deferred_payloads.clear()

    def on_unmount(self) -> None:
        """Final batch flush on unmount."""
        self._flush_batch()

    def on_resize(self, event: events.Resize) -> None:
        """Handle resize and reflow."""
        new_width = max(1, self.scrollable_content_region.width or 80)
        if new_width == self._last_wrap_width:
            return
        self._last_wrap_width = new_width

        # Mark size as known on first resize
        if not self._size_known:
            self._size_known = True
            for deferred in self._deferred_payloads:
                self._process_payload(deferred)
            self._deferred_payloads.clear()

        self._reflow_history()

    def append_message(self, msg: str) -> None:
        """Thread-safe message append."""
        if not msg:
            return
        self._batch_queue.put_nowait(msg)

    def _flush_batch(self) -> None:
        """Drain batch queue and process messages."""
        messages: list[str] = []
        try:
            while True:
                messages.append(self._batch_queue.get_nowait())
        except queue.Empty:
            pass

        if not messages:
            return

        payload = "".join(messages)
        if not payload:
            return

        if not self._size_known:
            self._deferred_payloads.append(payload)
            return

        self._process_payload(payload)

    def _process_payload(self, payload: str) -> None:
        """Process payload with inline append logic.

        Adapted from verify_ui.py:288-301 algorithm:
        - Split by newline
        - First segment appends to current buffer
        - Subsequent segments finalize current line and start new
        """
        segments = payload.split("\n")
        for i, segment in enumerate(segments):
            if i == 0:
                # First segment: append to current incomplete line
                self._current_line_buffer += segment
            else:
                # Newline encountered: finalize current line, start new
                self._finalize_current_line()
                self._current_line_buffer = segment

        # Re-render the current incomplete line
        self._update_pending_line()

        # Update virtual size
        total_lines = len(self._lines) + len(self._pending_strips)
        self.virtual_size = Size(self._widest_line_width, total_lines)

        if self.auto_scroll:
            self.scroll_end(animate=False)

        self.refresh()

    def _finalize_current_line(self) -> None:
        """Finalize the current line buffer into permanent lines."""
        if not self._current_line_buffer:
            # Empty line — still track in history for proper pruning
            was_full = len(self._render_history) == self.max_messages
            self._render_history.append(Text(""))
            width = max(1, self.scrollable_content_region.width or 80)
            self._lines.append(Strip.blank(width))
            # Trigger pruning if deque was full (oldest entry was dropped)
            if was_full:
                self._start_line += 1
                self._reflow_history()
        else:
            # Parse ANSI, add to history, soft-wrap, render
            text = Text.from_ansi(self._current_line_buffer)
            was_full = len(self._render_history) == self.max_messages
            self._render_history.append(text.copy())

            wrap_width = max(1, self.scrollable_content_region.width or 80)
            wrapped = self._soft_wrap_text(text, wrap_width)

            for wrapped_text in wrapped:
                strips = self._render_text_to_strips(wrapped_text)
                self._lines.extend(strips)
                for strip in strips:
                    self._widest_line_width = max(
                        self._widest_line_width, strip.cell_length
                    )

            # Trigger pruning if deque was full (oldest entry was dropped)
            if was_full:
                self._start_line += 1
                self._reflow_history()

        self._current_line_buffer = ""
        self._pending_strips = []
        self._line_cache.clear()

    def _update_pending_line(self) -> None:
        """Render the current incomplete line as pending strips."""
        if not self._current_line_buffer:
            self._pending_strips = []
            return

        text = Text.from_ansi(self._current_line_buffer)
        wrap_width = max(1, self.scrollable_content_region.width or 80)
        wrapped = self._soft_wrap_text(text, wrap_width)

        self._pending_strips = []
        for wrapped_text in wrapped:
            strips = self._render_text_to_strips(wrapped_text)
            self._pending_strips.extend(strips)

        # Invalidate cache for pending line positions
        self._line_cache.clear()

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
        total = len(self._lines) + len(self._pending_strips)
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

    def _reflow_history(self) -> None:
        """Rebuild lines from render history."""
        if not self._render_history:
            return

        was_manual = self._manual_scroll
        self._lines.clear()
        self._line_cache.clear()
        self._widest_line_width = 0

        wrap_width = max(1, self.scrollable_content_region.width or 80)
        for text in self._render_history:
            wrapped = self._soft_wrap_text(text, wrap_width)
            for wrapped_text in wrapped:
                strips = self._render_text_to_strips(wrapped_text)
                self._lines.extend(strips)
                for strip in strips:
                    self._widest_line_width = max(
                        self._widest_line_width, strip.cell_length
                    )

        total_lines = len(self._lines) + len(self._pending_strips)
        self.virtual_size = Size(self._widest_line_width, total_lines)

        if not was_manual:
            self.scroll_end(animate=False)

        self.refresh()

    def clear(self) -> None:
        """Clear all content."""
        self._lines.clear()
        self._line_cache.clear()
        self._current_line_buffer = ""
        self._pending_strips = []
        self._start_line = 0
        self._widest_line_width = 0
        self._render_history.clear()
        self.virtual_size = Size(0, 0)
        self.refresh()

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
