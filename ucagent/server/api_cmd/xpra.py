"""Owned Xpra application sessions, bounded diagnostics and process cleanup."""

import collections
from dataclasses import dataclass, field
import http.client
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import psutil


class XpraError(Exception):
    """An HTTP-ready session failure with an actionable public diagnostic."""

    def __init__(self, status, code, message, next_action, **details):
        """Keep the status separate from the bounded response body."""
        super().__init__(message)
        self.status = status
        self.detail = dict(error_code=code, message=message, next_action=next_action, **details)


@dataclass
class _Session:
    """Resources belonging to exactly one manager-created application session."""

    id: str
    name: str
    mode: str
    command: str
    cwd: str
    idle_timeout: int = -1
    secrets: tuple = ()
    status: str = "starting"
    created_at: float = field(default_factory=time.time)
    process: object = None
    directory: object = None
    worker: object = None
    children: dict = field(default_factory=dict)
    last_error: object = None
    logs: object = field(default_factory=lambda: collections.deque(maxlen=200))
    stop_requested: object = field(default_factory=threading.Event)
    stop_lock: object = field(default_factory=threading.Lock)


class XpraSessionManager:
    """Share quotas across listeners and own all launched processes and sockets."""

    def __init__(self, workspace, cfg=None, secrets=()):
        """Read resolved server configuration without probing or launching Xpra."""
        self.workspace = Path(workspace).resolve()
        defaults = dict(executable="xpra", max_sessions=5, terminal_command=["xterm", "-e"],
                        html_dir=None, startup_timeout=20, shutdown_timeout=5)
        self.options = {key: cfg.get_value("cmd_api.xpra." + key, value) if cfg is not None else value
                        for key, value in defaults.items()}
        self._sessions = {}
        self._lock = threading.RLock()
        self._closed = False
        self._secrets = tuple(value for value in secrets if value) + tuple(
            value for key, value in os.environ.items()
            if value and re.search(r"password|passwd|token|secret|api_key|proxy", key, re.I)
        )
        self._config_error = None
        for key in ("startup_timeout", "shutdown_timeout", "max_sessions"):
            value = self.options[key]
            valid = type(value) is int if key == "max_sessions" else type(value) in (int, float)
            if not valid or value <= 0 or value != value or value == float("inf"):
                self._config_error = f"cmd_api.xpra.{key} must be a positive {'integer' if key == 'max_sessions' else 'number'}."
        terminal = self.options["terminal_command"]
        if not isinstance(terminal, list) or not terminal or any(not isinstance(x, str) or not x or "\0" in x for x in terminal):
            self._config_error = "cmd_api.xpra.terminal_command must be a nonempty list of command arguments."
        if not isinstance(self.options["executable"], str) or not self.options["executable"] or "\0" in self.options["executable"]:
            self._config_error = "cmd_api.xpra.executable must name an executable."
        html_dir = self.options["html_dir"]
        if html_dir is not None and (not isinstance(html_dir, str) or not html_dir or "\0" in html_dir):
            self._config_error = "cmd_api.xpra.html_dir must be a directory path or null."
        limit = self.options["max_sessions"]
        self.max_sessions = limit if type(limit) is int and limit > 0 else None

    def _redact(self, text, session=None):
        """Remove known credential and supplied environment values from output."""
        for value in sorted(set(self._secrets + (session.secrets if session else ())), key=len, reverse=True):
            text = text.replace(value, "[redacted]")
        return text

    def status(self):
        """Report optional runtime prerequisites without blocking unrelated APIs."""
        result = dict(available=False, version=None, console_available=False,
                      max_sessions=self.max_sessions, diagnostic=None)
        if self._config_error:
            result["diagnostic"] = dict(error_code="XPRA_CONFIG_INVALID", message=self._config_error,
                                        next_action="Correct cmd_api.xpra in the config and restart the CMD service.")
            return result
        executable = shutil.which(self.options["executable"])
        result["console_available"] = bool(shutil.which(self.options["terminal_command"][0]))
        if not executable:
            result["diagnostic"] = dict(error_code="XPRA_NOT_FOUND", message="The configured Xpra executable was not found.",
                                        next_action="Install Xpra or set cmd_api.xpra.executable to its executable path.")
            return result
        try:
            probe = subprocess.run([executable, "--version"], capture_output=True, timeout=3)
            if probe.returncode:
                raise OSError("Xpra could not report its version.")
            result["version"] = self._redact(probe.stdout.decode("utf-8", "replace").strip()[:200])
            html_dir = self.options["html_dir"]
            if html_dir is not None and not (Path(html_dir).expanduser().resolve() / "index.html").is_file():
                raise XpraError(503, "XPRA_HTML5_MISSING", "The configured HTML5 directory has no index.html.",
                                "Install xpra-html5 and correct cmd_api.xpra.html_dir.")
            result["available"] = True
        except XpraError as exc:
            result["diagnostic"] = exc.detail
        except (OSError, subprocess.TimeoutExpired):
            result["diagnostic"] = dict(error_code="XPRA_UNAVAILABLE", message="Xpra could not be executed successfully.",
                                        next_action="Check the configured executable and its installation, then retry.")
        return result

    def _snapshot(self, session, logs=False):
        """Project public metadata while the manager lock protects mutable state."""
        result = dict(id=session.id, name=session.name, mode=session.mode,
                      command=self._redact(session.command, session), cwd=session.cwd,
                      status=session.status, created_at=session.created_at,
                      idle_timeout=session.idle_timeout,
                      viewer_path=f"sessions/{session.id}/view", last_error=session.last_error)
        if logs:
            result["log_tail"] = list(session.logs)
        return result

    def list(self):
        """Return owned sessions and count every not-yet-reaped active session."""
        with self._lock:
            return dict(sessions=[self._snapshot(s) for s in self._sessions.values()],
                        active_count=sum(s.status in ("starting", "running", "stopping") for s in self._sessions.values()),
                        max_sessions=self.max_sessions)

    def get(self, session_id):
        """Return bounded details, or explain that the requested session is absent."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise XpraError(404, "XPRA_SESSION_NOT_FOUND", "This Xpra session does not exist.",
                                "Refresh the session list and open an existing session.")
            return self._snapshot(session, logs=True)

    def socket_path(self, session_id):
        """Resolve only an owned, running session as a fixed proxy destination."""
        with self._lock:
            self.get(session_id)
            session = self._sessions[session_id]
            if session.status != "running" or session.process.poll() is not None:
                raise XpraError(503, "XPRA_SESSION_UNAVAILABLE", "This session is not running.",
                                "Inspect its status and logs, then create a new session if the application exited.")
            return str(Path(session.directory.name) / "s")

    def create(self, command, mode="gui", name="", cwd=".", env=None, idle_timeout=-1):
        """Reserve capacity, launch one application, and wait for its HTML5 endpoint."""
        if type(idle_timeout) is not int or idle_timeout != -1 and not 1 <= idle_timeout <= 4_294_967:
            raise XpraError(422, "XPRA_IDLE_TIMEOUT_INVALID", "idle_timeout must be -1 or a positive integer up to 4294967 seconds.",
                            "Use -1 to keep disconnected sessions running, or set the number of seconds without a connected client.")
        available = self.status()
        if not available["available"]:
            diagnostic = available["diagnostic"]
            raise XpraError(503, diagnostic["error_code"], diagnostic["message"], diagnostic["next_action"])
        try:
            argv = shlex.split(command)
            if not argv or any("\0" in x for x in argv):
                raise ValueError("A command is required.")
        except ValueError:
            raise XpraError(422, "XPRA_COMMAND_INVALID", "The command is empty or has invalid quoting.",
                            "Provide a program and arguments, using matching quotes.") from None
        if mode not in ("gui", "console"):
            raise XpraError(422, "XPRA_MODE_INVALID", "mode must be gui or console.", "Choose gui or console.")
        try:
            working_dir = (self.workspace / cwd).resolve()
            working_dir.relative_to(self.workspace)
            if not working_dir.is_dir():
                raise ValueError()
        except (ValueError, OSError):
            raise XpraError(422, "XPRA_CWD_INVALID", "The working directory must exist inside the workspace.",
                            "Choose a workspace-relative directory, without escaping through symlinks.") from None
        env = dict(env or {})
        if any(not isinstance(k, str) or not k or "=" in k or "\0" in k or not isinstance(v, str) or "\0" in v for k, v in env.items()):
            raise XpraError(422, "XPRA_ENV_INVALID", "Environment entries must be valid string names and values.",
                            "Correct env names and string values; remove NUL characters.")
        child_env = os.environ.copy()
        child_env.update(env)
        search_path = os.pathsep.join(str(working_dir / part) for part in child_env.get("PATH", os.defpath).split(os.pathsep))
        executable = shutil.which(argv[0], path=search_path) if "/" not in argv[0] else str(working_dir / argv[0])
        if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise XpraError(422, "XPRA_COMMAND_NOT_FOUND", "The application command was not found or is not executable.",
                            "Install the application or provide its executable path and correct PATH.")
        argv[0] = executable
        if mode == "console":
            terminal = list(self.options["terminal_command"])
            terminal[0] = shutil.which(terminal[0])
            if not terminal[0]:
                raise XpraError(503, "XPRA_TERMINAL_NOT_FOUND", "The configured graphical terminal was not found.",
                                "Install xterm or configure cmd_api.xpra.terminal_command.")
            argv = terminal + argv
        session = _Session(uuid.uuid4().hex, name or Path(argv[0]).name, mode, command,
                           str(working_dir.relative_to(self.workspace)) or ".", idle_timeout=idle_timeout,
                           secrets=tuple(v for v in env.values() if v))
        with self._lock:
            if self._closed:
                raise XpraError(503, "XPRA_STOPPING", "The CMD service is stopping.", "Restart the CMD service before creating sessions.")
            if self.list()["active_count"] >= self.options["max_sessions"]:
                raise XpraError(409, "XPRA_SESSION_LIMIT", "The maximum number of active Xpra sessions has been reached.",
                                "Delete an unused session or increase cmd_api.xpra.max_sessions.")
            self._sessions[session.id] = session
        try:
            directory = tempfile.TemporaryDirectory(prefix="uca-xpra-", dir="/tmp")
            socket_path = str(Path(directory.name) / "s")
            # Isolate Xpra defaults so host configuration cannot add public listeners
            # or extra startup commands outside this service's ownership.
            for key in ("XPRA_DEFAULT_CONF_DIRS", "XPRA_SYSTEM_CONF_DIRS", "XPRA_USER_CONF_DIRS"):
                child_env[key] = directory.name
            html = self.options["html_dir"]
            args = [shutil.which(self.options["executable"]), "seamless", "--daemon=no", "--attach=no",
                    "--start-via-proxy=no", "--systemd-run=no", "--splash=no", "--http=yes",
                    f"--html={str(Path(html).expanduser().resolve()) if html else 'on'}",
                    # CMD authenticates the browser; the private socket must also
                    # accept HTML5 clients that do not supply an OS username.
                    f"--bind={socket_path},auth=none:verify-username=no", f"--socket-dirs={directory.name}",
                    f"--sessions-dir={directory.name}/sessions", "--socket-permissions=600",
                    "--mdns=no", "--use-display=no", "--exit-with-children=yes",
                    # Xpra owns authenticated client accounting across every CMD
                    # listener and proxy. Connected clients never expire for lack of input.
                    "--sharing=no", "--lock=no", "--idle-timeout=0",
                    f"--server-idle-timeout={max(0, idle_timeout)}",
                    "--terminate-children=yes", "--exit-with-client=no", f"--start-child={shlex.join(argv)}"]
            with self._lock:
                session.directory = directory
                if self._closed or session.stop_requested.is_set():
                    raise XpraError(409, "XPRA_SESSION_CANCELLED", "Session creation was cancelled.", "Refresh the session list.")
                session.process = subprocess.Popen(args, cwd=working_dir, env=child_env, stdout=subprocess.PIPE,
                                                   stderr=subprocess.STDOUT, start_new_session=True)
                session.worker = threading.Thread(target=self._watch, args=(session,), daemon=True, name=f"xpra-{session.id[:8]}")
                session.worker.start()
            deadline = time.monotonic() + self.options["startup_timeout"]
            while time.monotonic() < deadline:
                if session.stop_requested.is_set():
                    raise XpraError(409, "XPRA_SESSION_CANCELLED", "Session creation was cancelled.", "Refresh the session list.")
                if session.process.poll() is not None:
                    raise XpraError(503, "XPRA_START_FAILED", "Xpra exited before its HTML5 service became ready.",
                                    "Inspect log_tail and fix the Xpra/X11 installation or application command. Independent sessions need X11 server support; a Linux container can provide it.")
                try:
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.settimeout(0.3)
                        connection.connect(socket_path)
                        connection.sendall(b"GET /index.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                        response = http.client.HTTPResponse(connection)
                        response.begin()
                        if response.status == 200 and "text/html" in response.getheader("Content-Type", ""):
                            with self._lock:
                                if not session.stop_requested.is_set() and session.process.poll() is None:
                                    session.status = "running"
                                    return self._snapshot(session)
                        if response.status == 404:
                            raise XpraError(503, "XPRA_HTML5_MISSING", "Xpra could not serve its HTML5 client.",
                                            "Install xpra-html5 or set cmd_api.xpra.html_dir to its resource directory.")
                except (OSError, http.client.HTTPException):
                    pass
                session.stop_requested.wait(0.1)
            raise XpraError(504, "XPRA_START_TIMEOUT", "Xpra did not become ready before the startup deadline.",
                            "Inspect log_tail, verify the display/HTML5 installation, or increase cmd_api.xpra.startup_timeout.")
        except (XpraError, OSError) as exc:
            self._stop(session)
            error = exc if isinstance(exc, XpraError) else XpraError(
                503, "XPRA_START_FAILED", "The Xpra process could not be started.", "Check executable permissions and the configured runtime directories.")
            with self._lock:
                session.status = "failed"
                session.last_error = error.detail
                error.detail.update(session_id=session.id, log_tail=list(session.logs))
            raise error from None

    def _watch(self, session):
        """Drain bounded output, reap the child and publish an unexpected exit."""
        process = session.process
        try:
            with process.stdout:
                pending = b""
                while True:
                    try:
                        descendants = psutil.Process(process.pid).children(recursive=True)
                    except psutil.Error:
                        descendants = []
                    # Xvfb starts its own process group. Retain identity-checked
                    # handles so a crashed parent cannot orphan its display.
                    with self._lock:
                        session.children = {pid: child for pid, child in session.children.items() if child.is_running()}
                        session.children.update((child.pid, child) for child in descendants)
                    ready, _, _ = select.select([process.stdout], [], [], .1)
                    if ready:
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            break
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        if len(pending) > 8192:
                            lines.append(pending)
                            pending = b""
                        with self._lock:
                            session.logs.extend(self._redact(line.decode("utf-8", "replace").rstrip(), session) for line in lines)
                    # A grandchild may inherit the output pipe after Xpra crashes.
                    # Its open descriptor must not prevent reaping the server.
                    if process.poll() is not None:
                        break
                if pending:
                    with self._lock:
                        session.logs.append(self._redact(pending.decode("utf-8", "replace"), session))
            code = process.wait()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # A reaped parent's group may no longer be signalable. Continue
                # with identity-checked descendants before releasing capacity.
                pass
            self._reap_children(session)
            with self._lock:
                if session.status != "failed":
                    session.status = "exited" if code == 0 or session.stop_requested.is_set() else "failed"
                    if session.status == "failed":
                        session.last_error = dict(error_code="XPRA_PROCESS_EXITED", message=f"Xpra exited with status {code}.",
                                                  next_action="Inspect log_tail and create a new session after correcting the failure.")
        finally:
            if session.directory:
                session.directory.cleanup()

    def _reap_children(self, session):
        """Reap recorded descendants, including children with separate groups."""
        with self._lock:
            children = list(session.children.values())
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(children, timeout=1)

    def _stop(self, session):
        """Stop only this session's process tree and release its private resources."""
        session.stop_requested.set()
        with session.stop_lock:
            with self._lock:
                process = session.process
                if process is not None and process.poll() is None:
                    session.status = "stopping"
            if process is not None and process.poll() is None:
                try:
                    descendants = psutil.Process(process.pid).children(recursive=True)
                    with self._lock:
                        session.children.update((child.pid, child) for child in descendants)
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, psutil.Error):
                    pass
                try:
                    process.wait(timeout=self.options["shutdown_timeout"])
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            self._reap_children(session)
            if session.worker and session.worker is not threading.current_thread():
                session.worker.join(timeout=1)
            if session.directory:
                session.directory.cleanup()
            with self._lock:
                if session.status != "failed":
                    session.status = "exited"

    def delete(self, session_id):
        """Stop an owned session and remove its in-memory record."""
        with self._lock:
            self.get(session_id)
            session = self._sessions[session_id]
        self._stop(session)
        with self._lock:
            self._sessions.pop(session_id, None)
        return dict(id=session_id, deleted=True)

    def close(self):
        """Reject new work and synchronously clean up every owned session."""
        with self._lock:
            self._closed = True
            sessions = list(self._sessions.values())
        for session in sessions:
            self._stop(session)
