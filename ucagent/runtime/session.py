"""Persistent operator session shared by terminal views, independent of their lifetimes."""

from collections import deque
from dataclasses import dataclass, replace
import json
from pathlib import Path
import threading

from ucagent.runtime.control.commands import CommandSession, CommandResult
from ucagent.runtime.operations import TERMINAL_STATES


@dataclass
class ConsoleEntry:
    """One persisted command or output segment shared by attached displays."""

    kind: str
    payload: str


@dataclass
class ConsoleState:
    """Keep transcript entries independent from widget lifetimes."""

    entries: list


class RuntimeSession:
    """Keep input preferences and display state without owning execution or terminal I/O."""

    def __init__(self, host, *, result_formatter, operation_formatter, session=None):
        """Subscribe to the runtime's output without changing shared command or signal handlers."""
        self.host = host
        self._result_formatter = result_formatter
        self._operation_formatter = operation_formatter
        self.agent = host.agent
        self.controller = host.controller
        self.registry = host.registry
        self.session = session or CommandSession(Path(self.agent.workspace))
        self.prompt = "(UnityChip) "
        self.history = []
        self.tui_console_state = ConsoleState([])
        self.tui_messages_state = None
        self._lock = threading.RLock()
        self._messages = deque(maxlen=4000)
        self._model_messages = deque(maxlen=4000)
        self._displayed = set()
        self._history_file = Path(self.agent.workspace) / ".ucagent" / "command_history.json"
        if self._history_file.is_file():
            self.history = json.loads(self._history_file.read_text())
        self.host.output.subscribe(self.queue_output, replay=True)
        self.host.messages.subscribe(self.queue_message, replay=True)
        self.host.add_cleanup(self.close)

    def close(self):
        """Release only this session's subscriptions, leaving tasks and services untouched."""
        self.host.output.unsubscribe(self.queue_output)
        self.host.messages.unsubscribe(self.queue_message)

    def record_console_output(self, text):
        """Append output once to the persistent session transcript."""
        if not text:
            return
        with self._lock:
            entries = self.tui_console_state.entries
            if entries and entries[-1].kind == "output":
                entries[-1].payload += text
            else:
                entries.append(ConsoleEntry("output", text))

    def record_console_command(self, command):
        """Record visible input independently from execution ownership."""
        if command and command != "tui":
            with self._lock:
                self.tui_console_state.entries.append(ConsoleEntry("command", command))

    def clear_console_state(self):
        """Clear this display's history without affecting operations or model messages."""
        self.tui_console_state.entries.clear()
        self.drain_output()

    def render_console_entries_since(self, index=0):
        """Render recorded entries for terminal replay after a UI detaches."""
        return "".join("> " + row.payload + "\n" if row.kind == "command" else row.payload
                       for row in self.tui_console_state.entries[index:])

    def record_cmd_history(self, command):
        """Keep consecutive duplicate inputs out of session history."""
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)

    def get_cmd_history(self):
        """Return a detached input history for frontend navigation."""
        return list(self.history)

    def save_cmd_history(self):
        """Persist only this console's history under its owned workspace."""
        self._history_file.parent.mkdir(exist_ok=True)
        self._history_file.write_text(json.dumps(self.history, ensure_ascii=False))

    def queue_output(self, text):
        """Order UI notices and runtime output in the same persistent display queue."""
        if text:
            with self._lock:
                self._messages.append(text)

    def drain_output(self):
        """Consume each buffered chunk once, independently of the active frontend."""
        with self._lock:
            text = "".join(self._messages)
            self._messages.clear()
        return text

    def queue_message(self, text):
        """Retain model output independently from whichever view is attached."""
        with self._lock:
            self._model_messages.append(text)

    def drain_messages(self):
        """Transfer pending model text, including incomplete lines, into a view."""
        with self._lock:
            text = "".join(self._model_messages)
            self._model_messages.clear()
        return text

    @property
    def foreground_id(self):
        """Select the latest live foreground operation, including continuation children."""
        rows = [row for row in self.host.operations.list()
                if row["session_id"] == self.session.id and row["foreground"]]
        active = [row for row in rows if row["state"] not in TERMINAL_STATES]
        return (active or rows)[-1]["id"] if rows else None

    def get_running_commands(self):
        """Display all runtime work even when another frontend submitted it."""
        return [row["input_line"] or row["command"] for row in self.host.operations.list()
                if row["state"] not in TERMINAL_STATES and row["command"] != "initial_commands"]

    def get_background_commands(self):
        """List this session's background work using executor-owned identity and timestamps."""
        return [{**row, "line": row["input_line"] or row["command"]}
                for row in self.host.operations.list()
                if row["session_id"] == self.session.id and not row["foreground"]
                and row["state"] not in TERMINAL_STATES]

    def cancel_foreground(self):
        """Request cancellation of the newest live operation from this session only."""
        operation_id = self.foreground_id
        if operation_id is None or self.host.operations.get(operation_id)["state"] in TERMINAL_STATES:
            return False
        self.host.operations.cancel(operation_id)
        return True

    def execute_line(self, line, *, foreground=True, confirmed=False):
        """Submit via the shared runtime policy and commit only changed session preferences."""
        with self._lock:
            request = replace(self.session, confirmed=confirmed, foreground=foreground)
            request.cwd = self.session.cwd
            previous = {key: getattr(request, key) for key in ("cwd", "repeat", "shell_timeout")}
        result = self.registry.submit(line, request)
        if result is None:
            return None
        with self._lock:
            for key, value in previous.items():
                if getattr(request, key) != value:
                    setattr(self.session, key, getattr(request, key))
            self.session.last_command = request.last_command
            self.record_cmd_history(request.last_command)
        return result

    def completed_output(self):
        """Report each terminal result once, including operations created by approval commands."""
        notices = []
        for row in self.host.operations.list():
            if (row["session_id"] == self.session.id and row["state"] in TERMINAL_STATES
                    and row["id"] not in self._displayed):
                self._displayed.add(row["id"])
                if row["result_kind"] == "command" and row["state"] == "succeeded" and row["result"] is not None:
                    result = CommandResult(row["command"], row["result"])
                    notices.append(f"[{row['id']}] {row['input_line']}: succeeded\n" + self.format_result(result))
                else:
                    notices.append(self._operation_formatter(row, row["input_line"]))
        return "\n".join(notices) + ("\n" if notices else "")

    def format_result(self, result):
        """Render the same command result for either local display."""
        return self._result_formatter(result, use_skills=self.agent.cfg.get_value("skill.use_skill", False))
