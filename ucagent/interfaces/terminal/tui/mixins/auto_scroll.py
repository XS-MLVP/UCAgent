"""Auto-scroll mixin for scrollable widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import MouseScrollDown, MouseScrollUp

if TYPE_CHECKING:
    pass


class AutoScrollMixin:
    """Mixin providing auto-scroll behavior with manual override.

    Widgets using this mixin should:
    1. Implement `_get_scrollable()` to return the scrollable widget
    2. Implement `_on_manual_scroll_changed(manual: bool)` for side effects (optional)
    3. Call `_exit_manual_scroll()` from their Esc key binding
    """

    _manual_scroll: bool = False

    def _get_scrollable(self) -> Any:
        raise NotImplementedError

    def _on_manual_scroll_changed(self, manual: bool) -> None:
        pass

    def _enter_manual_scroll(self) -> None:
        if not self._manual_scroll:
            self._manual_scroll = True
            self._get_scrollable().auto_scroll = False
            self._on_manual_scroll_changed(True)

    def _exit_manual_scroll(self) -> None:
        if self._manual_scroll:
            self._manual_scroll = False
            scrollable = self._get_scrollable()
            scrollable.auto_scroll = True
            scrollable.scroll_end()
            self._on_manual_scroll_changed(False)

    def _check_and_restore_auto_scroll(self) -> None:
        scrollable = self._get_scrollable()
        if scrollable.scroll_offset.y >= scrollable.max_scroll_y:
            self._exit_manual_scroll()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._enter_manual_scroll()
        self._get_scrollable().scroll_up()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._enter_manual_scroll()
        self._get_scrollable().scroll_down()
        self._check_and_restore_auto_scroll()
