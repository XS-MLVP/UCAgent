"""Main application for UCAgent TUI."""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive

from .handlers import KeyHandler
from .screens import ThemePickerScreen
from .utils import ConsoleCapture, UIMsgLogger
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


class VerifyApp(App[None]):
    """Main UCAgent verification TUI application."""

    CSS_PATH = "styles/default.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt", show=False, priority=True),
        Binding("ctrl+t", "choose_theme", "Choose theme", show=False),
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

        # Running command tracking
        self._sigint_prev = None
        self._sigint_inflight = False
        self._cancel_cooldown = False

        # Console output capture
        self._console_capture: ConsoleCapture | None = None
        self._stdout_backup = None
        self._stderr_backup = None
        self._vpdb_stdout_backup = None
        self._vpdb_stderr_backup = None
        self._mcps_logger_prev = None

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
        # Apply config values now that the app is mounted
        cfg = self.vpdb.agent.cfg
        self.task_width = cfg.get_value("tui.task_width", 84)
        self.console_height = cfg.get_value("tui.console_height", 13)
        # Set message echo handler
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self._mcps_logger_prev = getattr(self.vpdb.agent, "_mcps_logger", None)
        self.vpdb.agent._mcps_logger = UIMsgLogger(self, level="INFO")
        self._install_console_capture()
        self._install_sigint_handler()

        # Start periodic UI update
        self.set_interval(1.0, self._auto_update_ui)

        # Process initial batch commands if any
        if self.vpdb.init_cmd:
            self.call_later(self._process_batch_commands)

        # Focus the console input
        self.query_one(ConsoleInput).focus_input()

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        self._cleanup()

    def message_echo(self, msg: str, end: str = "\n") -> None:
        """Thread-safe message echo handler.

        This method is called from worker threads, so it posts
        a message to be processed on the main thread.
        """
        self.call_from_thread(self._process_message, msg, end)

    def _process_message(self, msg: str, end: str) -> None:
        """Process message on main thread."""
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.append_message(msg, end)

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
        self._restore_sigint_handler()
        self._restore_console_capture()

    def _install_console_capture(self) -> None:
        if self._console_capture is not None:
            return
        self._console_capture = ConsoleCapture()
        self._stdout_backup = sys.stdout
        self._stderr_backup = sys.stderr
        sys.stdout = self._console_capture
        sys.stderr = self._console_capture
        if self.vpdb.stdout is not None:
            self._vpdb_stdout_backup = self.vpdb.stdout
            self.vpdb.stdout = self._console_capture
        if getattr(self.vpdb, "stderr", None) is not None:
            self._vpdb_stderr_backup = self.vpdb.stderr
            self.vpdb.stderr = self._console_capture

    def _restore_console_capture(self) -> None:
        if self._console_capture is None:
            return
        if self._stdout_backup is not None:
            sys.stdout = self._stdout_backup
        if self._stderr_backup is not None:
            sys.stderr = self._stderr_backup
        if self._vpdb_stdout_backup is not None:
            self.vpdb.stdout = self._vpdb_stdout_backup
        if self._vpdb_stderr_backup is not None:
            self.vpdb.stderr = self._vpdb_stderr_backup
        self._console_capture = None

    def _install_sigint_handler(self) -> None:
        if self._sigint_prev is not None:
            return
        self._sigint_prev = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            try:
                self.call_from_thread(self._handle_ctrl_c)
            except Exception:
                pass

        signal.signal(signal.SIGINT, _sigint_handler)

    def _restore_sigint_handler(self) -> None:
        if self._sigint_prev is None:
            return
        try:
            signal.signal(signal.SIGINT, self._sigint_prev)
        finally:
            self._sigint_prev = None
            self._sigint_inflight = False
            self._cancel_cooldown = False

    def _handle_ctrl_c(self) -> None:
        if self._sigint_inflight:
            return
        self._sigint_inflight = True
        try:
            if self.cancel_running_command():
                # Successfully cancelled a command; set cooldown to prevent
                # a racing second Ctrl+C from immediately quitting.
                self._cancel_cooldown = True
                self.set_timer(0.5, self._clear_cancel_cooldown)
            elif not self._cancel_cooldown:
                self.action_quit()
        finally:
            self._sigint_inflight = False

    def _clear_cancel_cooldown(self) -> None:
        self._cancel_cooldown = False

    def flush_console_output(self) -> None:
        if self._console_capture is None:
            return
        text = self._console_capture.get_and_clear()
        if not text:
            return
        console = self.query_one("#console", ConsoleWidget)
        console.append_output(text)
