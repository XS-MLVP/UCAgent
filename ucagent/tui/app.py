"""Main application for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
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

        # Daemon commands tracking (current TUI session only)
        self.daemon_cmds: dict[float, str] = {}

        # Track previous logger for cleanup
        self._mcps_logger_prev = None
        self._ui_handlers_installed: bool = False

        # Session output history for dumping to terminal after exit
        self._session_output: str = ""
        self._is_shutting_down: bool = False
        self._cleanup_done: bool = False

    @property
    def session_output(self) -> str:
        return self._session_output

    @property
    def is_shutting_down(self) -> bool:
        return self._is_shutting_down

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
                    yield MessagesPanel(id="messages-panel")
            yield HorizontalSplitter(
                "console_height",
                invert=True,
                id="split-console",
                classes="splitter horizontal",
            )
            with Vertical(id="console-container"):
                yield ConsoleWidget(id="console", prompt=self.vpdb.prompt)
                yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        """Initialize after mounting."""
        # Install message echo handler and UI logger now that widgets are ready
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self._mcps_logger_prev = getattr(self.vpdb.agent, "_mcps_logger", None)
        self.vpdb.agent._mcps_logger = create_ui_logger(self, level="INFO")
        self._ui_handlers_installed = True
        self._restore_command_history()
        self._restore_console_history()
        self._restore_messages_history()

        # Install console capture and signal handler for TUI
        # sessions so stdout/log output appears in the Console panel.
        self.install_console_capture()
        self.install_sigint_handler()
        self.set_interval(0.5, self.refresh_runtime_state)

        # Process initial batch commands if any
        if self.vpdb.init_cmd:
            def process_batch():
                while self.vpdb.init_cmd:
                    cmd = self.vpdb.init_cmd.pop(0)
                    self.key_handler.process_command(cmd)
                console_input = self.query_one(ConsoleInput)
                console_input.update_running_commands()

            self.call_later(process_batch)

        # Focus the console input
        self.query_one(ConsoleInput).focus_input()

    async def on_ready(self) -> None:
        # Use default value from tcss
        task_panel = self.query_one(TaskPanel)
        self.task_width = task_panel.size.width

        # Set console height to half of available height (1:1 ratio with main-container)
        available_height = self.app.size.height // 2
        self.console_height = available_height

    def on_key(self, event: Key) -> None:
        """Allow Esc to dismiss the help panel without stealing other Esc uses."""
        if event.key == "escape" and self.query("#help-overlay"):
            self.action_hide_help_panel()
            event.prevent_default()
            event.stop()

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        self.cleanup()

    def message_echo(self, msg: str, end: str = "\n") -> None:
        """Thread-safe message echo handler invoked from worker threads."""
        if not msg:
            return
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.append_message(f"{msg}{end}")

    def console_output(self, text: str) -> None:
        """Thread-safe console output method.

        From worker threads, this puts text into the console's batch queue.

        Args:
            text: Text to output
        """
        console = self.query_one("#console", ConsoleWidget)
        console.queue_output(text)

    # Action methods for key bindings
    def action_interrupt_or_quit(self) -> None:
        """Cancel running command or quit."""
        self._handle_ctrl_c()

    def action_quit(self) -> None:
        """Handle quit action."""
        self.stop_running_tasks(include_detached=False)
        self.cleanup()
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

        cancelled = self.key_handler.cancel_last_worker()
        if cancelled:
            self.flush_console_output()
            console_input = self.query_one(ConsoleInput)
            console_input.update_running_commands()
        return cancelled

    def stop_running_tasks_with_policy(self, *, include_detached: bool) -> bool:
        cancelled = self.key_handler.cancel_all_workers(
            include_detached=include_detached
        )
        if not cancelled:
            return False
        self.flush_console_output()
        console_input = self.query_one(ConsoleInput)
        console_input.update_running_commands()
        task_panel = self.query_one("#task-panel", TaskPanel)
        task_panel.update_content()
        return True

    def stop_running_tasks(self, include_detached: bool = True) -> bool:
        return self.stop_running_tasks_with_policy(
            include_detached=include_detached
        )

    def refresh_runtime_state(self) -> None:
        if self._cleanup_done:
            return
        self.key_handler.get_running_commands()
        console_input = self.query_one(ConsoleInput)
        console_input.update_running_commands()

    def _restore_messages_history(self) -> None:
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.restore_state(self.vpdb.tui_messages_state)

    def _restore_console_history(self) -> None:
        console = self.query_one("#console", ConsoleWidget)
        console.restore_state(self.vpdb.tui_console_state)

    def _restore_command_history(self) -> None:
        self.cmd_history = self.vpdb.get_cmd_history()
        self.cmd_history_index = len(self.cmd_history)
        self.key_handler.last_cmd = self.cmd_history[-1] if self.cmd_history else None

    def _save_messages_history(self) -> None:
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        self.vpdb.tui_messages_state = messages_panel.export_state()

    def _save_console_history(self) -> None:
        console = self.query_one("#console", ConsoleWidget)
        self.vpdb.tui_console_state = console.export_state()

    def _save_command_history(self) -> None:
        self.vpdb.save_cmd_history()

    def cleanup(self) -> None:
        """Cleanup resources on exit."""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self._is_shutting_down = True
        self.stop_running_tasks(include_detached=False)

        # Collect console history (best-effort, only on first call)
        if self._console_capture is not None and not self._session_output:
            self._session_output = self._console_capture.get_history()
        self._save_command_history()
        self._save_console_history()
        self._save_messages_history()

        if self._ui_handlers_installed:
            self.vpdb.agent.unset_message_echo_handler()
            self.vpdb.agent._mcps_logger = self._mcps_logger_prev
            self._ui_handlers_installed = False
        self.restore_sigint_handler()
        self.restore_console_capture()
