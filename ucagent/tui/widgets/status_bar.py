"""Status bar widget for UCAgent TUI."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class StatusBar(Horizontal):
    """Bottom status bar showing key runtime info."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw_text: str = ""

    def compose(self) -> ComposeResult:
        yield Static(id="status-left")
        yield Static("F1 for shortcuts", id="status-hint")

    def on_mount(self) -> None:
        self.update_content()
        self.set_interval(1.0, self.update_content)

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
        left = " | ".join(parts)
        self._raw_text = left
        self.query_one("#status-left", Static).update(self._truncate_left(left))

    def on_resize(self, event: events.Resize) -> None:
        if self._raw_text:
            self.query_one("#status-left", Static).update(
                self._truncate_left(self._raw_text)
            )

    def _truncate_left(self, text: str) -> str:
        """Truncate left status text to available width."""
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
