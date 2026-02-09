"""Main application for UCAgent TUI."""

from __future__ import annotations

import queue
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
        Binding("ctrl+t", "choose_theme", "Choose theme", show=False),
        Binding("f1", "toggle_help_panel", "Help", show=False),
        # Arrow keys
        Binding("ctrl+left", "split_left", "Split left", show=False, priority=True),
        Binding("ctrl+right", "split_right", "Split right", show=False, priority=True),
        Binding("ctrl+up", "split_up", "Split up", show=False, priority=True),
        Binding("ctrl+down", "split_down", "Split down", show=False, priority=True),
        # Vim-style arrow keys
        Binding("ctrl+h", "split_left", "Split left", show=False, priority=True),
        Binding("ctrl+l", "split_right", "Split right", show=False, priority=True),
        Binding("ctrl+k", "split_up", "Split up", show=False, priority=True),
        Binding("ctrl+j", "split_down", "Split down", show=False, priority=True),
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

        # Message queue for thread-safe UI updates (shared with MessagesPanel)
        self._ui_message_queue: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()

        # Track previous logger for cleanup
        self._mcps_logger_prev = None
        self._ui_handlers_installed: bool = False

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
                yield VerticalSplitter(
                    "task_width", id="split-task", classes="splitter vertical"
                )
                with Vertical(id="right-container"):
                    yield MessagesPanel(
                        id="messages-panel", message_queue=self._ui_message_queue
                    )
            yield HorizontalSplitter(
                "console_height",
                invert=True,
                id="split-console",
                classes="splitter horizontal",
            )
            yield ConsoleWidget(id="console", prompt=self.vpdb.prompt)
            yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        """Initialize after mounting."""
        # Install message echo handler and UI logger now that widgets are ready
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self._mcps_logger_prev = getattr(self.vpdb.agent, "_mcps_logger", None)
        self.vpdb.agent._mcps_logger = create_ui_logger(self, level="INFO")
        self._ui_handlers_installed = True

        # Install console capture and signal handler
        self.install_console_capture()
        self.install_sigint_handler()

        # Process initial batch commands if any
        if self.vpdb.init_cmd:
            self.call_later(self._process_batch_commands)

        # Focus the console input
        self.query_one(ConsoleInput).focus_input()

    def on_ready(self) -> None:
        # Use default value from tcss
        task_panel = self.query_one(TaskPanel)
        self.task_width = task_panel.size.width
        console = self.query_one(ConsoleWidget)
        self.console_height = console.size.height

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
        """
        self._ui_message_queue.put((msg, end))

    def console_output(self, text: str) -> None:
        """Thread-safe console output method.

        From worker threads, this puts text into the console's batch queue.

        Args:
            text: Text to output
        """
        console = self.query_one("#console", ConsoleWidget)
        console.queue_output(text)

    def update_task_panel(self) -> None:
        """Update task panel content."""
        task_panel = self.query_one("#task-panel", TaskPanel)
        task_panel.update_content()

    def update_status_bar(self) -> None:
        """Update bottom status bar content."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_content()

    def _process_batch_commands(self) -> None:
        if not self.vpdb.init_cmd:
            return

        while self.vpdb.init_cmd:
            cmd = self.vpdb.init_cmd.pop(0)
            self.key_handler.process_command(cmd)

        console_input = self.query_one(ConsoleInput)
        console_input.update_running_commands()

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
        new_value = _clamp_split_value(
            "console_height", self.console_height + self._split_step
        )
        self.console_height = new_value

    def action_split_down(self) -> None:
        """Move horizontal splitter down (shrink console)."""
        new_value = _clamp_split_value(
            "console_height", self.console_height - self._split_step
        )
        self.console_height = new_value

    def on_console_input_command_submitted(
        self, event: ConsoleInput.CommandSubmitted
    ) -> None:
        self.key_handler.process_command(event.command, event.daemon)
        console_input = self.query_one(ConsoleInput)
        console_input.update_running_commands()

    def cancel_running_command(self) -> bool:
        if not self.key_handler.has_active_worker():
            return False

        thread_id = self.key_handler.get_last_worker_thread_id()
        if thread_id is not None:
            self.vpdb.agent.set_break_thread(thread_id)

        cancelled = self.key_handler.cancel_last_worker()
        if cancelled:
            self.flush_console_output()
            console_input = self.query_one(ConsoleInput)
            console_input.update_running_commands()
        return cancelled

    def _is_console_busy(self) -> bool:
        try:
            return self.query_one(ConsoleInput).is_busy
        except Exception:
            return False

    def _cleanup(self) -> None:
        if self._ui_handlers_installed:
            self.vpdb.agent.unset_message_echo_handler()
            self.vpdb.agent._mcps_logger = self._mcps_logger_prev
        self.restore_sigint_handler()
        self.restore_console_capture()
