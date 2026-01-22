"""Task panel widget for UCAgent TUI."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..utils import parse_ansi_to_rich

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class TaskPanel(VerticalScroll):
    """Panel displaying mission tasks, changed files, and tool status."""

    DEFAULT_CSS = """
    TaskPanel {
        border: solid $primary;
        border-title-color: $text;
        border-title-align: center;
    }

    TaskPanel .section-title {
        text-align: center;
        text-style: bold;
        margin: 1 0;
    }

    TaskPanel .task-item {
        padding: 0 1;
    }

    TaskPanel .task-current {
        color: $error;
    }

    TaskPanel .task-completed {
        color: $success;
    }

    TaskPanel .task-skipped {
        color: $warning;
    }

    TaskPanel .file-recent {
        color: $success;
    }

    TaskPanel .tool-busy {
        color: $warning;
    }
    """

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

    def update_content(self, vpdb: "VerifyPDB", daemon_cmds: dict[float, str]) -> None:
        """Update panel content from VerifyPDB data.

        Args:
            vpdb: VerifyPDB instance
            daemon_cmds: Dictionary of daemon commands
        """
        # Update mission info
        mission_info = vpdb.api_mission_info()
        if mission_info:
            self.query_one("#mission-title", Static).update(
                parse_ansi_to_rich(mission_info[0])
            )

            # Build task list
            task_lines = []
            for line in mission_info[1:]:
                task_lines.append(parse_ansi_to_rich(line))
            self.query_one("#task-list", Static).update("\n".join(str(t) for t in task_lines))

        # Update changed files
        self._update_changed_files(vpdb)

        # Update tool status
        self._update_tool_status(vpdb)

        # Update daemon commands
        self._update_daemon_cmds(daemon_cmds)

    def _update_changed_files(self, vpdb: "VerifyPDB") -> None:
        """Update changed files section."""
        from ucagent.util.functions import fmt_time_stamp, fmt_time_deta

        changed_files = vpdb.api_changed_files()[:5]
        lines = []
        for delta, mtime, filename in changed_files:
            time_str = fmt_time_stamp(mtime)
            if delta < 180:
                time_str += f" ({fmt_time_deta(delta)})"
                lines.append(f"[green]{time_str}: {filename}[/green]")
            else:
                lines.append(f"{time_str}: {filename}")

        self.query_one("#changed-files", Static).update("\n".join(lines))

    def _update_tool_status(self, vpdb: "VerifyPDB") -> None:
        """Update tool call status."""
        tool_info = []
        for name, count, busy in vpdb.api_tool_status():
            if busy:
                tool_info.append(f"[yellow]{name}({count})[/yellow]")
            else:
                tool_info.append(f"{name}({count})")

        self.query_one("#tool-status", Static).update(" ".join(tool_info))

    def _update_daemon_cmds(self, daemon_cmds: dict[float, str]) -> None:
        """Update daemon commands section."""
        if not daemon_cmds:
            self.query_one("#daemon-cmds", Static).update("")
            return

        from ucagent.util.functions import fmt_time_stamp, fmt_time_deta

        ntime = time.time()
        lines = ["\nDaemon Commands"]
        for key, cmd in daemon_cmds.items():
            lines.append(f"{cmd}: {fmt_time_stamp(key)} - {fmt_time_deta(ntime - key, True)}")

        self.query_one("#daemon-cmds", Static).update("\n".join(lines))
