"""Task panel widget for UCAgent TUI."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class TaskPanel(VerticalScroll):
    """Panel displaying mission tasks, changed files, and tool status."""

    REFRESH_INTERVAL_S = 1.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Mission"

    def compose(self) -> ComposeResult:
        """Compose the task panel content."""
        yield Static(id="mission-title", classes="section-title")
        yield Static(id="task-list")
        yield Static("\nChanged Files", classes="section-title")
        yield Static(id="changed-files")
        yield Static("\nTools Call", classes="section-title")
        yield Static(id="tool-status")
        yield Static(id="daemon-cmds")
        yield Static("\nStatus", classes="section-title")
        yield Static(id="status-summary")

    def on_mount(self) -> None:
        self.watch(self.app, "task_width", self._apply_task_width)
        self._apply_task_width(self.app.task_width)
        self.update_content()
        self._refresh_timer = self.set_interval(
            self.REFRESH_INTERVAL_S, self.update_content
        )

    def _apply_task_width(self, value: int) -> None:
        if not self.is_mounted:
            return
        self.styles.width = value

    def update_content(self) -> None:
        """Update panel content from VerifyPDB data."""
        from rich.text import Text

        vpdb = self.app.vpdb
        task_data = vpdb.api_task_list()
        mission_name = task_data.get("mission_name") or task_data.get(
            "task_list", {}
        ).get("mission", "")
        self.query_one("#mission-title", Static).update(mission_name)

        task_lines = self._format_task_lines()
        self.query_one("#task-list", Static).update(
            Text.from_ansi("\n".join(task_lines))
        )

        self._update_changed_files()
        self._update_tool_status()
        self._update_daemon_cmds()
        self._update_status_summary()

    def _format_task_lines(self) -> list[str]:
        mission_info = self.app.vpdb.api_mission_info()
        if not mission_info:
            return []
        return mission_info[1:]

    def _update_changed_files(self) -> None:
        """Update changed files section."""
        from ucagent.util.functions import fmt_time_stamp, fmt_time_deta

        changed_files = self.app.vpdb.api_changed_files()[:5]
        lines = []
        for delta, mtime, filename in changed_files:
            time_str = fmt_time_stamp(mtime)
            if delta < 180:
                time_str += f" ({fmt_time_deta(delta)})"
                lines.append(f"[green]{time_str}: {filename}[/green]")
            else:
                lines.append(f"{time_str}: {filename}")

        self.query_one("#changed-files", Static).update("\n".join(lines))

    def _update_tool_status(self) -> None:
        """Update tool call status."""
        tool_info = []
        for name, count, busy in self.app.vpdb.api_tool_status():
            if busy:
                tool_info.append(f"[yellow]{name}({count})[/yellow]")
            else:
                tool_info.append(f"{name}({count})")

        self.query_one("#tool-status", Static).update(" ".join(tool_info))

    def _update_status_summary(self) -> None:
        """Update status summary section."""
        status_text = self.app.vpdb.api_status()
        self.query_one("#status-summary", Static).update(status_text)

    def _update_daemon_cmds(self) -> None:
        """Update daemon commands section."""
        daemon_cmds = self.app.daemon_cmds
        if not daemon_cmds:
            self.query_one("#daemon-cmds", Static).update("")
            return

        from ucagent.util.functions import fmt_time_stamp, fmt_time_deta

        ntime = time.time()
        lines = ["\nDaemon Commands"]
        for key, cmd in daemon_cmds.items():
            lines.append(
                f"{cmd}: {fmt_time_stamp(key)} - {fmt_time_deta(ntime - key, True)}"
            )

        self.query_one("#daemon-cmds", Static).update("\n".join(lines))
