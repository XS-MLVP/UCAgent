"""Status bar widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Static

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class StatusBar(Static):
    """Bottom status bar showing key runtime info."""

    REFRESH_INTERVAL_S = 1.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw_text: str = ""

    def on_mount(self) -> None:
        self.update_content()
        self._refresh_timer = self.set_interval(
            self.REFRESH_INTERVAL_S, self.update_content
        )


    def update_content(self) -> None:
        """Update status bar content."""
        vpdb = self.app.vpdb
        stats = vpdb.agent.status_info()
        backend_type = vpdb.agent.cfg.get_value("backend.key_name", "unknown")

        fields = [
            ("Run Time", stats.get("Run Time", "-")),
            ("Model", stats.get("LLM", "-")),
            ("Backend", backend_type),
            ("Stream", stats.get("Stream", "-")),
            ("Mode", stats.get("Interaction Mode", "-")),
        ]

        parts = [f"{label}: {self._format_value(value)}" for label, value in fields]
        raw = " | ".join(parts)
        self._raw_text = raw
        self.update(self._truncate_to_width(raw))

    def on_resize(self, event: events.Resize) -> None:
        if self._raw_text:
            self.update(self._truncate_to_width(self._raw_text))

    def _truncate_to_width(self, text: str) -> str:
        width = self.size.width
        if width <= 0 or len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return text[: width - 3] + "..."

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)
