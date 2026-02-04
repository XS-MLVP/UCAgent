"""Status bar widget for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar showing key runtime info."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw_text: str = ""
        self._hint: str = ""

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
        hint = "F1 for shortcuts"
        self._raw_text = left
        self._hint = hint
        self.update(self._layout_with_hint(left, hint))

    def on_resize(self, event: events.Resize) -> None:
        if self._raw_text:
            self.update(self._layout_with_hint(self._raw_text, self._hint))

    def _layout_with_hint(self, left: str, hint: str) -> str:
        """Layout left-aligned status with right-aligned hint."""
        width = self.size.width
        if width <= 0:
            return left
        total_len = len(left) + len(hint) + 2  # 2 for minimum gap
        if total_len > width:
            # Truncate left part to make room for hint
            available = width - len(hint) - 2
            if available < 10:
                # Not enough room, just show what fits
                return left[:width] if len(left) <= width else left[: width - 3] + "..."
            left = left[: available - 3] + "..." if len(left) > available else left
        gap = width - len(left) - len(hint)
        return left + " " * gap + hint

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
