"""Main application for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Input
from textual.events import Key

from .widgets import TaskPanel, StatusPanel, MessagesPanel, ConsoleWidget, VerticalSplitter, HorizontalSplitter
from .handlers import KeyHandler
from .utils import ConsoleCapture, UIMsgLogger

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class VerifyApp(App[None]):
    """Main UCAgent verification TUI application."""

    CSS_PATH = "styles/default.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel_scroll", "Cancel scroll", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("alt+up", "scroll_messages_up", "Scroll messages up", show=False),
        Binding("alt+down", "scroll_messages_down", "Scroll messages down", show=False),
        Binding("alt+left", "console_page_prev", "Console page prev", show=False),
        Binding("alt+right", "console_page_next", "Console page next", show=False),
        Binding("pageup", "console_page_prev", "Console page prev", show=False),
        Binding("pagedown", "console_page_next", "Console page next", show=False),
        Binding("shift+right", "clear_console", "Clear console", show=False),
        Binding("shift+left", "clear_input", "Clear input", show=False),
    ]

    # Reactive properties for dynamic layout
    task_width: reactive[int] = reactive(84)
    console_height: reactive[int] = reactive(13)
    status_height: reactive[int] = reactive(7)
    is_cmd_busy: reactive[bool] = reactive(False)

    def __init__(self, vpdb: "VerifyPDB") -> None:
        super().__init__()
        self.vpdb = vpdb
        self.cfg = vpdb.agent.cfg
        self._apply_theme_preference()

        # Store config values to apply after mount
        self._config_task_width = self.cfg.get_value("tui.task_width", 84)
        self._config_console_height = self.cfg.get_value("tui.console_height", 13)
        self._config_status_height = self.cfg.get_value("tui.status_height", 7)

        # Command history
        self.cmd_history: list[str] = []
        self.cmd_history_index: int = 0

        # Handler for key events
        self.key_handler = KeyHandler(self)

        # Daemon commands tracking
        self.daemon_cmds: dict[float, str] = {}

        # Scroll state
        self.messages_scroll_mode: bool = False
        self.console_page_cache: list[str] | None = None
        self.console_page_index: int = 0

        # Console output capture
        self._console_capture: ConsoleCapture | None = None
        self._stdout_backup = None
        self._stderr_backup = None
        self._vpdb_stdout_backup = None
        self._vpdb_stderr_backup = None
        self._mcps_logger_prev = None
        self._console_extra_height: int = 0

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

    def _apply_theme_preference(self) -> None:
        """Apply theme preference with a terminal-aware fallback."""
        theme_pref = str(self.cfg.get_value("tui.theme", "auto")).strip().lower()
        if theme_pref in {"", "auto"}:
            theme_name = self._detect_terminal_theme()
        elif theme_pref in {"ansi", "terminal"}:
            theme_name = "textual-light"
        else:
            theme_name = theme_pref

        if theme_name in self.available_themes:
            self.theme = theme_name

    def _detect_terminal_theme(self) -> str:
        """Best-effort light/dark detection using terminal hints."""
        colorfgbg = os.getenv("COLORFGBG", "")
        if colorfgbg:
            parts = [p for p in colorfgbg.replace(",", ";").split(";") if p.isdigit()]
            if parts:
                try:
                    bg = int(parts[-1])
                except ValueError:
                    bg = None
                if bg is not None:
                    if bg in {0, 1, 2, 3, 4, 5, 6, 8}:
                        return "textual-dark"
                    if bg in {7, 9, 10, 11, 12, 13, 14, 15}:
                        return "textual-light"
        return "textual-light"

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        with Vertical(id="app-container"):
            with Horizontal(id="main-container"):
                yield TaskPanel(id="task-panel")
                yield VerticalSplitter("task_width", id="split-task", classes="splitter vertical")
                with Vertical(id="right-container"):
                    yield StatusPanel(id="status-panel")
                    yield HorizontalSplitter("status_height", id="split-status", classes="splitter horizontal")
                    yield MessagesPanel(id="messages-panel")
            yield HorizontalSplitter("console_height", invert=True, id="split-console", classes="splitter horizontal")
            yield ConsoleWidget(id="console", prompt=self.vpdb.prompt)

    async def on_mount(self) -> None:
        """Initialize after mounting."""
        # Apply config values now that the app is mounted
        self.task_width = self._config_task_width
        self.console_height = self._config_console_height
        self.status_height = self._config_status_height

        # Set message echo handler
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self._mcps_logger_prev = getattr(self.vpdb.agent, "_mcps_logger", None)
        self.vpdb.agent._mcps_logger = UIMsgLogger(self, level="INFO")
        self._install_console_capture()

        # Start periodic UI update
        self.set_interval(1.0, self._auto_update_ui)

        # Process initial batch commands if any
        if self.vpdb.init_cmd:
            self.call_later(self._process_batch_commands)

        # Focus the console input
        self.query_one("#console-input", Input).focus()

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        self.vpdb.agent.unset_message_echo_handler()
        self.vpdb.agent._mcps_logger = self._mcps_logger_prev
        self._restore_console_capture()

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
        self.update_status_panel()
        console = self.query_one("#console", ConsoleWidget)
        console.refresh_prompt()

    def update_task_panel(self) -> None:
        """Update task panel content."""
        task_panel = self.query_one("#task-panel", TaskPanel)
        task_panel.update_content(self.vpdb, self.daemon_cmds)

    def update_status_panel(self) -> None:
        """Update status panel content."""
        status_panel = self.query_one("#status-panel", StatusPanel)
        layout_info = (self.task_width, self.console_height, self.status_height)
        status_panel.update_content(self.vpdb, layout_info)

    def _process_batch_commands(self) -> None:
        """Process batch commands from init_cmd."""
        if not self.vpdb.init_cmd:
            return

        while self.vpdb.init_cmd:
            cmd = self.vpdb.init_cmd.pop(0)
            self.run_worker(self.key_handler.process_command(cmd))

    # Action methods for key bindings
    def action_quit(self) -> None:
        """Handle quit action."""
        self.vpdb.agent.unset_message_echo_handler()
        self.vpdb.agent._mcps_logger = self._mcps_logger_prev
        self._restore_console_capture()
        self.exit()

    def action_cancel_scroll(self) -> None:
        """Cancel scroll mode."""
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        if messages_panel.scroll_mode:
            messages_panel.scroll_to_end()
        else:
            console = self.query_one("#console", ConsoleWidget)
            console.exit_page_mode()

    def action_increase_console_height(self) -> None:
        """Increase console height."""
        self.console_height = min(50, self.console_height + 1)

    def action_decrease_console_height(self) -> None:
        """Decrease console height."""
        self.console_height = max(3, self.console_height - 1)

    def action_increase_task_width(self) -> None:
        """Increase task panel width."""
        self.task_width = min(200, self.task_width + 2)

    def action_decrease_task_width(self) -> None:
        """Decrease task panel width."""
        self.task_width = max(10, self.task_width - 2)

    def action_increase_status_height(self) -> None:
        """Increase status panel height."""
        self.status_height = min(100, self.status_height + 1)

    def action_decrease_status_height(self) -> None:
        """Decrease status panel height."""
        self.status_height = max(3, self.status_height - 1)

    def action_scroll_messages_up(self) -> None:
        """Scroll messages panel up."""
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.move_focus(-1)

    def action_scroll_messages_down(self) -> None:
        """Scroll messages panel down."""
        messages_panel = self.query_one("#messages-panel", MessagesPanel)
        messages_panel.move_focus(1)

    def action_console_page_prev(self) -> None:
        """Console page previous."""
        console = self.query_one("#console", ConsoleWidget)
        console.page_scroll(-self.console_height, auto_enter=True)

    def action_console_page_next(self) -> None:
        """Console page next."""
        console = self.query_one("#console", ConsoleWidget)
        console.page_scroll(self.console_height, auto_enter=True)

    def action_clear_console(self) -> None:
        """Clear console output."""
        console = self.query_one("#console", ConsoleWidget)
        console.clear_output()

    def action_clear_input(self) -> None:
        """Clear console input."""
        input_widget = self.query_one("#console-input", Input)
        input_widget.value = ""

    def watch_task_width(self, new_value: int) -> None:
        """React to task_width changes."""
        if not self.is_mounted:
            return
        try:
            task_panel = self.query_one("#task-panel")
            task_panel.styles.width = new_value
        except Exception:
            pass

    def watch_console_height(self, new_value: int) -> None:
        """React to console_height changes."""
        if not self.is_mounted:
            return
        try:
            console = self.query_one("#console")
            console.styles.height = new_value + 2 + self._console_extra_height
        except Exception:
            pass

    def watch_status_height(self, new_value: int) -> None:
        """React to status_height changes."""
        if not self.is_mounted:
            return
        try:
            status_panel = self.query_one("#status-panel")
            status_panel.styles.height = new_value
        except Exception:
            pass

    async def on_console_widget_command_submitted(
        self, event: ConsoleWidget.CommandSubmitted
    ) -> None:
        """Handle command submission from console."""
        await self.key_handler.process_command(event.command, event.daemon)

    async def on_key(self, event: Key) -> None:
        """Handle key events not covered by bindings."""
        console = self.query_one("#console", ConsoleWidget)
        if event.key != "tab" and console.has_suggestions:
            console.clear_suggestions()
        if event.key == "tab":
            await self._handle_tab_completion()
            event.prevent_default()
            event.stop()
        elif event.key == "up":
            self._handle_history_up()
            event.prevent_default()
            event.stop()
        elif event.key == "down":
            self._handle_history_down()
            event.prevent_default()
            event.stop()

    async def _handle_tab_completion(self) -> None:
        """Handle tab key for command completion."""
        input_widget = self.query_one("#console-input", Input)
        current_text = input_widget.value

        completions = self.key_handler.complete_command(current_text)
        console = self.query_one("#console", ConsoleWidget)

        if not completions:
            console.clear_suggestions()
            return

        if len(completions) == 1:
            # Single completion - use it
            prefix = current_text[:current_text.rfind(" ") + 1] if " " in current_text else ""
            input_widget.value = prefix + completions[0]
            input_widget.cursor_position = len(input_widget.value)
            console.clear_suggestions()
        else:
            # Multiple completions - show them and use common prefix
            import os
            prefix = os.path.commonprefix(completions)
            if prefix:
                full_cmd = current_text[:current_text.rfind(" ") + 1] if " " in current_text else ""
                full_cmd += prefix
                input_widget.value = full_cmd
                input_widget.cursor_position = len(full_cmd)

            console.show_suggestions(completions)

    def _handle_history_up(self) -> None:
        """Handle up arrow for command history."""
        console = self.query_one("#console", ConsoleWidget)
        if console.page_scroll(1):
            return
        cmd = self.key_handler.get_history_item(-1)
        if cmd is not None:
            input_widget = self.query_one("#console-input", Input)
            input_widget.value = cmd
            input_widget.cursor_position = len(cmd)

    def _handle_history_down(self) -> None:
        """Handle down arrow for command history."""
        console = self.query_one("#console", ConsoleWidget)
        if console.page_scroll(-1):
            return
        cmd = self.key_handler.get_history_item(1)
        if cmd is not None:
            input_widget = self.query_one("#console-input", Input)
            input_widget.value = cmd
            input_widget.cursor_position = len(cmd)

    def set_console_extra_height(self, extra_lines: int) -> None:
        self._console_extra_height = max(0, extra_lines)
        if not self.is_mounted:
            return
        try:
            console = self.query_one("#console")
            console.styles.height = self.console_height + 2 + self._console_extra_height
        except Exception:
            pass

    def _install_console_capture(self) -> None:
        if self._console_capture is not None:
            return
        self._console_capture = ConsoleCapture()
        self._stdout_backup = sys.stdout
        self._stderr_backup = sys.stderr
        sys.stdout = self._console_capture
        sys.stderr = self._console_capture
        if getattr(self.vpdb, "stdout", None) is not None:
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

    def flush_console_output(self) -> None:
        if self._console_capture is None:
            return
        text = self._console_capture.get_and_clear()
        if not text:
            return
        console = self.query_one("#console", ConsoleWidget)
        console.append_output(text)
