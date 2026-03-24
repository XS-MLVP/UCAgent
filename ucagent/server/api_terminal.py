# -*- coding: utf-8 -*-
"""Web-based terminal server for UCAgent.

Provides two operating modes:

1. **Process mode** – spawns a command as a subprocess and relays its
   stdin / stdout / stderr over a WebSocket.  The subprocess is started
   once and survives browser refreshes or disconnects; new WebSocket
   connections simply re-attach to the running process.

2. **Console mode** – mirrors the hosting process's stdout into connected
   browsers and forwards browser input to a callback (e.g. ``pdb.add_cmds``).
   Works with both the PDB command line and the Textual TUI.

Both modes are exposed via a lightweight aiohttp server that serves an
xterm.js-based HTML page on ``/`` and a WebSocket endpoint on ``/ws``.

REST API endpoints:

- ``GET  /api/status``  – server status + number of connected clients
- ``GET  /api/clients`` – detailed list of connected WebSocket clients
"""

from __future__ import annotations

import atexit
import asyncio
import base64
import collections
import hmac
import json
import logging
import os
import pathlib
import signal
import struct
import sys
import threading
import time
import shlex

from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from aiohttp import WSMsgType, web

log = logging.getLogger("ucagent.terminal")

# Directory paths for templates and static assets
_SERVER_DIR = pathlib.Path(__file__).resolve().parent
_TEMPLATE_DIR = _SERVER_DIR / "templates"
_STATIC_DIR = _SERVER_DIR / "static"

def _build_web_console_command(argv: Optional[List[str]] = None) -> str:
    """Build the subprocess command served by textual-serve."""
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cli_path = os.path.normpath(os.path.join(current_dir, "..", "cli.py"))
    cmd = [
        "env",
        "PYTHONWARNINGS=ignore",
        sys.executable,
        cli_path,
        *raw_args,
    ]
    return shlex.join(cmd)


def _extract_web_console_spec(argv: Optional[List[str]] = None) -> str:
    """Extract web-console optional value from argv."""
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    for i, arg in enumerate(raw_args):
        if arg == "--web-console":
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                return raw_args[i + 1]
            return ""
        if arg.startswith("--web-console="):
            return arg.split("=", 1)[1]
    return ""


def _parse_web_console_spec(spec: str) -> tuple[str, int, str]:
    """Parse '--web-console host:port[:password]' value."""
    if not spec or str(spec).strip() == "-1":
        return "localhost", 8000, ""
    parts = spec.split(":", 2)
    if len(parts) < 2:
        raise ValueError(
            f"Invalid --web-console value '{spec}'. Expected format: base_url:port[:password]"
        )
    host = parts[0].strip()
    if not host:
        raise ValueError(
            f"Invalid --web-console value '{spec}'. base_url cannot be empty."
        )
    port_str = parts[1].strip()
    try:
        port = int(port_str)
    except ValueError as e:
        raise ValueError(
            f"Invalid --web-console value '{spec}'. Port must be an integer."
        ) from e
    if port == -1:
        port = 8000
    elif port < 1 or port > 65535:
        raise ValueError(
            f"Invalid --web-console value '{spec}'. Port must be in range 1..65535."
        )
    password = parts[2] if len(parts) == 3 else ""
    return host, port, password


def _resolve_web_console_bind(spec: str) -> tuple[str, int, str]:
    """Resolve final web-console bind host/port/password with conflict policy."""
    from ucagent.util.functions import find_available_port, is_port_free
    host, port, password = _parse_web_console_spec(spec)
    if ":-1" in str(spec):
        return host, find_available_port(start_port=port, end_port=65535), password
    if is_port_free(host, port):
        return host, port, password
    # Bare '--web-console' uses defaults. If default 8000 is busy, auto-increase.
    if spec.strip() == "":
        return host, find_available_port(start_port=port, end_port=65535), password
    raise ValueError(
        f"Port {port} on host '{host}' is unavailable for --web-console."
    )


def _serve_web_console(argv: Optional[List[str]] = None) -> None:
    """Serve the UCAgent TUI in a browser via a PTY-based web terminal."""
    command = _build_web_console_command(argv)
    web_console_spec = _extract_web_console_spec(argv)
    host, port, password = _resolve_web_console_bind(web_console_spec)
    server = PdbWebTermServer(
        command + f" --web-console-session-host={host} --web-console-session-port={port}",
        host=host,
        port=port,
        password=password,
        title="UCAgent Terminal",
    )
    server.start_blocking()

