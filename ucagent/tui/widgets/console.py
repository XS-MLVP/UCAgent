"""Console widget for UCAgent TUI."""

from __future__ import annotations

import queue
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog

from rich.text import Text

from ..mixins import AutoScrollMixin
from .console_input import ConsoleInput


class ConsoleWidget(AutoScrollMixin, Vertical):
    """Console widget with output display and input area."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "exit_page_mode", "Exit page mode", show=False),
        Binding("pageup", "console_page_prev", "Console page prev", show=False),
        Binding("pagedown", "console_page_next", "Console page next", show=False),
        Binding("shift+right", "clear_console", "Clear console", show=False),
    ]

    REFRESH_INTERVAL_S = 0.2

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Console"
        self._prompt = prompt
        self._extra_height: int = 0
        self._batch_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="console-output",
            max_lines=1000,
            auto_scroll=True,
            wrap=True,
            markup=False,
            highlight=False,
        )
        yield ConsoleInput(prompt=self._prompt)

    def _get_scrollable(self) -> Any:
        return self.query_one("#console-output", RichLog)

    def _on_manual_scroll_changed(self, manual: bool) -> None:
        self.query_one(ConsoleInput).set_page_mode(manual)

    def on_mount(self) -> None:
        self.watch(self.app, "console_height", self._apply_console_height)
        self._apply_console_height(self.app.console_height)
        self._auto_update()
        self._refresh_timer = self.set_interval(
            self.REFRESH_INTERVAL_S, self._auto_update
        )
        self._batch_timer = self.set_interval(
            self.REFRESH_INTERVAL_S, self._flush_batch
        )

    def _auto_update(self) -> None:
        if hasattr(self.app, "_console_capture"):
            self.app.flush_console_output()
        self.refresh_prompt()

    def _apply_console_height(self, value: int) -> None:
        if not self.is_mounted:
            return
        self.styles.height = value + self._extra_height

    def set_extra_height(self, extra_lines: int) -> None:
        self._extra_height = max(0, extra_lines)
        if not self.is_mounted:
            return
        self.styles.height = self.app.console_height + self._extra_height

    def queue_output(self, text: str) -> None:
        if not text:
            return
        self._batch_queue.put_nowait(text)

    def _flush_batch(self) -> None:
        texts: list[str] = []
        while True:
            try:
                texts.append(self._batch_queue.get_nowait())
            except queue.Empty:
                break

        if not texts:
            return

        combined = "".join(texts)
        self.append_output(combined)

    def append_output(self, text: str) -> None:
        if not text:
            return

        processed = text.replace("\t", "    ")
        processed = processed.replace("\r\n", "\n").replace("\r", "\n")

        output_log = self.query_one("#console-output", RichLog)

        lines = processed.split("\n")
        for i, line in enumerate(lines):
            if i == len(lines) - 1 and not line:
                continue
            output_log.write(Text.from_ansi(line))

    def clear_output(self) -> None:
        output_log = self.query_one("#console-output", RichLog)
        output_log.clear()
        self._exit_manual_scroll()

    def action_clear_console(self) -> None:
        self.clear_output()

    def page_scroll(self, delta: int, auto_enter: bool = False) -> bool:
        if not self._manual_scroll:
            if not auto_enter:
                return False
            self._enter_manual_scroll()

        output_log = self.query_one("#console-output", RichLog)
        output_log.scroll_relative(y=delta, animate=False)

        if delta > 0:
            self._check_and_restore_auto_scroll()

        return True

    def action_console_page_prev(self) -> None:
        delta = -self.app.console_height
        self.page_scroll(delta, auto_enter=True)

    def action_console_page_next(self) -> None:
        delta = self.app.console_height
        self.page_scroll(delta, auto_enter=True)

    def action_exit_page_mode(self) -> None:
        self._exit_manual_scroll()

    def output_line_count(self) -> int:
        output_log = self.query_one("#console-output", RichLog)
        return len(output_log.lines)

    def set_busy(self, busy: bool) -> None:
        self.query_one(ConsoleInput).set_busy(busy)

    def set_running_command(self, command: str | None) -> None:
        self.query_one(ConsoleInput).set_running_command(command)

    def refresh_prompt(self) -> None:
        self.query_one(ConsoleInput).refresh_prompt()
