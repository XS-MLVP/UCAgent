import io
import os
import shlex
import sys
import tempfile

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.server import api_terminal
from ucagent.server.api_terminal import PdbWebTermServer, _get_web_console_exit_code


def test_web_console_process_capture_records_traceback_from_pty():
    capture = tempfile.NamedTemporaryFile(delete=False)
    capture.close()
    try:
        command = shlex.join([
            sys.executable,
            "-c",
            (
                "import sys; "
                "print('stdout before'); "
                "print('stderr before', file=sys.stderr); "
                "raise RuntimeError('web console boom')"
            ),
        ])
        server = PdbWebTermServer(
            command,
            host="127.0.0.1",
            port=0,
            title="test",
            process_output_capture_path=capture.name,
        )

        server.start_blocking()

        assert _get_web_console_exit_code(server) not in (None, 0)
        output = open(capture.name, "rb").read().decode("utf-8", "replace")
        assert "stdout before" in output
        assert "stderr before" in output
        assert "Traceback (most recent call last)" in output
        assert "RuntimeError: web console boom" in output
    finally:
        os.unlink(capture.name)


def test_web_console_prints_traceback_even_when_exit_code_is_zero(monkeypatch):
    capture = tempfile.NamedTemporaryFile(delete=False)
    try:
        lines = [f"noise {i}\n".encode() for i in range(120)]
        lines += [
            b"UCAgent encountered an error: boom\n",
            b"Traceback (most recent call last):\n",
            b"  File \"demo.py\", line 1, in <module>\n",
            b"RuntimeError: boom\n",
            b"UCAgent is exited.\n",
        ]
        capture.write(b"".join(lines))
        capture.close()
        stderr = io.StringIO()
        monkeypatch.setattr(api_terminal.sys, "stderr", stderr)

        api_terminal._print_web_console_abnormal_exit_output(0, capture.name)

        replayed = stderr.getvalue()
        assert "Command exited abnormally with code 0" in replayed
        assert "Traceback (most recent call last)" in replayed
        assert "RuntimeError: boom" in replayed
        assert "noise 0" not in replayed
        assert "noise 119" in replayed
    finally:
        try:
            os.unlink(capture.name)
        except OSError:
            pass


def test_cli_writes_exception_to_web_console_capture_arg():
    capture = tempfile.NamedTemporaryFile(delete=False)
    capture.close()
    try:
        command = shlex.join([
            sys.executable,
            os.path.abspath(os.path.join(current_dir, "..", "ucagent", "cli.py")),
            "/tmp/no-workspace",
            "NoDut",
            "--extra-skill-path",
            "bad-skill-path",
            "--web-console-capture-path",
            capture.name,
        ])
        server = PdbWebTermServer(
            command,
            host="127.0.0.1",
            port=0,
            title="test",
            process_output_capture_path=capture.name,
        )

        server.start_blocking()

        output = open(capture.name, "rb").read().decode("utf-8", "replace")
        assert "UCAgent encountered an error" in output
        assert "--extra-skill-path requires --use-skill is True" in output
    finally:
        os.unlink(capture.name)
