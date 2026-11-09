"""Ordinary terminal view over a persistent runtime session."""

from ucagent.interfaces.terminal.presentation import format_result, format_operation
import codecs
import io
import os
import select
import shlex
import sys
from uuid import uuid4

from rich.cells import cell_len

from ucagent.runtime.control.commands import CommandResult, completion_base
from ucagent.runtime.control.controller import ControlError
from ucagent.runtime.output import StreamBridge
from ucagent.runtime.session import RuntimeSession


class Console:
    """Read and render terminal input without owning tasks, services or startup execution."""

    def __init__(self, host, *, session=None, input_stream=None, output_stream=None, tui_factory=None):
        """Attach a supplied operator session or create one for this terminal."""
        self.host = host
        self.frontend = session if session is not None else RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
        self.input = input_stream if input_stream is not None else sys.stdin
        self.output = output_stream if output_stream is not None else sys.stdout
        while isinstance(self.output, StreamBridge):
            self.output = self.output._original
        self.prompt = self.frontend.prompt
        self.tui_factory = tui_factory
        self._control_id = "console:" + uuid4().hex

    def execute_line(self, line, *, confirmed=False):
        """Handle local display actions, forwarding task and instance commands to the session."""
        name, *tail = line.strip().split(maxsplit=1) or [""]
        if name in {"tui", "clear"}:
            self.frontend.registry.resolve(name).parse(tail[0] if tail else "")
            if name == "tui":
                if self.tui_factory is None:
                    raise ControlError("unavailable", "No TUI frontend is configured.")
                transcript = self.tui_factory(self.frontend)
                if transcript:
                    self.output.write(transcript)
                return CommandResult("tui", {"attached": False})
            self.frontend.clear_console_state()
            if self.input.isatty():
                self.output.write("\x1b[2J\x1b[H")
            return None
        return self.frontend.execute_line(line, confirmed=confirmed)

    def display_result(self, result):
        """Display and retain a human-readable command result for terminal users."""
        if result is not None:
            text = self.frontend.format_result(result) + "\n"
            self.frontend.record_console_output(text)
            self.output.write(text)
            self.output.flush()

    def _render_input(self, text, cursor):
        """Redraw an editable line after output while preserving the logical cursor."""
        self.output.write("\r\x1b[K" + self.prompt + text)
        remaining = cell_len(text[cursor:])
        if remaining:
            self.output.write(f"\x1b[{remaining}D")
        self.output.flush()

    def _flush_output(self, pending="", cursor=None):
        """Display streamed output and operation results between input keystrokes."""
        text = self.frontend.drain_output() + self.frontend.completed_output()
        if text:
            self.frontend.record_console_output(text)
            if self.input.isatty():
                self.output.write("\r\x1b[K" + text + ("" if text.endswith("\n") else "\n"))
                self._render_input(pending, len(pending) if cursor is None else cursor)
            else:
                self.output.write(text)
                self.output.flush()

    def _readline(self, prompt=""):
        """Display readiness after configuring input, then read with editing and streaming."""
        try:
            fd = self.input.fileno()
        except (OSError, io.UnsupportedOperation):
            self.output.write(prompt)
            self.output.flush()
            return self.input.readline()
        if not self.input.isatty() or os.name != "posix":
            self.output.write(prompt)
            self.output.flush()
            while self.host.snapshot()["instance"] == "ready":
                self._flush_output()
                if select.select([fd], [], [], 0.1)[0]:
                    return self.input.readline()
            return ""
        import termios
        import tty

        saved = termios.tcgetattr(fd)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text, draft, cursor = "", "", 0
        history_index = history_length = len(self.frontend.history)
        try:
            tty.setcbreak(fd, termios.TCSANOW)
            # A visible prompt promises that control keys will reach our reader.
            self.output.write(prompt)
            self.output.flush()
            while self.host.snapshot()["instance"] == "ready":
                self._flush_output(text, cursor)
                if not select.select([fd], [], [], 0.1)[0]:
                    continue
                value = os.read(fd, 1)
                if not value or (value == b"\x04" and not text):
                    return ""
                if value in (b"\r", b"\n"):
                    self.output.write("\n")
                    return text + "\n"
                if value in (b"\x7f", b"\x08"):
                    if cursor:
                        text = text[:cursor - 1] + text[cursor:]
                        cursor -= 1
                elif value == b"\x04":
                    text = text[:cursor] + text[cursor + 1:]
                elif value == b"\x01":
                    cursor = 0
                elif value == b"\x05":
                    cursor = len(text)
                elif value == b"\x15":
                    text, cursor = text[cursor:], 0
                elif value == b"\x0b":
                    text = text[:cursor]
                elif value == b"\x17":
                    start = cursor
                    while start and text[start - 1].isspace():
                        start -= 1
                    while start and not text[start - 1].isspace():
                        start -= 1
                    text, cursor = text[:start] + text[cursor:], start
                elif value == b"\t":
                    matches = self.frontend.registry.complete(text[:cursor], self.frontend.session)
                    if matches:
                        base = completion_base(text[:cursor])
                        common = os.path.commonprefix(matches)
                        if len(matches) == 1:
                            replacement = base + (shlex.quote(matches[0]) if base else matches[0])
                        else:
                            self.output.write("\r\x1b[K" + "  ".join(matches) + "\n")
                            replacement = base + (shlex.quote(common) if base else common)
                        text, cursor = replacement + text[cursor:], len(replacement)
                elif value == b"\x1b":
                    sequence = b""
                    while len(sequence) < 12 and select.select([fd], [], [], 0.03)[0]:
                        sequence += os.read(fd, 1)
                        if len(sequence) >= 2 and (sequence[-1:].isalpha() or sequence.endswith(b"~")):
                            break
                    if sequence in (b"[A", b"[B"):
                        if len(self.frontend.history) != history_length:
                            history_index = history_length = len(self.frontend.history)
                        if history_index == len(self.frontend.history):
                            draft = text
                        history_index = max(0, min(len(self.frontend.history), history_index + (-1 if sequence == b"[A" else 1)))
                        text = self.frontend.history[history_index] if history_index < len(self.frontend.history) else draft
                        cursor = len(text)
                    elif sequence == b"[D":
                        cursor = max(0, cursor - 1)
                    elif sequence == b"[C":
                        cursor = min(len(text), cursor + 1)
                    elif sequence in (b"[H", b"OH", b"[1~", b"[7~"):
                        cursor = 0
                    elif sequence in (b"[F", b"OF", b"[4~", b"[8~"):
                        cursor = len(text)
                    elif sequence == b"[3~":
                        text = text[:cursor] + text[cursor + 1:]
                elif value >= b" " and value != b"\x7f":
                    decoded = decoder.decode(value)
                    text, cursor = text[:cursor] + decoded + text[cursor:], cursor + len(decoded)
                self._render_input(text, cursor)
            return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    def run(self):
        """Read a TTY or pipe until EOF or host shutdown; UI never installs process signals."""
        if self.host.snapshot()["instance"] != "ready":
            return
        self.host.attach_control(self._control_id, interrupt=self.frontend.cancel_foreground)
        self.host.output.install()
        self.host.output.terminal_attached = True
        self.host.startup.release()
        try:
            while self.host.snapshot()["instance"] == "ready":
                line = self._readline(self.prompt)
                if not line:
                    return
                self.frontend.record_console_command(line.strip())
                try:
                    result = self.execute_line(line)
                except ControlError as error:
                    if error.code == "confirmation_required":
                        if self._readline("Confirm this command? [y/N] ").strip().lower() not in {"y", "yes"}:
                            continue
                        result = self.execute_line(line, confirmed=True)
                    else:
                        self.output.write(f"{error.code}: {error}\n")
                        continue
                self.display_result(result)
                self.output.flush()
        finally:
            self.host.output.terminal_attached = False
            self.frontend.save_cmd_history()
            self.host.detach_control(self._control_id)
