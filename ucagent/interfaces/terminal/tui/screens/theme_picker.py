"""Theme picker modal screen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static


class ThemePickerScreen(ModalScreen[str | None]):
    """Modal screen for selecting a theme."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "accept", "Accept theme", show=False),
    ]

    def __init__(self, themes: list[str], current: str | None = None) -> None:
        super().__init__()
        self._themes = themes
        self._current = current
        self._original_theme = current
        self._ready = False

    def compose(self) -> ComposeResult:
        option_list = OptionList(*self._themes, id="theme-picker-options")
        yield Vertical(
            Static("Select theme", id="theme-picker-title"),
            option_list,
            id="theme-picker",
        )

    def on_mount(self) -> None:
        if self._original_theme is None:
            self._original_theme = self.app.theme
        option_list = self.query_one(OptionList)
        option_list.focus()
        if self._current in self._themes:
            option_list.highlighted = self._themes.index(self._current)
        self._ready = True

    def on_option_list_option_highlighted(
            self, event: OptionList.OptionHighlighted
    ) -> None:
        if not self._ready:
            return
        theme_name = self._themes[event.option_index]
        if theme_name in self.app.available_themes:
            self.app.theme = theme_name

    def on_option_list_option_selected(
            self, event: OptionList.OptionSelected
    ) -> None:
        theme_name = self._themes[event.option_index]
        self.dismiss(theme_name)

    def action_cancel(self) -> None:
        if self._original_theme in self.app.available_themes:
            self.app.theme = self._original_theme
        self.dismiss(None)

    def action_accept(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None:
            self.dismiss(None)
            return
        theme_name = self._themes[option_list.highlighted]
        self.dismiss(theme_name)
