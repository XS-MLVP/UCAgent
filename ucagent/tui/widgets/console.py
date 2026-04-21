"""Console widget for UCAgent TUI."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Any, ClassVar

from rich.box import SQUARE
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog

from .console_input import ConsoleInput
from ..mixins import AutoScrollMixin


@dataclass
class ConsoleEntry:
    kind: str
    payload: str


@dataclass
class ConsoleWidgetState:
    entries: list[ConsoleEntry]


class ConsoleWidget(AutoScrollMixin, Vertical):
    """Console widget with output display and input area."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "exit_page_mode", "Exit page mode", show=False),
        Binding("pageup", "console_page_prev", "Console page prev", show=False),
        Binding("pagedown", "console_page_next", "Console page next", show=False),
        Binding("shift+right", "clear_console", "Clear console", show=False),
    ]

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Console"
        self._prompt = prompt
        self._extra_height: int = 0
        self._batch_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._entries: list[ConsoleEntry] = []

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
        self._tick()
        self.set_interval(0.2, self._tick)

    def _tick(self) -> None:
        self._flush_batch()
        self._auto_update()

    def _auto_update(self) -> None:
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

    def export_state(self) -> ConsoleWidgetState:
        self._flush_batch()
        return ConsoleWidgetState(
            entries=[ConsoleEntry(entry.kind, entry.payload) for entry in self._entries]
        )

    def restore_state(self, state: ConsoleWidgetState | None) -> None:
        self.clear_output(sync_to_vpdb=False)
        if state is None:
            return

        for entry in state.entries:
            if entry.kind == "command":
                self._write_command(entry.payload, record=True, sync_to_vpdb=False)
            elif entry.kind == "output":
                self._write_output(entry.payload, record=True, sync_to_vpdb=False)

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

    def append_output(self, text: str, *, sync_to_vpdb: bool = True) -> None:
        self._write_output(text, record=True, sync_to_vpdb=sync_to_vpdb)

    def _write_output(
            self,
            text: str,
            *,
            record: bool,
            sync_to_vpdb: bool,
    ) -> None:
        if not text:
            return
        if record:
            if self._entries and self._entries[-1].kind == "output":
                self._entries[-1].payload += text
            else:
                self._entries.append(ConsoleEntry("output", text))
        if sync_to_vpdb:
            vpdb = getattr(self.app, "vpdb", None)
            if vpdb is not None and hasattr(vpdb, "record_console_output"):
                vpdb.record_console_output(text)

        processed = text.replace("\t", "    ")
        processed = processed.replace("\r\n", "\n").replace("\r", "\n")

        output_log = self.query_one("#console-output", RichLog)

        lines = processed.split("\n")
        for i, line in enumerate(lines):
            if i == len(lines) - 1 and not line:
                continue
            output_log.write(Text.from_ansi(line))

    def echo_command(self, cmd: str, *, sync_to_vpdb: bool = True) -> None:
        self._write_command(cmd, record=True, sync_to_vpdb=sync_to_vpdb)

    def _write_command(
            self,
            cmd: str,
            *,
            record: bool,
            sync_to_vpdb: bool,
    ) -> None:
        if record:
            self._entries.append(ConsoleEntry("command", cmd))
        if sync_to_vpdb:
            vpdb = getattr(self.app, "vpdb", None)
            if vpdb is not None and hasattr(vpdb, "record_console_command"):
                vpdb.record_console_command(cmd)
        output_log = self.query_one("#console-output", RichLog)
        t = Text(f"> {cmd}", style="bold")
        output_log.write(
            Panel(
                t,
                box=SQUARE,
                border_style="dim",
                padding=(0, 1),
                expand=True,
            )
        )

    def clear_output(self, *, sync_to_vpdb: bool = True) -> None:
        output_log = self.query_one("#console-output", RichLog)
        output_log.clear()
        self._entries.clear()
        self._exit_manual_scroll()
        if sync_to_vpdb:
            vpdb = getattr(self.app, "vpdb", None)
            if vpdb is not None and hasattr(vpdb, "clear_console_state"):
                vpdb.clear_console_state()

    def action_clear_console(self) -> None:
        self.clear_output()

    def page_scroll(self, delta: int, auto_enter: bool = False) -> bool:
        if not self._manual_scroll:
            if not auto_enter:
                return False
            self._enter_manual_scroll()

        output_log = self.query_one("#console-output", RichLog)
        output_log.scroll_relative(y=delta)

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

    def refresh_prompt(self) -> None:
        self.query_one(ConsoleInput).refresh_prompt()
