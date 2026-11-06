"""Textual frontend attached to an ordinary console and its runtime host."""

from contextlib import asynccontextmanager
from uuid import uuid4

from textual.app import App
from textual.binding import Binding
from textual.events import Key
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import HelpPanel

from .handlers import KeyHandler
from .screens import ThemePickerScreen
from .widgets.splitter import _clamp_split_value
from .widgets import TaskPanel, StatusBar, MessagesPanel, ConsoleWidget, ConsoleInput, VerticalSplitter, HorizontalSplitter


class VerifyApp(App):
    """Present shared state without owning services, signals or business workers."""

    CSS_PATH = "styles/default.tcss"
    BINDINGS = [Binding("ctrl+c", "interrupt", "Cancel operation", priority=True),
                Binding("ctrl+q", "detach", "Return to console", priority=True),
                Binding("f1", "toggle_help_panel", "Help"),
                Binding("escape", "hide_help_panel", "Close help", show=False, priority=True)]
    _split_step = 2
    BINDINGS += [Binding("ctrl+t", "choose_theme", "Theme"),
                 *[Binding(key, "split_" + direction, show=False, priority=True)
                   for key, direction in (("ctrl+left", "left"), ("ctrl+right", "right"),
                       ("ctrl+up", "up"), ("ctrl+down", "down"), ("ctrl+h", "left"),
                       ("ctrl+l", "right"), ("ctrl+k", "up"), ("ctrl+j", "down"))]]
    task_width = reactive(84)
    console_height = reactive(13)

    def __init__(self, session):
        """Attach one transient view to a persistent command session."""
        super().__init__()
        self.theme = "textual-dark"
        self.frontend = session
        self.host = session.host
        self.key_handler = KeyHandler(self)
        self.cmd_history = session.history
        self.daemon_cmds = []
        self._control_id = "tui:" + uuid4().hex
        self._cleaned = False
        self._replay_prefix = session.render_console_entries_since()
        self.session_output = ""
        self._stream_capture = None
        self._console_widget = None
        self._messages_widget = None

    async def run_async(self, **kwargs):
        """Keep capture active until Textual has fully restored its terminal streams."""
        try:
            return await super().run_async(**kwargs)
        finally:
            self._release_capture()

    @asynccontextmanager
    async def run_test(self, **kwargs):
        """Apply the same stream lifetime to headless and real-terminal test drivers."""
        try:
            async with super().run_test(**kwargs) as pilot:
                yield pilot
        finally:
            self._release_capture()

    def _release_capture(self):
        """Release the view bridge after teardown, including shutdown during a UI session."""
        if self._stream_capture is not None:
            self._stream_capture.__exit__(None, None, None)
            self._stream_capture = None
        if self.host.snapshot()["instance"] in {"closed", "failed"}:
            self.host.output.close()

    def get_css_variables(self):
        """Provide the focus background used by the existing theme stylesheet."""
        variables = super().get_css_variables()
        if self.current_theme.name == "textual-light":
            variables["console-input-focus"] = variables.get("surface", variables.get("background", "ansi_default"))
        else:
            variables["console-input-focus"] = variables.get("surface-active", variables.get("surface", "ansi_default"))
        return variables

    def compose(self):
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
                yield ConsoleWidget(id="console", prompt=self.frontend.prompt)
                yield StatusBar(id="status-bar")

    def on_mount(self):
        """Restore display state and subscribe through existing agent message callbacks."""
        self._console_widget = self.query_one(ConsoleWidget)
        self._messages_widget = self.query_one(MessagesPanel)
        self.host.attach_control(self._control_id, interrupt=self.frontend.cancel_foreground, messages=True)
        self._stream_capture = self.host.output.capture()
        self._stream_capture.__enter__()
        self.query_one(ConsoleWidget).restore_state(self.frontend.tui_console_state)
        self.query_one(MessagesPanel).restore_state(self.frontend.tui_messages_state)
        self.set_interval(0.1, self.refresh_runtime_state)
        self.query_one(ConsoleInput).focus_input()

    def message_echo(self, text, end="\n", **kwargs):
        """Queue model messages on the widget's existing thread-safe input buffer."""
        self.host.message_echo(text, end=end)

    def console_output(self, text):
        """Queue display output for the UI timer without writing from worker threads."""
        self.frontend.queue_output(text)

    def flush_console_output(self):
        """Drain queued output exactly once and persist it through the console widget."""
        if self._cleaned or self._console_widget is None:
            return
        text = self.frontend.drain_output()
        if text:
            self.query_one(ConsoleWidget).append_output(text)
        messages = self.frontend.drain_messages()
        if messages:
            self.query_one(MessagesPanel).append_message(messages)

    def refresh_runtime_state(self):
        """Poll owned operations; detaching this view never changes their identities."""
        if self._cleaned:
            return
        self.console_output(self.frontend.completed_output())
        self.flush_console_output()
        self.daemon_cmds = self.frontend.get_background_commands()
        self.query_one(ConsoleInput).set_busy(bool(self.frontend.get_running_commands()))
        self.query_one(ConsoleInput).update_running_commands()
        if self.host.snapshot()["instance"] in {"closing", "closed", "failed"}:
            self.action_detach()

    def on_console_input_command_submitted(self, event):
        """Forward one input event to the explicit command handler."""
        self.key_handler.process_command(event.command, event.daemon)

    def cancel_running_command(self):
        """Cancel this session's foreground operation without process signals."""
        if not self.frontend.cancel_foreground():
            return False
        self.console_output("Cancellation requested.\n")
        self.flush_console_output()
        return True

    def action_interrupt(self):
        """Ctrl-C affects only the foreground operation selected by this session."""
        self.cancel_running_command()

    def action_detach(self):
        """Return to the console without shutting down the application."""
        self.cleanup()
        self.exit()

    def action_quit(self):
        """Exit this view without requesting task or instance shutdown."""
        self.action_detach()

    def on_ready(self):
        """Size the initial split from the terminal, matching the original layout."""
        self.task_width = self.query_one(TaskPanel).size.width
        self.console_height = self.size.height // 2
        self.host.startup.release()
        self.refresh_runtime_state()

    def check_action(self, action, parameters):
        """Reserve Escape for help only while its overlay is visible."""
        if action == "hide_help_panel":
            return bool(self.query("#help-overlay"))
        return True

    def on_key(self, event: Key):
        """Dismiss binding help with Escape without consuming unrelated keys."""
        if event.key == "escape" and self.query("#help-overlay"):
            self.action_hide_help_panel()
            event.prevent_default()
            event.stop()

    def on_unmount(self):
        """Persist view state exactly once even on exceptional UI exits."""
        self.cleanup()

    def cleanup(self):
        """Persist view state while the outer app lifetime continues capturing teardown output."""
        if self._cleaned or self._console_widget is None:
            return
        try:
            self.console_output(self.frontend.completed_output())
            self.flush_console_output()
            self.frontend.tui_console_state = self._console_widget.export_state()
            self.frontend.tui_messages_state = self._messages_widget.export_state()
            self.frontend.save_cmd_history()
            transcript = self.frontend.render_console_entries_since()
            self.session_output = (transcript[len(self._replay_prefix):]
                                   if transcript.startswith(self._replay_prefix) else transcript)
        finally:
            self._cleaned = True
            self.host.startup.release()
            self.host.detach_control(self._control_id)

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
        """Apply a selected theme after the picker closes."""
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
