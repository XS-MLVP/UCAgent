"""Main application for UCAgent TUI."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import HelpPanel

from .handlers import KeyHandler
from .mixins import ConsoleCaptureMixin, SigintHandlerMixin
from .screens import ThemePickerScreen
from .utils import create_ui_logger
from .widgets import (
    TaskPanel,
    StatusBar,
    MessagesPanel,
    ConsoleWidget,
    ConsoleInput,
    VerticalSplitter,
    HorizontalSplitter,
)
from .widgets.splitter import _clamp_split_value

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class VerifyApp(SigintHandlerMixin, ConsoleCaptureMixin, App[None]):
    """Main UCAgent verification TUI application."""

    CSS_PATH = "styles/default.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt", show=False, priority=True),
        Binding("ctrl+shift+t", "choose_theme", "Choose theme", show=False),
        Binding("ctrl+shift+slash", "toggle_help_panel", "Help", show=False),
        Binding("ctrl+shift+left", "split_left", "Split left", show=False, priority=True),
        Binding("ctrl+shift+right", "split_right", "Split right", show=False, priority=True),
        Binding("ctrl+shift+up", "split_up", "Split up", show=False, priority=True),
        Binding("ctrl+shift+down", "split_down", "Split down", show=False, priority=True),
    ]

    # Reactive properties for dynamic layout
    task_width: reactive[int] = reactive(84)
    console_height: reactive[int] = reactive(13)
    _split_step: int = 2

    def __init__(self, vpdb: "VerifyPDB") -> None:
        super().__init__()
        self.vpdb = vpdb
        self.theme = "textual-dark"

        # Command history
        self.cmd_history: list[str] = []
        self.cmd_history_index: int = 0

        # Handler for key events
        self.key_handler = KeyHandler(self)

        # Daemon commands tracking
        self.daemon_cmds: dict[float, str] = {}

        # Message buffer for messages received before UI is mounted
        self._message_buffer: list[tuple[str, str]] = []
        self._ui_mounted: bool = False

        # Set message echo handler and logger early (like verify_ui.py does)
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self._mcps_logger_prev = getattr(self.vpdb.agent, "_mcps_logger", None)
        self.vpdb.agent._mcps_logger = create_ui_logger(self, level="INFO")

    def get_css_variables(self) -> dict[str, str]:
        """Provide extra theme variables for custom styles."""
        variables = super().get_css_variables()
        if self.current_theme.name == "textual-light":
            variables["console-input-focus"] = variables.get(
                "surface", variables.get("background", "ansi_default")
            )
        else:
            variables["console-input-focus"] = variables.get(
                "surface-active", variables.get("surface", "ansi_default")
            )
        return variables

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        with Vertical(id="app-container"):
            with Horizontal(id="main-container"):
                yield TaskPanel(id="task-panel")
                yield VerticalSplitter("task_width", id="split-task", classes="splitter vertical")
                with Vertical(id="right-container"):
                    yield MessagesPanel(id="messages-panel")
            yield HorizontalSplitter("console_height", invert=True, id="split-console", classes="splitter horizontal")
            yield ConsoleWidget(id="console", prompt=self.vpdb.prompt)
            yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        """Initialize after mounting."""
        # Mark UI as mounted and flush any buffered messages
        self._ui_mounted = True
        self._flush_message_buffer()

        # Install console capture and signal handler
        self.install_console_capture()
        self.install_sigint_handler()

        # Start periodic UI update
        self.set_interval(1.0, self._auto_update_ui)

        # Process initial batch commands if any
        if self.vpdb.init_cmd:
            self.call_later(self._process_batch_commands)

        # Focus the console input
        self.query_one(ConsoleInput).focus_input()

    def on_key(self, event: Key) -> None:
        """Allow Esc to dismiss the help panel without stealing other Esc uses."""
        if event.key == "escape" and self.query("#help-overlay"):
            self.action_hide_help_panel()
            event.prevent_default()
            event.stop()

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        self._cleanup()

    def message_echo(self, msg: str, end: str = "\n") -> None:
        """Thread-safe message echo handler.

        This method is called from worker threads, so it posts
        a message to be processed on the main thread.

        If the UI is not yet mounted, buffer the message for later.
        """
        if not self._ui_mounted:
            # Buffer messages until UI is ready
            self._message_buffer.append((msg, end))
            return
        self.call_from_thread(self._process_message, msg, end)

    def _process_message(self, msg: str, end: str) -> None:
        """Process message on main thread."""
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.append_message(msg, end)

    def _flush_message_buffer(self) -> None:
        """Flush buffered messages to the UI."""
        if not self._message_buffer:
            return
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        for msg, end in self._message_buffer:
            messages_panel.append_message(msg, end)
        self._message_buffer.clear()

    def _auto_update_ui(self) -> None:
        """Periodic UI update callback."""
        self.flush_console_output()
        self.update_task_panel()
        self.update_status_bar()
        console = self.query_one("#console", ConsoleWidget)
        console.refresh_prompt()

    def update_task_panel(self) -> None:
        """Update task panel content."""
        task_panel = self.query_one("#task-panel", TaskPanel)
        task_panel.update_content(self.vpdb, self.daemon_cmds)

    def update_status_bar(self) -> None:
        """Update bottom status bar content."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_content(self.vpdb)

    def _process_batch_commands(self) -> None:
        """Process batch commands from init_cmd."""
        if not self.vpdb.init_cmd:
            return

        while self.vpdb.init_cmd:
            cmd = self.vpdb.init_cmd.pop(0)
            self.run_worker(self.key_handler.process_command(cmd))

    # Action methods for key bindings
    def action_interrupt_or_quit(self) -> None:
        """Cancel running command or quit."""
        self._handle_ctrl_c()

    def action_quit(self) -> None:
        """Handle quit action."""
        self._cleanup()
        self.exit()

    def action_choose_theme(self) -> None:
        """Open theme picker modal."""
        if isinstance(self.screen, ThemePickerScreen):
            return
        themes = sorted(self.available_themes)
        self.push_screen(
            ThemePickerScreen(themes, current=self.theme),
            self._apply_theme_selection,
        )

    def action_show_help_panel(self) -> None:
        """Show the help panel on the right side."""
        if not self.query("#help-overlay"):
            focused = self.focused
            panel = HelpPanel(id="help-overlay")
            panel.border_title = "Keys"
            self.screen.mount(panel)
            if focused is not None:
                self.set_focus(focused, scroll_visible=False)

    def action_hide_help_panel(self) -> None:
        """Hide the help panel (if present)."""
        self.query("#help-overlay").remove()

    def action_toggle_help_panel(self) -> None:
        """Toggle the keys/help panel."""
        if self.query("#help-overlay"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def _apply_theme_selection(self, theme_name: str | None) -> None:
        if not theme_name:
            return
        if theme_name in self.available_themes:
            self.theme = theme_name

    def action_split_left(self) -> None:
        """Move vertical splitter left (shrink task panel)."""
        new_value = _clamp_split_value("task_width", self.task_width - self._split_step)
        self.task_width = new_value

    def action_split_right(self) -> None:
        """Move vertical splitter right (expand task panel)."""
        new_value = _clamp_split_value("task_width", self.task_width + self._split_step)
        self.task_width = new_value

    def action_split_up(self) -> None:
        """Move horizontal splitter up (expand console)."""
        new_value = _clamp_split_value("console_height", self.console_height + self._split_step)
        self.console_height = new_value

    def action_split_down(self) -> None:
        """Move horizontal splitter down (shrink console)."""
        new_value = _clamp_split_value("console_height", self.console_height - self._split_step)
        self.console_height = new_value

    async def on_console_input_command_submitted(
            self, event: ConsoleInput.CommandSubmitted
    ) -> None:
        """Handle command submission from console."""
        self.run_worker(self.key_handler.process_command(event.command, event.daemon))

    def set_active_command(self, command: str) -> None:
        """Update the console display for a running command."""
        console = self.query_one("#console", ConsoleWidget)
        console.set_running_command(command)

    def clear_active_command(self) -> None:
        """Clear the running command display."""
        console = self.query_one("#console", ConsoleWidget)
        console.set_running_command(None)

    def cancel_running_command(self) -> bool:
        """Request interruption of the running command if any."""
        had_worker = self.key_handler.has_active_worker()
        if had_worker:
            self.key_handler.cancel_active_worker()
        busy = had_worker or self._is_console_busy()
        # Daemon commands also count as running
        if self.daemon_cmds:
            busy = True
        if not busy:
            return False
        try:
            self.vpdb._sigint_handler(signal.SIGINT, None)
        except BaseException:
            pass
        return True

    def _is_console_busy(self) -> bool:
        try:
            return self.query_one(ConsoleInput).is_busy
        except Exception:
            return False

    def _cleanup(self) -> None:
        self.vpdb.agent.unset_message_echo_handler()
        self.vpdb.agent._mcps_logger = self._mcps_logger_prev
        self.restore_sigint_handler()
        self.restore_console_capture()
