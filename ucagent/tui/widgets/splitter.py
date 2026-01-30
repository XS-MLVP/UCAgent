"""Splitter widgets for mouse-based resizing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Static

if TYPE_CHECKING:
    pass


class VerticalSplitter(Static):
    """Draggable vertical splitter to resize columns."""

    def __init__(self, target: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._target = target
        self._dragging = False
        self._start_pos = 0
        self._start_value = 0

    def on_mount(self) -> None:
        self._refresh_line()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_line()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        self._start_pos = event.screen_x
        self._start_value = getattr(self.app, self._target)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        current = event.screen_x
        delta = current - self._start_pos
        new_value = self._start_value + delta
        new_value = _clamp_split_value(self._target, new_value)
        setattr(self.app, self._target, new_value)

    def _refresh_line(self) -> None:
        height = max(1, self.size.height)
        self.update("\n".join([" "] * height))


class HorizontalSplitter(Static):
    """Draggable horizontal splitter to resize rows."""

    def __init__(self, target: str, invert: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._target = target
        self._invert = invert
        self._dragging = False
        self._start_pos = 0
        self._start_value = 0

    def on_mount(self) -> None:
        self._refresh_line()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_line()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        self._start_pos = event.screen_y
        self._start_value = getattr(self.app, self._target)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        current = event.screen_y
        delta = current - self._start_pos
        if self._invert:
            delta = -delta
        new_value = self._start_value + delta
        new_value = _clamp_split_value(self._target, new_value)
        setattr(self.app, self._target, new_value)

    def _refresh_line(self) -> None:
        width = max(1, self.size.width)
        self.update(" " * width)


def _clamp_split_value(target: str, value: int) -> int:
    """Clamp split value with only minimum constraints."""
    value = int(value)
    if target == "task_width":
        return max(10, value)
    if target == "status_height":
        return max(3, value)
    if target == "console_height":
        return max(3, value)
    return value
