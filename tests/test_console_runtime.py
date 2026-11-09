"""Console sessions use shared operations and never change process working directory."""

from ucagent.interfaces.terminal.presentation import format_result, format_operation
import io
import os
import threading

import pytest

from test_runtime_host import make_host
from ucagent.interfaces.terminal.console import Console
from ucagent.runtime.session import RuntimeSession
from ucagent.runtime.output import OutputBuffer


@pytest.fixture
def console(tmp_path):
    """Create a real console and host while keeping test output and state isolated."""
    host, runtime = make_host(tmp_path)
    runtime.agent.cfg.set_value("backend", {"key_name": "test"})
    runtime.agent.status_info = lambda: {"LLM": "test-model", "Run Time": "0s"}
    runtime.agent.test_tools = []
    runtime.agent.message_echo_handler = None
    runtime.agent.set_message_echo_handler = lambda handler: setattr(runtime.agent, "message_echo_handler", handler)
    runtime.agent.unset_message_echo_handler = lambda: setattr(runtime.agent, "message_echo_handler", None)
    frontend = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
    host.attach_control("test-console")
    host.start()
    yield frontend
    host.request_shutdown()
    assert host.wait(3)["instance"] == "closed"


def test_aliases_and_foreground_cancellation_are_session_local(console):
    """Cancelling a console operation leaves another session's operation running."""
    other = RuntimeSession(console.host, result_formatter=format_result, operation_formatter=format_operation)
    first = console.execute_line("sleep 10").data
    second = other.execute_line("sleep 10").data
    assert console.cancel_foreground()
    assert console.host.operations.wait(first["id"], 2)["state"] == "cancelled"
    assert console.host.operations.get(second["id"])["state"] == "running"
    assert other.cancel_foreground()
    for name in ("nr", "next_round"):
        operation = console.execute_line(name).data
        assert console.host.operations.wait(operation["id"], 2)["state"] == "succeeded"
    assert console.agent.invoke_round == 2


def test_directories_history_and_explicit_shell_are_independent(console, tmp_path):
    """Directory changes are per session; history survives frontend reconstruction."""
    original = os.getcwd()
    (tmp_path / "child").mkdir()
    console.execute_line("cd child")
    assert os.getcwd() == original
    other = RuntimeSession(console.host, result_formatter=format_result, operation_formatter=format_operation)
    assert other.session.cwd == tmp_path
    console.save_cmd_history()
    restored = RuntimeSession(console.host, result_formatter=format_result, operation_formatter=format_operation)
    assert restored.history == ["cd child"]
    operation = console.execute_line("shell pwd").data
    assert console.host.operations.wait(operation["id"], 2)["stdout"].strip() == str(tmp_path / "child")


def test_output_bridge_has_one_wrapper_and_restores_streams(monkeypatch):
    """Two resource owners share capture plumbing and releasing one preserves the other."""
    import sys
    from ucagent.util.log import info
    original = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original)
    one, two = OutputBuffer(), OutputBuffer()
    one.install()
    bridge = sys.stdout
    two.install()
    try:
        assert sys.stdout is bridge
        info("one-line")
        assert len([line for line in one.get_lines() if "one-line" in line]) == 1
        one.close()
        assert sys.stdout is bridge
        print("remaining")
        assert two.get_lines()[-1] == "remaining"
    finally:
        two.close()
    assert sys.stdout is original


def test_real_pty_tui_detach_and_foreground_interrupt(tmp_path):
    """A real terminal can leave TUI, cancel a shell, and retain a responsive console."""
    import pty
    import select
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = '''
import sys
from pathlib import Path
sys.path.insert(0, "tests")
from test_runtime_host import make_host
from ucagent.interfaces.terminal.console import Console
from ucagent.interfaces.terminal.tui import enter_tui
host, runtime = make_host(Path(sys.argv[1]))
runtime.agent.cfg.set_value("backend", {"key_name": "test"})
runtime.agent.test_tools = []
console = Console(host, tui_factory=enter_tui)
host.start()
with host.signals():
    console.run()
host.request_shutdown()
assert host.wait(5)["instance"] == "closed"
'''
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, "-c", source, str(tmp_path)], cwd=root,
                               stdin=slave, stdout=slave, stderr=slave,
                               env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    transcript = bytearray()

    def read_until(marker):
        """Drain the real PTY until observable output arrives within a bounded deadline."""
        deadline = time.monotonic() + 10
        while marker not in transcript:
            assert process.poll() is None, transcript.decode(errors="replace")
            assert time.monotonic() < deadline, transcript.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                transcript.extend(os.read(master, 65536))

    try:
        read_until(b"(UnityChip) ")
        os.write(master, b"tui\n")
        read_until(b"0.00 tok/s")
        os.write(master, b"\x11")
        read_until(b'"attached": false')
        os.write(master, b"shell sleep 30\n")
        read_until(b"shell: ")
        process.send_signal(signal.SIGINT)
        os.write(master, b"pwd\nquit\n")
        process.wait(timeout=10)
        assert process.returncode == 0, transcript.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_console_completed_notice_and_confirmation_are_session_scoped(console):
    """Terminal polling emits one terminal result and approval does not persist."""
    result = console.execute_line("shell exit 7")
    record = console.host.operations.wait(result.data["id"], 3)
    assert record["state"] == "failed"
    text = console.completed_output()
    assert "process_failed:" in text and '"returncode": 7' in text
    assert console.completed_output() == ""
    assert not console.session.confirmed


