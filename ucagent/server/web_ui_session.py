# -*- coding: utf-8 -*-
"""Standalone browser-session runner for the Textual web UI.

This keeps the web UI startup path out of ``VerifyPDB.set_trace()`` while still
reusing the existing VerifyPDB command surface as the backend command engine.
"""

from __future__ import annotations

import readline
from typing import TYPE_CHECKING, Iterable, Optional, List

from ucagent.util.log import echo_g, echo_y

if TYPE_CHECKING:
    from ucagent.verify_agent import VerifyAgent
    from ucagent.verify_pdb import VerifyPDB

import base64
import hmac
import shlex
import sys


def _build_web_ui_command(argv: Optional[List[str]] = None) -> str:
    """Build the subprocess command served by textual-serve."""
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    forwarded_args = []
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--web-ui-session":
            i += 1
            continue
        if arg == "--web-ui":
            # argparse optional-value form: "--web-ui" [value]
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                i += 2
            else:
                i += 1
            continue
        if arg.startswith("--web-ui="):
            i += 1
            continue
        forwarded_args.append(arg)
        i += 1
    if "--web-ui-session" not in forwarded_args:
        forwarded_args.append("--web-ui-session")
    cmd = [
        "env",
        "PYTHONWARNINGS=ignore",
        sys.executable,
        "-m",
        "ucagent.cli",
        *forwarded_args,
    ]
    return shlex.join(cmd)


def _serve_web_ui(argv: Optional[List[str]] = None) -> None:
    """Serve the UCAgent TUI in a browser via a PTY-based web terminal."""
    from ucagent.server.api_terminal import WebTerminalServer

    command = _build_web_ui_command(argv)
    web_ui_spec = _extract_web_ui_spec(argv)
    host, port, password = _resolve_web_ui_bind(web_ui_spec)
    server = WebTerminalServer(
        command,
        host=host,
        port=port,
        password=password,
        title="UCAgent Terminal",
    )
    server.start_blocking()


def _extract_web_ui_spec(argv: Optional[List[str]] = None) -> str:
    """Extract web-ui optional value from argv."""
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    for i, arg in enumerate(raw_args):
        if arg == "--web-ui":
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                return raw_args[i + 1]
            return ""
        if arg.startswith("--web-ui="):
            return arg.split("=", 1)[1]
    return ""


def _parse_web_ui_spec(spec: str) -> tuple[str, int, str]:
    """Parse '--web-ui host:port[:password]' value."""
    if not spec:
        return "localhost", 8000, ""
    parts = spec.split(":", 2)
    if len(parts) < 2:
        raise ValueError(
            f"Invalid --web-ui value '{spec}'. Expected format: base_url:port[:password]"
        )
    host = parts[0].strip()
    if not host:
        raise ValueError(
            f"Invalid --web-ui value '{spec}'. base_url cannot be empty."
        )
    port_str = parts[1].strip()
    try:
        port = int(port_str)
    except ValueError as e:
        raise ValueError(
            f"Invalid --web-ui value '{spec}'. Port must be an integer."
        ) from e
    if port < 1 or port > 65535:
        raise ValueError(
            f"Invalid --web-ui value '{spec}'. Port must be in range 1..65535."
        )
    password = parts[2] if len(parts) == 3 else ""
    return host, port, password


def _resolve_web_ui_bind(spec: str) -> tuple[str, int, str]:
    """Resolve final web-ui bind host/port/password with conflict policy."""
    from ucagent.util.functions import find_available_port, is_port_free

    host, port, password = _parse_web_ui_spec(spec)
    if is_port_free(host, port):
        return host, port, password
    # Bare '--web-ui' uses defaults. If default 8000 is busy, auto-increase.
    if spec.strip() == "":
        return host, find_available_port(start_port=port, end_port=65535), password
    raise ValueError(
        f"Port {port} on host '{host}' is unavailable for --web-ui."
    )


def _is_valid_basic_auth(auth_header: str, password: str) -> bool:
    """Validate HTTP Basic Auth header against expected password."""
    if not password:
        return True
    if not auth_header or not auth_header.startswith("Basic "):
        return False

    encoded = auth_header[6:].strip()
    if not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return False

    _, sep, pwd = decoded.partition(":")
    if not sep:
        return False
    return hmac.compare_digest(pwd.encode("utf-8"), password.encode("utf-8"))


def _suppress_web_ui_session_logs() -> None:
    """Silence non-error logs until the browser TUI finishes its handshake."""
    import ucagent.util.log as log
    log.set_silent(True)


