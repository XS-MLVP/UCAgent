"""TUI input dispatch and history; operations remain owned by the runtime host."""

from ucagent.runtime.control.controller import ControlError
from ucagent.runtime.control.commands import CommandResult
from ucagent.interfaces.terminal.tui.widgets import ConsoleWidget
from ucagent.interfaces.terminal.tui.screens.confirmation import ConfirmationScreen


class KeyHandler:
    """Translate UI actions without creating threads or using thread identifiers."""

    def __init__(self, app):
        """Bind one view to its persistent console session."""
        self.app = app
        self.last_cmd = app.frontend.history[-1] if app.frontend.history else None
        self._history_index = len(app.frontend.history)
        self._history_length = len(app.frontend.history)

    def process_command(self, cmd, daemon=False, *, confirmed=False):
        """Submit input without blocking Textual; confirm destructive actions explicitly."""
        cmd = cmd.strip()
        if not cmd:
            return
        name, *tail = cmd.split(maxsplit=1)
        if name.lower() in {"q", "quit", "exit"}:
            if tail:
                self.app.console_output("Use q to leave TUI, or shutdown [force] to close the instance.\n")
                self.app.flush_console_output()
            else:
                self.app.action_detach()
            return
        if name in {"tui", "clear"}:
            if tail:
                self.app.console_output(f"{name} takes no arguments.\n")
                self.app.flush_console_output()
                return
            if name == "clear":
                self.app.frontend.clear_console_state()
                self.app.query_one(ConsoleWidget).clear_output()
            return
        if not confirmed:
            self.app.query_one(ConsoleWidget).echo_command(cmd)
        try:
            result = self.app.frontend.execute_line(cmd, foreground=not daemon, confirmed=confirmed)
            if result is not None and result.command == "help":
                rows = result.data if isinstance(result.data, list) else [result.data]
                described = []
                for row in rows:
                    if row["name"] == "quit":
                        shutdown = {**row, "name": "shutdown", "aliases": [], "usage": "shutdown [force]",
                                    "summary": "Close the instance and stop tasks and services."}
                        if tail and tail[0] == "shutdown":
                            described.append(shutdown)
                        else:
                            described.append({**row, "aliases": ["q", "exit"], "usage": "quit",
                                              "summary": "Leave TUI; keep tasks and services running."})
                            if not tail:
                                described.append(shutdown)
                    else:
                        described.append(row)
                result = CommandResult("help", described)
            self._add_to_history(cmd)
            self.app.console_output(self.app.frontend.format_result(result) + "\n" if result else "")
        except ControlError as error:
            if error.code == "confirmation_required":
                def accept(approved):
                    """Confirm only the original command; cancellation never dispatches it."""
                    if approved:
                        self.process_command(cmd, daemon, confirmed=True)
                    else:
                        self.app.console_output("Command cancelled.\n")
                        self.app.flush_console_output()
                self.app.push_screen(ConfirmationScreen(cmd), accept)
            else:
                self.app.console_output(f"{error.code}: {error}\n")
        self.app.flush_console_output()

    def _add_to_history(self, cmd):
        """Share history with the ordinary console and later UI attachments."""
        self.app.frontend.record_cmd_history(cmd)
        self.last_cmd = cmd
        self._history_index = len(self.app.frontend.history)
        self._history_length = len(self.app.frontend.history)

    def get_history_item(self, direction):
        """Navigate this session's command history without modifying another session."""
        history = self.app.frontend.history
        if len(history) != self._history_length:
            self._history_index = self._history_length = len(history)
        self._history_index = max(0, min(len(history), self._history_index + direction))
        return history[self._history_index] if self._history_index < len(history) else ""

    def complete_command(self, text):
        """Complete explicit registered commands and session-relative arguments."""
        return self.app.frontend.registry.complete(text, self.app.frontend.session)

    def get_running_commands(self):
        """Read active operation names from the runtime owner."""
        return self.app.frontend.get_running_commands()

    def cancel_last_worker(self):
        """Request cooperative cancellation of the selected foreground operation."""
        return self.app.frontend.cancel_foreground()

    def has_active_worker(self):
        """Report active operations without keeping UI worker handles."""
        return bool(self.get_running_commands())
