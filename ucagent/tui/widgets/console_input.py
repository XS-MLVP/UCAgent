"""Console input widget for UCAgent TUI."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, ClassVar

from rich.spinner import Spinner
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key, MouseDown
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from ..completion import CompletionHandler

if TYPE_CHECKING:
    from ucagent.tui.handlers import KeyHandler


class ConsoleInputField(Input):
    """Input field that can lock editing while a command is running."""

    def _is_locked(self) -> bool:
        node = self.parent
        while node is not None:
            if hasattr(node, "is_busy"):
                return bool(getattr(node, "is_busy", False))
            node = node.parent
        return False

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self._is_locked():
            return None
        return super().check_action(action, parameters)


class BusyIndicator(Widget):
    """Busy indicator using a Rich spinner."""

    def __init__(self, spinner: str = "dots", **kwargs) -> None:
        super().__init__(**kwargs)
        self._spinner = Spinner(spinner)

    def on_mount(self) -> None:
        self.auto_refresh = self._spinner.interval / 1000.0

    def render(self) -> Spinner:
        return self._spinner

    def on_mouse_down(self, event: MouseDown) -> None:
        """Forward focus to the console input when clicked."""
        self.app.query_one("#console-input", Input).focus()
        event.stop()


class ConsoleInput(Vertical):
    """Input and suggestion area for the console."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("shift+left", "clear_input", "Clear input", show=False),
        # Override Screen's default tab bindings with priority to prevent focus switching
        Binding("tab", "handle_tab", "Tab", show=False, priority=True),
        Binding("shift+tab", "handle_shift_tab", "Shift+Tab", show=False, priority=True),
    ]

    class CommandSubmitted(Message):
        """Message sent when a command is submitted."""

        def __init__(self, command: str, daemon: bool = False) -> None:
            super().__init__()
            self.command = command
            self.daemon = daemon

    is_busy: reactive[bool] = reactive(False)

    def __init__(self, prompt: str = "(UnityChip) ", **kwargs) -> None:
        super().__init__(**kwargs)
        self.prompt = prompt
        self._page_mode: bool = False
        self._suggestions_visible: bool = False
        self._suggestions_text: str = ""
        self._completion = CompletionHandler()
        self._busy_command: str | None = None
        self._programmatic_change: bool = False  # Flag to skip clearing on programmatic changes

    def compose(self) -> ComposeResult:
        """Compose the input and suggestion widgets."""
        with Horizontal(id="console-input-row"):
            yield BusyIndicator(id="console-loading")
            yield ConsoleInputField(placeholder=self.prompt, id="console-input")
        yield Static(id="console-suggest")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.is_busy and action == "clear_input":
            return None
        return super().check_action(action, parameters)

    def on_mount(self) -> None:
        """Setup after mounting."""
        self._update_prompt()
        self._hide_suggestions()
        self._set_loading_visible(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command submission."""
        if self.is_busy:
            return
        cmd = event.value.strip()
        input_widget = self.query_one("#console-input", Input)
        input_widget.value = ""
        self.clear_suggestions()

        if not cmd:
            return

        daemon = cmd.endswith("&")
        if daemon:
            cmd = cmd[:-1].strip()

        console = self.parent
        if console is not None and hasattr(console, "append_output"):
            console.append_output(f"{self.prompt}{cmd}\n")

        self.post_message(self.CommandSubmitted(cmd, daemon))

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Clear suggestions when input text changes (e.g., user types space)."""
        if self._programmatic_change:
            self._programmatic_change = False
            return
        if self.has_suggestions:
            self.clear_suggestions()

    async def on_key(self, event: Key) -> None:
        """Handle key events for input behavior.

        Note: Tab/Shift+Tab are handled by priority bindings (action_handle_tab,
        action_handle_shift_tab) to prevent Screen's default focus switching.
        """
        if self.is_busy:
            return

        if event.key == "up":
            self._handle_history_up()
            event.prevent_default()
            event.stop()
        elif event.key == "down":
            self._handle_history_down()
            event.prevent_default()
            event.stop()

    def focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#console-input", Input).focus()

    def input_has_focus(self) -> bool:
        """Return True if the input widget is focused."""
        return self.app.focused is self.query_one("#console-input", Input)

    def clear_input(self) -> None:
        """Clear the input field."""
        self.query_one("#console-input", Input).value = ""

    def action_clear_input(self) -> None:
        """Clear the input field (binding target)."""
        self.clear_input()

    def action_handle_tab(self) -> None:
        """Handle Tab key - tab completion when input focused, otherwise focus input."""
        if self.input_has_focus():
            if not self.is_busy:
                self.handle_tab_completion()
            # When busy, Tab does nothing (prevents accidental focus switch)
        else:
            # Focus the input field instead of cycling focus
            self.focus_input()

    def action_handle_shift_tab(self) -> None:
        """Handle Shift+Tab key - switch focus to previous widget."""
        self.app.action_focus_previous()

    def set_text(self, text: str, move_cursor: bool = True) -> None:
        """Set input text and optionally move cursor to the end."""
        self._programmatic_change = True
        input_widget = self.query_one("#console-input", Input)
        input_widget.value = text
        if move_cursor:
            input_widget.cursor_position = len(text)

    def handle_tab_completion(self) -> None:
        """Handle tab key for command completion."""
        input_widget = self.query_one("#console-input", Input)
        current_text = input_widget.value

        is_cycling = self._completion.state.has_items and self._suggestions_visible
        new_text, suggestions, selected_index = self._completion.handle_tab(
            current_text, self.app.key_handler, is_cycling
        )

        if new_text is not None:
            self.set_text(new_text)

        if suggestions:
            self.show_suggestions(suggestions, selected_index=selected_index)
        else:
            self.clear_suggestions()

    def _handle_history_up(self) -> None:
        """Handle up arrow for command history."""
        console = self.app.query_one("#console")
        if console.page_scroll(1):
            return
        cmd = self.app.key_handler.get_history_item(-1)
        if cmd is not None:
            self.set_text(cmd)

    def _handle_history_down(self) -> None:
        """Handle down arrow for command history."""
        console = self.app.query_one("#console")
        if console.page_scroll(-1):
            return
        cmd = self.app.key_handler.get_history_item(1)
        if cmd is not None:
            self.set_text(cmd)

    def _update_prompt(self) -> None:
        """Update the input prompt based on state."""
        input_widget = self.query_one("#console-input", Input)

        prefix = ""
        if self._page_mode:
            prefix += "<Up/Down: scroll, Esc: exit> "

        input_widget.placeholder = f"{prefix}{self.prompt}"

    def set_busy(self, busy: bool) -> None:
        """Set busy state."""
        self.is_busy = busy
        if busy:
            self.clear_suggestions()
        else:
            self._busy_command = None
        input_widget = self.query_one("#console-input", Input)
        input_widget.set_class(busy, "busy")
        self._set_loading_visible(busy)
        self._update_prompt()
        if busy:
            self._update_running_display(input_widget)
        else:
            input_widget.value = ""

    def set_page_mode(self, enabled: bool) -> None:
        """Set page mode prompt prefix."""
        if self._page_mode == enabled:
            return
        self._page_mode = enabled
        self._update_prompt()

    def refresh_prompt(self) -> None:
        """Refresh the input prompt display."""
        self._update_prompt()
        self._update_running_display()

    def set_running_command(self, command: str | None) -> None:
        """Set the running command shown in the input field."""
        cmd = command.strip() if command else ""
        self._busy_command = cmd if cmd else None
        self._update_running_display()

    @property
    def has_suggestions(self) -> bool:
        return self._suggestions_visible

    def show_suggestions(self, suggestions: list[str], selected_index: int = -1) -> None:
        if not suggestions:
            self.clear_suggestions()
            return
        if 0 <= selected_index < len(suggestions):
            renderable = self._build_suggestion_menu(suggestions, selected_index)
            plain_text = renderable.plain
        else:
            plain_text = " ".join(suggestions)
            renderable = plain_text
        self._suggestions_text = plain_text
        self.query_one("#console-suggest", Static).update(renderable)
        self._show_suggestions()

        extra_lines = self._measure_suggestion_lines(plain_text)
        self._set_console_extra_height(extra_lines)

    def clear_suggestions(self) -> None:
        if not self._suggestions_visible:
            return
        self.query_one("#console-suggest", Static).update("")
        self._hide_suggestions()
        self._set_console_extra_height(0)
        self._completion.reset()

    def _show_suggestions(self) -> None:
        self._suggestions_visible = True
        widget = self.query_one("#console-suggest")
        widget.styles.display = "block"

    def _hide_suggestions(self) -> None:
        self._suggestions_visible = False
        widget = self.query_one("#console-suggest")
        widget.styles.display = "none"

    def _build_suggestion_menu(self, suggestions: list[str], selected_index: int) -> Text:
        text = Text()
        for idx, item in enumerate(suggestions):
            if idx:
                text.append(" ")
            if idx == selected_index:
                text.append(item, style="bold reverse")
            else:
                text.append(item)
        return text

    def _measure_suggestion_lines(self, text: str) -> int:
        width = max(20, self.size.width - 2)
        wrapped = textwrap.wrap(text, width=width)
        return max(1, len(wrapped))

    def _set_console_extra_height(self, extra_lines: int) -> None:
        parent = self.parent
        if parent is not None and hasattr(parent, "set_extra_height"):
            parent.set_extra_height(extra_lines)

    def _set_loading_visible(self, visible: bool) -> None:
        indicator = self.query_one("#console-loading", BusyIndicator)
        indicator.set_class(visible, "is-visible")
        indicator.refresh(layout=True)

    def _update_running_display(self, input_widget: Input | None = None) -> None:
        if not self.is_busy:
            return
        widget = input_widget or self.query_one("#console-input", Input)
        text = self._busy_command or ""
        if widget.value != text:
            widget.value = text
            widget.cursor_position = len(text)