# ---------------------------------------------------------------------------
# Shared ring-buffer for recent output (so reconnecting clients can scroll
# back a bit).
# ---------------------------------------------------------------------------

_DEFAULT_SCROLLBACK = 5000  # chunks kept in memory


class _OutputRing:
    """Thread-safe ring-buffer that stores raw bytes chunks."""

    def __init__(self, max_chunks: int = _DEFAULT_SCROLLBACK) -> None:
        self._buf: Deque[bytes] = collections.deque(maxlen=max_chunks)
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        with self._lock:
            self._buf.append(data)

    def snapshot(self) -> bytes:
        """Return a single bytes blob of the entire scrollback."""
        with self._lock:
            return b"".join(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# ---------------------------------------------------------------------------
# Process mode helpers
# ---------------------------------------------------------------------------

class _ManagedProcess:
    """Wraps a single long-lived subprocess with a pty so that curses /
    readline / Textual apps work correctly."""

    def __init__(self, command: str, env: Optional[Dict[str, str]] = None) -> None:
        self.command = command
        self._env = env
        self._master_fd: Optional[int] = None
        self._pid: Optional[int] = None
        self._alive = False
        self._exit_code: Optional[int] = None

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def pid(self) -> Optional[int]:
        return self._pid

    @property
    def master_fd(self) -> int:
        assert self._master_fd is not None
        return self._master_fd

    def start(self, cols: int = 120, rows: int = 40) -> None:
        """Fork/exec via pty."""
        import fcntl
        import pty
        import termios

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"] = str(rows)
        if self._env:
            env.update(self._env)

        master_fd, slave_fd = pty.openpty()

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        child_pid = os.fork()
        if child_pid == 0:
            # ── child ──
            os.close(master_fd)
            os.setsid()

            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvpe("/bin/sh", ["/bin/sh", "-c", self.command], env)

        # ── parent ──
        os.close(slave_fd)
        self._master_fd = master_fd
        self._pid = child_pid
        self._alive = True

    def resize(self, cols: int, rows: int) -> None:
        if self._master_fd is None:
            return
        import fcntl
        import termios

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def write(self, data: bytes) -> None:
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

    def poll(self) -> Optional[int]:
        """Non-blocking wait; returns exit code or None if still running."""
        if self._pid is None:
            return self._exit_code
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            self._alive = False
            self._exit_code = -1
            return self._exit_code
        if pid == 0:
            return None
        self._alive = False
        if os.WIFEXITED(status):
            self._exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self._exit_code = -os.WTERMSIG(status)
        else:
            self._exit_code = -1
        return self._exit_code

    def terminate(self) -> None:
        if self._pid is not None and self._alive:
            try:
                os.kill(self._pid, signal.SIGTERM)
            except OSError:
                pass

    def kill(self) -> None:
        if self._pid is not None and self._alive:
            try:
                os.kill(self._pid, signal.SIGKILL)
            except OSError:
                pass

    def close_fd(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None


# ---------------------------------------------------------------------------
# Console-capture helper (for console mode)
# ---------------------------------------------------------------------------

class _ConsoleMirror:
    """Wraps ``sys.stdout`` so every write is also fanned-out to connected
    WebSocket clients.  The original stream is preserved and written to first.
    """

    def __init__(self, original: Any) -> None:
        self._original = original
        self._callbacks: List[Callable[[bytes], Any]] = []
        self._lock = threading.Lock()
        self._ring = _OutputRing()
        self._paused = False

    # ── stream interface ─────────────────────────────────────────────
    def write(self, s: str | bytes) -> int:
        if isinstance(s, (bytes, bytearray)):
            raw = bytes(s)
            text = s.decode("utf-8", "replace")
        else:
            text = s
            raw = s.encode("utf-8", "replace")
        self._original.write(text)
        # xterm.js needs \r\n for proper newlines; Python stdout only sends \n.
        ws_raw = raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        self._ring.append(ws_raw)
        if not self._paused:
            with self._lock:
                for cb in self._callbacks:
                    try:
                        cb(ws_raw)
                    except Exception:
                        pass
        return len(text)

    def flush(self) -> None:
        self._original.flush()

    def isatty(self) -> bool:
        return getattr(self._original, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._original, "errors", "replace")

    def set_callbacks_paused(self, paused: bool) -> None:
        """Temporarily pause/resume WebSocket callbacks.

        Used when PTY mode is active — the PTY reader thread handles
        output forwarding instead of per-write callbacks."""
        self._paused = paused

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    # ── subscription ─────────────────────────────────────────────────
    def add_callback(self, cb: Callable[[bytes], Any]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    def remove_callback(self, cb: Callable[[bytes], Any]) -> None:
        with self._lock:
            try:
                self._callbacks.remove(cb)
            except ValueError:
                pass

    @property
    def ring(self) -> _OutputRing:
        return self._ring


# ---------------------------------------------------------------------------
# Connected client info
# ---------------------------------------------------------------------------

class _ClientInfo:
    """Metadata about a single WebSocket client."""

    def __init__(self, ws: web.WebSocketResponse, request: web.Request,
                 session_id: str) -> None:
        self.ws = ws
        self.session_id = session_id
        self.remote = request.remote or "unknown"
        self.user_agent = request.headers.get("User-Agent", "unknown")
        self.connected_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "remote": self.remote,
            "user_agent": self.user_agent,
            "connected_at": self.connected_at,
            "duration_s": round(time.time() - self.connected_at, 1),
        }


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------

def _load_template(name: str) -> str:
    """Load an HTML template from the templates directory."""
    path = _TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

class PdbWebTermServer:
    """Lightweight aiohttp server that serves a web terminal via WebSocket.

    **Process mode** (default):  ``command`` is spawned once in a pty.
    Multiple browser tabs share the same session; closing the browser does
    NOT kill the process.

    **Console mode**:  initialized with ``console_input_callback`` – the
    hosting process's stdout is captured and fanned-out to browsers.
    Browser keyboard input is forwarded to the callback.

    Endpoints
    ---------
    GET  /                – xterm.js terminal page
    GET  /ws              – WebSocket for terminal I/O
    GET  /static/{path}   – static assets (xterm.js, addons, CSS)
    GET  /api/status      – server status JSON (uptime, client count, mode)
    GET  /api/clients     – detailed list of connected clients

    Parameters
    ----------
    command : str or None
        Shell command to run (process mode).  ``None`` for console mode.
    host : str
        Bind address for the HTTP server.
    port : int
        Port for the HTTP server.
    password : str
        If non-empty, HTTP Basic Auth is required.
    title : str
        Title shown in the browser tab.
    env : dict or None
        Extra environment variables for the subprocess (process mode).
    console_input_callback : callable or None
        ``func(text: str) -> None`` called when the browser user types
        something (console mode only).
    """

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        host: str = "localhost",
        port: int = 8000,
        password: str = "",
        title: str = "UCAgent Terminal",
        env: Optional[Dict[str, str]] = None,
        console_input_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.command = command
        self.host = host
        self.port = port
        self.password = password
        self.title = title
        self._env = env
        self.started_at: Optional[float] = None

        # Process mode state
        self._process: Optional[_ManagedProcess] = None
        self._output_ring = _OutputRing()
        self._reader_task: Optional[asyncio.Task] = None

        # Console mode state
        self._console_cb = console_input_callback
        self._console_mirror: Optional[_ConsoleMirror] = None

        # Connected clients: session_id → _ClientInfo
        self._clients: Dict[str, _ClientInfo] = {}
        self._clients_lock = asyncio.Lock()

        # Server state
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # PTY mode state (for TUI support)
        self._pty_active = False
        self._pty_master_fd: Optional[int] = None
        self._pty_slave_fd: Optional[int] = None
        self._pty_saved_fds: Optional[Tuple[int, int, int]] = None
        self._pty_reader_thread: Optional[threading.Thread] = None
        self._pty_stdin_thread: Optional[threading.Thread] = None
        self._pty_saved_termios: Optional[list] = None

        # Last known terminal dimensions (updated by web client resize).
        # Used as initial PTY size in enter_pty_mode() so that the PTY
        # matches the web terminal from the start.
        self._terminal_cols: int = 0
        self._terminal_rows: int = 0
        self._pty_atexit_registered = False

    # ── public API ───────────────────────────────────────────────────

    @property
    def is_process_mode(self) -> bool:
        return self.command is not None

    @property
    def is_running(self) -> bool:
        return self._running

    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def start(self) -> Tuple[bool, str]:
        """Start the web terminal server in a background thread.

        Returns ``(success, message)``."""
        if self._running:
            return False, f"Terminal server already running at {self.url()}"

        ready = threading.Event()
        error_holder: List[str] = []

        def _run() -> None:
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(self._start_async(ready, error_holder))
                self._loop.run_forever()
            except Exception as exc:
                error_holder.append(str(exc))
                ready.set()
            finally:
                self._loop.run_until_complete(self._cleanup_async())
                self._loop.close()
                self._running = False

        self._thread = threading.Thread(target=_run, daemon=True, name="web-terminal")
        self._thread.start()
        ready.wait(timeout=10)

        if error_holder:
            return False, f"Terminal server failed: {error_holder[0]}"

        self._running = True
        self.started_at = time.time()
        return True, f"Terminal server started at {self.url()}"

    def stop(self) -> Tuple[bool, str]:
        """Shut down the server and (in process mode) the subprocess."""
        if not self._running or self._loop is None:
            return False, "Terminal server is not running"

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._running = False
        self.started_at = None
        return True, "Terminal server stopped"

    def start_blocking(self) -> None:
        """Start and block the calling thread (for use as the main entry
        point, e.g. ``_serve_web_console`` replacement)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        ready = threading.Event()
        error_holder: List[str] = []

        try:
            loop.run_until_complete(self._start_async(ready, error_holder))
            if error_holder:
                raise RuntimeError(error_holder[0])
            self._running = True
            self.started_at = time.time()
            self._print_banner()
            print(f"Serving terminal on {self.url()}", file=sys.stderr)
            print("Press Ctrl+C to quit", file=sys.stderr)
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            loop.run_until_complete(self._cleanup_async())
            loop.close()
            self._running = False
            self.started_at = None

    def _print_banner(self) -> None:
        """Print UCAgent ASCII art banner."""
        try:
            from ucagent.version import __version__
        except ImportError:
            __version__ = "unknown"

        banner = f"""
\u001b[34m   __  __   ______    ___                           __ \u001b[0m
\u001b[34m  / / / /  / ____/   /   |   ____ _  ___    ____   / /_\u001b[0m
\u001b[34m / / / /  / /       / /| |  / __ `/ / _ \\  / __ \\ / __/\u001b[0m
\u001b[34m/ /_/ /  / /___    / ___ | / /_/ / /  __/ / / / // /_ \u001b[0m
\u001b[34m\\____/   \\____/   /_/  |_| \\__, /  \\___/ /_/ /_/ \\__/\u001b[0m
\u001b[34m                          /____/                       \u001b[0m \u001b[36mv{__version__}\u001b[0m
"""
        print(banner, file=sys.stderr)

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict for the /api/status endpoint."""
        result: Dict[str, Any] = {
            "running": self._running,
            "mode": ("process" if self.is_process_mode
                     else "pty" if self._pty_active
                     else "console"),
            "host": self.host,
            "port": self.port,
            "url": self.url(),
            "clients": len(self._clients),
            "password_protected": bool(self.password),
        }
        if self.started_at:
            result["uptime_s"] = round(time.time() - self.started_at, 1)
        if self.is_process_mode and self._process is not None:
            result["process_alive"] = self._process.alive
        return result

    def get_clients(self) -> List[Dict[str, Any]]:
        """Return detailed info about all connected WebSocket clients."""
        return [c.to_dict() for c in self._clients.values()]

    # ── PTY mode (for TUI support) ─────────────────────────────────

    def enter_pty_mode(self) -> None:
        """Switch from console mode to PTY mode for TUI support.

        Creates a PTY pair, redirects stdio file descriptors to the PTY
        slave so that Textual (which writes directly to fds) is captured.
        A reader thread forwards PTY output to both the original terminal
        and connected WebSocket clients.  WebSocket input is written raw
        to the PTY master so TUI key handling works.
        """
        if self._pty_active:
            return

        import fcntl
        import pty
        import termios
        import tty

        master_fd, slave_fd = pty.openpty()

        # Determine initial PTY size: prefer the last size reported by
        # a connected web client; fall back to the local terminal size;
        # last resort is 120x40.
        cols, rows = self._terminal_cols, self._terminal_rows
        if cols <= 0 or rows <= 0:
            try:
                sz = os.get_terminal_size()
                cols, rows = sz.columns, sz.lines
            except OSError:
                cols, rows = 120, 40
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Save original file descriptors.
        saved_stdin = os.dup(0)
        saved_stdout = os.dup(1)
        saved_stderr = os.dup(2)

        # Redirect stdio to the PTY slave.
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)

        self._pty_master_fd = master_fd
        self._pty_slave_fd = slave_fd
        self._pty_saved_fds = (saved_stdin, saved_stdout, saved_stderr)

        # Pause _ConsoleMirror WebSocket callbacks to avoid double output.
        if self._console_mirror is not None:
            self._console_mirror.set_callbacks_paused(True)

        # Put the *real* stdin into raw mode so keystrokes are forwarded
        # without line-discipline buffering.
        try:
            self._pty_saved_termios = termios.tcgetattr(saved_stdin)
            tty.setraw(saved_stdin)
        except termios.error:
            self._pty_saved_termios = None

        self._pty_active = True

        # Register an atexit handler so the local terminal is restored
        # even if the program exits without calling exit_pty_mode().
        if not self._pty_atexit_registered:
            atexit.register(self._pty_restore_terminal)
            self._pty_atexit_registered = True

        # Background thread: read PTY master → original terminal + WS
        self._pty_reader_thread = threading.Thread(
            target=self._pty_read_loop,
            args=(master_fd, saved_stdout),
            daemon=True,
            name="pty-reader",
        )
        self._pty_reader_thread.start()

        # Background thread: real stdin → PTY master
        self._pty_stdin_thread = threading.Thread(
            target=self._pty_stdin_relay,
            args=(saved_stdin, master_fd),
            daemon=True,
            name="pty-stdin",
        )
        self._pty_stdin_thread.start()

    def _pty_restore_terminal(self) -> None:
        """Restore the real terminal attributes (atexit safety net).

        Called automatically on interpreter exit so the user's shell
        is not left in raw / no-echo mode.
        """
        if self._pty_saved_fds is not None and self._pty_saved_termios is not None:
            import termios
            try:
                termios.tcsetattr(self._pty_saved_fds[0], termios.TCSANOW,
                                  self._pty_saved_termios)
            except (termios.error, OSError):
                pass

    def set_pty_echo(self, enabled: bool) -> None:
        """Enable or disable ECHO on the PTY slave.

        Disable ECHO before entering TUI to prevent mouse-tracking
        escape sequences from being echoed back.  Re-enable when
        returning to the PDB command line so typed characters are
        visible.
        """
        if not self._pty_active or self._pty_slave_fd is None:
            return
        import termios
        try:
            attr = termios.tcgetattr(self._pty_slave_fd)
            if enabled:
                attr[3] = attr[3] | termios.ECHO
            else:
                attr[3] = attr[3] & ~termios.ECHO
            termios.tcsetattr(self._pty_slave_fd, termios.TCSANOW, attr)
        except (termios.error, OSError):
            pass

    def exit_pty_mode(self) -> None:
        """Switch back from PTY mode to normal console mode."""
        if not self._pty_active:
            return

        self._pty_active = False

        # Restore original file descriptors.
        if self._pty_saved_fds is not None:
            saved_stdin, saved_stdout, saved_stderr = self._pty_saved_fds

            # Restore terminal attributes on real stdin.
            if self._pty_saved_termios is not None:
                import termios
                try:
                    termios.tcsetattr(saved_stdin, termios.TCSANOW,
                                      self._pty_saved_termios)
                except termios.error:
                    pass
                self._pty_saved_termios = None

            os.dup2(saved_stdin, 0)
            os.dup2(saved_stdout, 1)
            os.dup2(saved_stderr, 2)

            os.close(saved_stdin)
            os.close(saved_stdout)
            os.close(saved_stderr)
            self._pty_saved_fds = None

        # Close PTY fds.
        for fd_attr in ("_pty_master_fd", "_pty_slave_fd"):
            fd = getattr(self, fd_attr, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_attr, None)

        # Wait for relay threads to finish.
        for thr_attr in ("_pty_reader_thread", "_pty_stdin_thread"):
            thr = getattr(self, thr_attr, None)
            if thr is not None:
                thr.join(timeout=2)
                setattr(self, thr_attr, None)

        # Unregister the atexit handler since we've cleanly restored.
        if self._pty_atexit_registered:
            atexit.unregister(self._pty_restore_terminal)
            self._pty_atexit_registered = False

        # Re-enable _ConsoleMirror callbacks.
        if self._console_mirror is not None:
            self._console_mirror.set_callbacks_paused(False)

    def _pty_read_loop(self, master_fd: int, output_fd: int) -> None:
        """Read from PTY master, write to original terminal and WS."""
        while self._pty_active:
            try:
                data = os.read(master_fd, 16384)
                if not data:
                    break
            except OSError:
                break

            # Write to the real terminal so local display works.
            try:
                os.write(output_fd, data)
            except OSError:
                pass

            # Scrollback for reconnecting clients.
            self._output_ring.append(data)

            # Broadcast to WebSocket clients.
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._broadcast_bytes(data), self._loop
                )

    def _pty_stdin_relay(self, stdin_fd: int, master_fd: int) -> None:
        """Relay real keyboard input to the PTY master."""
        while self._pty_active:
            try:
                data = os.read(stdin_fd, 1024)
                if not data:
                    break
                os.write(master_fd, data)
            except OSError:
                break

    async def _broadcast_bytes(self, data: bytes) -> None:
        """Send bytes to all connected WebSocket clients."""
        async with self._clients_lock:
            for client in list(self._clients.values()):
                try:
                    if not client.ws.closed:
                        await client.ws.send_bytes(data)
                except Exception:
                    pass

    # ── install console mode capture ─────────────────────────────────

    def install_console_capture(self) -> None:
        """Install stdout mirroring for console mode.  Call this from the
        main thread *before* ``start()``."""
        if self._console_mirror is not None:
            return
        self._console_mirror = _ConsoleMirror(sys.stdout)
        sys.stdout = self._console_mirror  # type: ignore[assignment]

    def uninstall_console_capture(self) -> None:
        if self._console_mirror is not None:
            sys.stdout = self._console_mirror._original  # type: ignore[assignment]
            self._console_mirror = None

    # ── async internals ──────────────────────────────────────────────

    async def _start_async(
        self,
        ready: threading.Event,
        errors: List[str],
    ) -> None:
        app = web.Application()

        # Auth middleware (skip static assets)
        if self.password:
            pwd = self.password

            @web.middleware
            async def auth_mw(request: web.Request, handler: Any) -> web.StreamResponse:
                if request.path.startswith("/static/"):
                    return await handler(request)
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Basic "):
                    try:
                        decoded = base64.b64decode(auth[6:]).decode("utf-8")
                        _, _, p = decoded.partition(":")
                        if hmac.compare_digest(p.encode(), pwd.encode()):
                            return await handler(request)
                    except Exception:
                        pass
                raise web.HTTPUnauthorized(
                    text="Unauthorized",
                    headers={"WWW-Authenticate": 'Basic realm="UCAgent Terminal"'},
                )

            app.middlewares.append(auth_mw)

        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/api/status", self._handle_api_status)
        app.router.add_get("/api/clients", self._handle_api_clients)
        app.router.add_static("/static", _STATIC_DIR, show_index=False)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await self._site.start()
        except Exception as exc:
            errors.append(str(exc))
            ready.set()
            return

        # Process mode: start the managed subprocess immediately so the
        # command begins running even if no browser has connected yet.
        if self.is_process_mode:
            await self._ensure_process()

        ready.set()

    async def _cleanup_async(self) -> None:
        # Close all websockets
        async with self._clients_lock:
            for info in list(self._clients.values()):
                await info.ws.close()
            self._clients.clear()

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

        # Kill subprocess
        if self._process is not None:
            self._process.terminate()
            await asyncio.sleep(0.2)
            if self._process.alive:
                self._process.kill()
            self._process.close_fd()

        # Uninstall console mirror
        self.uninstall_console_capture()

        if self._site is not None:
            await self._site.stop()
        if self._runner is not None:
            await self._runner.cleanup()

    async def _ensure_process(self) -> None:
        """Start the subprocess if not already running."""
        if self._process is not None and self._process.alive:
            return
        assert self.command is not None
        self._output_ring.clear()
        cols, rows = self._terminal_cols, self._terminal_rows
        if cols <= 0 or rows <= 0:
            try:
                sz = os.get_terminal_size()
                cols, rows = sz.columns, sz.lines
            except OSError:
                cols, rows = 120, 40
        proc = _ManagedProcess(self.command, env=self._env)
        proc.start(cols, rows)
        self._process = proc
        self._reader_task = asyncio.ensure_future(self._read_process_output())

    async def _read_process_output(self) -> None:
        """Continuously read from the pty master and broadcast to clients."""
        assert self._process is not None
        loop = asyncio.get_event_loop()
        fd = self._process.master_fd

        while self._process.alive:
            try:
                data = await loop.run_in_executor(None, self._blocking_read, fd)
            except OSError:
                break
            if not data:
                break
            self._output_ring.append(data)
            await self._broadcast(data)

        # Process ended
        exit_code = self._process.poll()
        msg = json.dumps({"type": "exit", "code": exit_code or 0})
        await self._broadcast_text(msg)

        # Stop the event loop so start_blocking() exits
        loop.stop()

    @staticmethod
    def _blocking_read(fd: int) -> bytes:
        try:
            return os.read(fd, 4096)
        except OSError:
            return b""

    async def _broadcast(self, data: bytes) -> None:
        async with self._clients_lock:
            dead: List[str] = []
            for sid, info in self._clients.items():
                try:
                    await info.ws.send_bytes(data)
                except Exception:
                    dead.append(sid)
            for sid in dead:
                self._clients.pop(sid, None)

    async def _broadcast_text(self, text: str) -> None:
        async with self._clients_lock:
            dead: List[str] = []
            for sid, info in self._clients.items():
                try:
                    await info.ws.send_str(text)
                except Exception:
                    dead.append(sid)
            for sid in dead:
                self._clients.pop(sid, None)

    # ── HTTP handlers ────────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        html = _load_template("terminal.html")
        html = html.replace("{{TITLE}}", self.title)
        return web.Response(text=html, content_type="text/html")

    async def _handle_api_status(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_status())

    async def _handle_api_clients(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_clients())

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        session_id = request.query.get("session_id", "")
        if not session_id:
            session_id = f"anon-{id(ws)}"

        # ── Single-session enforcement ───────────────────────────────
        # Only one browser tab can be connected at a time.  If a new
        # connection arrives, reject it (the browser shows the overlay);
        # the user can "Take Over" which sends a new connect with the
        # same mechanism — here we kick the old session.
        async with self._clients_lock:
            if self._clients:
                # There is an existing session.  Check if it's the same
                # session_id (page reload) or a different one (new tab).
                existing = list(self._clients.values())
                for old in existing:
                    if old.session_id == session_id:
                        # Same browser tab reconnecting (page reload)
                        try:
                            await old.ws.close()
                        except Exception:
                            pass
                        self._clients.pop(old.session_id, None)
                    else:
                        # Different tab — kick the old session
                        try:
                            await old.ws.send_str(json.dumps({
                                "type": "takeover",
                                "reason": "Session taken over by another connection.",
                            }))
                            await old.ws.close()
                        except Exception:
                            pass
                        self._clients.pop(old.session_id, None)

            client = _ClientInfo(ws, request, session_id)
            self._clients[session_id] = client

        # Send scrollback history
        if self.is_process_mode:
            history = self._output_ring.snapshot()
        elif self._pty_active:
            history = self._output_ring.snapshot()
        elif self._console_mirror is not None:
            history = self._console_mirror.ring.snapshot()
        else:
            history = b""
        if history:
            await ws.send_bytes(history)

        # Console mode: install a per-client callback to forward stdout
        # (skipped when PTY mode is active — PTY reader handles output)
        console_cb = None
        if not self.is_process_mode and not self._pty_active and self._console_mirror is not None:

            def _on_output(data: bytes) -> None:
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._safe_send_bytes(ws, data), self._loop
                    )

            console_cb = _on_output
            self._console_mirror.add_callback(console_cb)

        line_buf: List[str] = []   # console-mode line buffer

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    text = msg.data
                    try:
                        ctrl = json.loads(text)
                        if isinstance(ctrl, dict) and ctrl.get("type") == "resize":
                            cols = int(ctrl.get("cols", 120))
                            rows = int(ctrl.get("rows", 40))
                            # Remember the latest web dimensions so
                            # enter_pty_mode() can use them for the
                            # initial PTY size.
                            self._terminal_cols = cols
                            self._terminal_rows = rows
                            # Process mode: start process on first resize (with correct size)
                            if self.is_process_mode and (self._process is None or not self._process.alive):
                                await self._ensure_process()
                            elif self._process is not None:
                                self._process.resize(cols, rows)
                                if self._process.pid is not None:
                                    try:
                                        os.killpg(self._process.pid, signal.SIGWINCH)
                                    except (ProcessLookupError, OSError):
                                        try:
                                            os.kill(self._process.pid, signal.SIGWINCH)
                                        except (ProcessLookupError, OSError):
                                            pass
                            if (self._pty_active
                                    and self._pty_slave_fd is not None):
                                import fcntl
                                import termios as _termios
                                winsize = struct.pack(
                                    "HHHH", rows, cols, 0, 0)
                                try:
                                    fcntl.ioctl(
                                        self._pty_slave_fd,
                                        _termios.TIOCSWINSZ,
                                        winsize,
                                    )
                                    os.kill(os.getpid(), signal.SIGWINCH)
                                except OSError:
                                    pass
                            continue
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

                    # Regular input
                    if self.is_process_mode:
                        if self._process is not None and self._process.alive:
                            self._process.write(text.encode("utf-8"))
                    elif self._pty_active:
                        # PTY mode: forward raw keystrokes to PTY master.
                        if self._pty_master_fd is not None:
                            try:
                                os.write(self._pty_master_fd,
                                         text.encode("utf-8"))
                            except OSError:
                                pass
                    else:
                        # Console mode: line-buffered input with echo.
                        # We iterate by index so we can skip multi-char
                        # escape sequences (e.g. \x1b[A for arrow keys).
                        i = 0
                        while i < len(text):
                            ch = text[i]
                            if ch == '\r':  # Enter
                                line = ''.join(line_buf)
                                line_buf.clear()
                                await ws.send_bytes(b'\r\n')
                                if self._console_cb is not None and line:
                                    try:
                                        self._console_cb(line)
                                    except Exception:
                                        pass
                            elif ch in ('\x7f', '\b'):  # Backspace
                                if line_buf:
                                    line_buf.pop()
                                    await ws.send_bytes(b'\b \b')
                            elif ch == '\x03':  # Ctrl+C
                                line_buf.clear()
                                await ws.send_bytes(b'^C\r\n')
                            elif ch == '\x15':  # Ctrl+U — clear line
                                erase = b'\b \b' * len(line_buf)
                                line_buf.clear()
                                if erase:
                                    await ws.send_bytes(erase)
                            elif ch == '\x1b':  # Escape sequence — skip all
                                i += 1
                                if i < len(text) and text[i] == '[':
                                    i += 1  # skip '['
                                    # Skip parameter bytes and final byte
                                    while i < len(text) and text[i] < '@':
                                        i += 1
                                    # skip the final byte (e.g. A/B/C/D)
                                i += 1
                                continue
                            elif ch >= ' ':  # Printable
                                line_buf.append(ch)
                                await ws.send_bytes(ch.encode('utf-8'))
                            i += 1

                elif msg.type == WSMsgType.BINARY:
                    if self.is_process_mode and self._process is not None:
                        self._process.write(msg.data)

                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            async with self._clients_lock:
                self._clients.pop(session_id, None)
            if console_cb is not None and self._console_mirror is not None:
                self._console_mirror.remove_callback(console_cb)

        return ws

    async def _safe_send_bytes(self, ws: web.WebSocketResponse, data: bytes) -> None:
        try:
            if not ws.closed:
                await ws.send_bytes(data)
        except Exception:
            pass
