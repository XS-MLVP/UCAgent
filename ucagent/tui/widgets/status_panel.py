"""Status panel widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import VerticalScroll

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class StatusPanel(VerticalScroll):
    """Panel displaying current agent status."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Status"

    def compose(self) -> ComposeResult:
        """Compose the status panel."""
        yield Static(id="status-content")

    def on_mount(self) -> None:
        self.watch(self.app, "status_height", self._apply_status_height)
        self._apply_status_height(self.app.status_height)

    def _apply_status_height(self, value: int) -> None:
        if not self.is_mounted:
            return
        self.styles.height = value

    def update_content(self, vpdb: "VerifyPDB", layout_info: tuple[int, int, int]) -> None:
        """Update status content.

        Args:
            vpdb: VerifyPDB instance
            layout_info: Tuple of (task_width, console_height, status_height)
        """
        status_text = vpdb.api_status()
        w_task, h_console, h_status = layout_info
        full_status = f"{status_text}\nWHH({w_task},{h_console},{h_status})"

        self.query_one("#status-content", Static).update(full_status)