def test_console_created_after_host_start_does_not_recapture_its_display(console):
    """A late console writes to the underlying terminal without queuing its own redraw."""
    from ucagent.runtime.output import StreamBridge

    other = Console(console.host)
    assert not isinstance(other.output, StreamBridge)
    other.output = io.StringIO()
    other.display_result(other.execute_line("status"))
    assert "LLM: test-model" in other.output.getvalue()
    assert other.frontend.drain_output() == ""


def test_real_pty_console_edits_cursor_history_and_quoted_completion(tmp_path):
    """The interactive reader supports editing without interrupting streamed operation output."""
    import pty
    import select
    import subprocess
    import sys
    import time
    from pathlib import Path

    (tmp_path / "two words.txt").write_text("COMPLETED_FILE")
    root = Path(__file__).resolve().parents[1]
    source = '''
import sys
from pathlib import Path
sys.path.insert(0, "tests")
from test_runtime_host import make_host
from ucagent.interfaces.terminal.console import Console
host, runtime = make_host(Path(sys.argv[1]))
frontend = Console(host)
host.start()
with host.signals():
    frontend.run()
host.request_shutdown()
assert host.wait(5)["instance"] == "closed"
'''
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, "-c", source, str(tmp_path)], cwd=root,
                               stdin=slave, stdout=slave, stderr=slave,
                               env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    received = bytearray()

    def read_until(marker):
        """Drain a terminal until a deterministic output appears or its deadline expires."""
        deadline = time.monotonic() + 10
        while marker not in received:
            assert process.poll() is None and time.monotonic() < deadline, received.decode(errors="replace")[-6000:]
            if select.select([master], [], [], 0.1)[0]:
                received.extend(os.read(master, 65536))

    try:
        read_until(b"(UnityChip) ")
        # Insert the missing letter inside the word, then move back to its end.
        os.write(master, b"shell printf 'EDIT_OK'\x01\x1b[C\x1b[C\x1b[C\x04l\x05\n")
        read_until(b"shell: ")
        # A quoted partial filename is completed as one executable shell argument.
        os.write(master, b'shell cat "two w\t\n')
        read_until(b"COMPLETED_FILE")
        # Restore the last command, return to the draft and replace it with pwd.
        os.write(master, b"draft\x1b[A\x1b[B\x15pwd\n")
        read_until(b"cwd:")
        os.write(master, b"quit\n")
        process.wait(timeout=10)
        assert process.returncode == 0, received.decode(errors="replace")[-6000:]
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_temporary_capture_restores_streams_and_keeps_runtime_owners_separate(monkeypatch):
    """A UI capture neither echoes its output nor redirects another host's worker logs."""
    import sys
    from ucagent.runtime.output import OUTPUT_OWNER

    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    one, two = OutputBuffer(), OutputBuffer()
    with pytest.raises(RuntimeError, match="view failed"):
        with one.capture():
            print("view-output")
            token = OUTPUT_OWNER.set(two)
            try:
                print("other-runtime")
            finally:
                OUTPUT_OWNER.reset(token)
            raise RuntimeError("view failed")
    assert sys.stdout is stdout and sys.stderr is stderr
    assert stdout.getvalue() == ""
    assert one.get_lines() == ["view-output"]
    assert two.get_lines() == ["other-runtime"]


def test_console_prompt_follows_terminal_input_readiness(console, monkeypatch):
    """Control keys cannot arrive while the visible prompt still has canonical input mode."""
    from unittest.mock import Mock
    events = []
    stream = Mock()
    stream.fileno.return_value = 37
    stream.isatty.return_value = True
    output = Mock()
    output.write.side_effect = lambda text: events.append(("output", text))
    frontend = Console(console.host, session=console, input_stream=stream, output_stream=output)
    monkeypatch.setattr("termios.tcgetattr", lambda fd: ["original"])
    monkeypatch.setattr("termios.tcsetattr", lambda *args: events.append(("restore", args[2])))
    monkeypatch.setattr("tty.setcbreak", lambda *args: events.append(("ready", args[0])))
    monkeypatch.setattr("select.select", lambda *args: ([37], [], []))
    monkeypatch.setattr("os.read", lambda *args: b"\n")
    monkeypatch.setattr(frontend, "_flush_output", lambda *args: None)
    assert frontend._readline("READY> ") == "\n"
    assert events[:2] == [("ready", 37), ("output", "READY> ")]
    assert events[-1] == ("restore", ["original"])