class WebUISession:
    """Minimal TUI/session facade used by the browser-based Textual session."""

    def __init__(
        self,
        agent: "VerifyAgent",
        init_cmd: Optional[Iterable[str]] = None,
        delegate: Optional["VerifyPDB"] = None,
    ) -> None:
        self.agent = agent
        self._delegate = delegate if delegate is not None else agent.pdb
        self.init_cmd = list(init_cmd or [])
        self.cmdqueue: list[str] = []
        self._tui_app = None
        self._in_tui = False
        self._current_cmd: str | None = None
        self.lastcmd: str = ""

    @property
    def prompt(self) -> str:
        return self._delegate.prompt

    @prompt.setter
    def prompt(self, value: str) -> None:
        self._delegate.prompt = value

    @property
    def stdout(self):
        return self._delegate.stdout

    @stdout.setter
    def stdout(self, value) -> None:
        self._delegate.stdout = value

    @property
    def stderr(self):
        return getattr(self._delegate, "stderr", None)

    @stderr.setter
    def stderr(self, value) -> None:
        self._delegate.stderr = value

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def parseline(self, line: str):
        return self._delegate.parseline(line)

    def completedefault(self, text, line, begidx, endidx):
        return self._delegate.completedefault(text, line, begidx, endidx)

    def api_all_cmds(self, prefix: str = ""):
        cmds = self._delegate.api_all_cmds(prefix)
        if " " in prefix:
            return cmds
        hidden = {"tui", "exit_tui", "web_ui_start"}
        return [cmd for cmd in cmds if cmd not in hidden]

    def add_cmds(self, cmds) -> None:
        if isinstance(cmds, str):
            cmds = [cmds]
        if self._in_tui and self._tui_app is not None:
            for cmd in cmds:
                self._tui_app.call_from_thread(
                    self._tui_app.key_handler.process_command, cmd
                )
            return
        self.cmdqueue.extend(cmds)

    def onecmd(self, line: str):
        self._current_cmd = line or None
        if line:
            self.lastcmd = line
        cmd, arg, _ = self.parseline(line)
        handler = getattr(type(self), f"do_{cmd}", None) if cmd else None
        try:
            if handler is not None:
                return handler(self, arg)
            return self._delegate.onecmd(line)
        finally:
            self._current_cmd = None

    def do_continue(self, arg):
        """Continue execution without a breakpoint."""
        self.agent.set_break(False)
        self.agent.set_force_trace(False)
        self.agent.run_loop()

    do_c = do_continue

    def do_continue_with_message(self, arg):
        """Continue execution with a message."""
        try:
            self.agent.set_continue_msg(arg.strip())
        except Exception as exc:
            echo_y(f"Error setting continue message: {exc}")
            return
        self.do_continue("")

    def do_next_round(self, arg):
        """Continue execution to the next round."""
        self.agent.set_break(False)
        self.agent.one_loop()

    do_nr = do_next_round

    def do_next_round_with_message(self, arg):
        """Continue execution to the next round with a message."""
        msg = arg.strip()
        if not msg:
            echo_y("Message cannot be empty, usage: next_round_with_message <message>")
            return
        self.agent.set_break(False)
        self.agent.one_loop(msg)

    do_nrm = do_next_round_with_message

    def do_tui(self, arg):
        """Web UI session already runs inside the Textual UI."""
        echo_y("Already in web UI session.")

    def do_web_ui_start(self, arg):
        """Web UI session is already active."""
        echo_y("Web UI session is already active.")

    def do_quit(self, arg):
        """Quit the web UI session."""
        self.agent.stage_manager.save_stage_info()
        history_file = getattr(self._delegate, "history_file", None)
        if history_file:
            try:
                readline.write_history_file(history_file)
            except Exception:
                pass
        echo_g("Stage information saved. Exiting web UI session.")
        self.agent.exit()
        if self._tui_app is not None:
            self._tui_app.call_from_thread(self._tui_app.action_quit)
        return True

    do_q = do_quit
    do_exit = do_quit

    def run(self) -> None:
        from ucagent.tui import enter_tui

        if self.cmdqueue:
            self.init_cmd.extend(self.cmdqueue)
            self.cmdqueue.clear()
        self._in_tui = True
        try:
            enter_tui(self)
        finally:
            self._in_tui = False


def run_web_ui_session(
    agent: "VerifyAgent",
    init_cmd: Optional[Iterable[str]] = None,
) -> None:
    """Launch the browser Textual session without entering PDB first."""
    WebUISession(agent, init_cmd=init_cmd).run()
