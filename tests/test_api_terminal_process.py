"""PTY subprocess regressions for threaded Web Console startup and cleanup."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pty
import select
import shlex
import signal
import sys
import time

import pytest

from ucagent.server import api_terminal
from ucagent.server.api_terminal import _ManagedProcess


def _python_command(code: str) -> str:
    """Replace the shell with a Python probe so signals target the probe."""
    return "exec " + shlex.join([sys.executable, "-u", "-c", code])


def _read_until(process: _ManagedProcess, marker: bytes) -> bytes:
    """Read PTY output up to a marker with a bounded failure deadline."""
    output = b""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.master_fd], [], [], 0.05)
        if ready:
            try:
                chunk = os.read(process.master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
            if marker in output:
                return output
    pytest.fail(f"Missing PTY marker {marker!r}; received {output!r}")


@pytest.fixture
def processes():
    """Reap all probe subprocesses and release their PTYs even after failures."""
    running = []
    yield running
    for process in running:
        if process.pid is not None:
            process.kill()
            process.wait(timeout=5)
        process.close_fd()


def test_threaded_process_has_controlling_tty_and_supports_input_and_resize(processes):
    """A threaded spawn must retain terminal I/O, session ownership and SIGWINCH."""
    code = """
import json, os, signal, sys

def resized(signum, frame):
    print('RESIZED:' + json.dumps(list(os.get_terminal_size(0))), flush=True)

signal.signal(signal.SIGWINCH, resized)
with open('/dev/tty') as tty:
    snapshot = {
        'ttys': [os.isatty(fd) for fd in (0, 1, 2)],
        'controlling_tty': tty.isatty(),
        'session_leader': os.getsid(0) == os.getpid(),
        'foreground_group': os.tcgetpgrp(0) == os.getpgrp(),
        'size': list(os.get_terminal_size(0)),
        'term': os.environ['TERM'],
        'columns': os.environ['COLUMNS'],
        'lines': os.environ['LINES'],
        'custom': os.environ['UCAGENT_PTY_TEST_VALUE'],
    }
print('READY:' + json.dumps(snapshot), flush=True)
print('INPUT:' + sys.stdin.readline().strip(), flush=True)
"""
    process = _ManagedProcess(_python_command(code), {"UCAGENT_PTY_TEST_VALUE": "inherited"})
    processes.append(process)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(process.start, 93, 31).result(timeout=5)

    output = _read_until(process, b"READY:")
    snapshot = json.loads(output.split(b"READY:", 1)[1].splitlines()[0])
    assert snapshot == {
        "ttys": [True, True, True],
        "controlling_tty": True,
        "session_leader": True,
        "foreground_group": True,
        "size": [93, 31],
        "term": "xterm-256color",
        "columns": "93",
        "lines": "31",
        "custom": "inherited",
    }
    assert process.alive
    assert process.poll() is None
    process.resize(110, 45)
    assert b"RESIZED:[110, 45]" in _read_until(process, b"RESIZED:[110, 45]")
    process.write(b"terminal input\n")
    assert b"INPUT:terminal input" in _read_until(process, b"INPUT:terminal input")
    assert process.wait(timeout=5) == 0
    assert process.alive is False


@pytest.mark.parametrize("exit_code", [0, 7])
def test_process_poll_retains_exit_status_and_reaps_child(processes, exit_code):
    """Repeated polling must preserve both successful and failed exit statuses."""
    process = _ManagedProcess(_python_command(f"raise SystemExit({exit_code})"))
    processes.append(process)
    process.start()
    assert process.wait(timeout=5) == exit_code
    assert process.poll() == exit_code
    assert process.poll() == exit_code
    assert process.alive is False
    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)
    fd = process.master_fd
    process.close_fd()
    process.close_fd()
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize("method,signum", [("terminate", signal.SIGTERM), ("kill", signal.SIGKILL)])
def test_process_signals_retain_signal_exit_status(processes, method, signum):
    """Termination and forced shutdown must reap the child with a signal status."""
    process = _ManagedProcess(_python_command("import time; print('READY'); time.sleep(30)"))
    processes.append(process)
    process.start()
    _read_until(process, b"READY")
    getattr(process, method)()
    assert process.wait(timeout=5) == -signum
    assert process.poll() == -signum
    getattr(process, method)()


@pytest.mark.parametrize("failure_point", ["ioctl", "spawn"])
def test_process_start_failure_closes_both_pty_descriptors(monkeypatch, failure_point):
    """A terminal setup or spawn failure must release both newly opened FDs."""
    import fcntl

    descriptors = pty.openpty()
    monkeypatch.setattr(pty, "openpty", lambda: descriptors)

    def fail(*args, **kwargs):
        """Simulate a failure before a subprocess takes ownership of the PTY."""
        raise OSError("terminal setup failed")

    if failure_point == "ioctl":
        monkeypatch.setattr(fcntl, "ioctl", fail)
    else:
        monkeypatch.setattr(api_terminal.subprocess, "Popen", fail)
    process = _ManagedProcess("true")
    with pytest.raises(OSError, match="terminal setup failed"):
        process.start()
    assert process.pid is None
    assert process.alive is False
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
