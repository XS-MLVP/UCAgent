"""Real subprocess coverage for streamed output, idle deadlines and group cleanup."""

import os
from pathlib import Path
import selectors
import shlex
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ucagent.core.backends.cmdline import UCAgentCmdLineBackend
from ucagent.runtime.control.commands import CommandSession
from ucagent.runtime.control.controller import Controller, ControlError
from ucagent.runtime.operations import OperationContext, OperationExecutor
from ucagent.util.config import Config
import ucagent.util.functions as runtime_functions
from ucagent.util.functions import run_shell_process


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Managed process groups require POSIX")


def python_command(source):
    """Replace the shell with an unbuffered Python child using safe argument quoting."""
    return f"exec {shlex.quote(sys.executable)} -u -c {shlex.quote(source)}"


class Agent:
    """Provide the backend's exact pause and output interfaces without startup."""

    def __init__(self, workspace):
        """Create an isolated domain owner with finite command defaults."""
        self.workspace = str(workspace)
        self.output_dir = str(workspace)
        self.cfg = Config({"cmd_timeout": 2})
        self.test_tools = []
        self._break = False
        self.messages = []

    def set_break(self, value):
        """Record pause requests without signals or thread interruption."""
        self._break = value

    def is_break(self):
        """Expose the same pause state to the external command backend."""
        return self._break

    def message_echo(self, text):
        """Retain backend output for assertions."""
        self.messages.append(text)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Observe real output chunks using a condition instead of timing sleeps."""
    owner = OperationExecutor(Controller(Agent(tmp_path)))
    output = threading.Condition()
    original = OperationContext.emit

    def notify(context, stream, text):
        """Publish real output then wake observers waiting for that data."""
        original(context, stream, text)
        with output:
            output.notify_all()

    monkeypatch.setattr(OperationContext, "emit", notify)
    yield owner, CommandSession(tmp_path), output
    assert owner.close(4)["closed"], "Shell test leaked a worker"


def test_output_is_queryable_before_exit_with_separate_streams(runtime, tmp_path):
    """A live process exposes partial lines before an explicit release file appears."""
    owner, session, output = runtime
    gate = tmp_path / "release"
    command = python_command(
        "import sys,time,pathlib; "
        "sys.stdout.write('partial stdout');sys.stdout.flush(); "
        "sys.stderr.write('partial stderr');sys.stderr.flush(); "
        f"gate=pathlib.Path({str(gate)!r});\n"
        "while not gate.exists(): time.sleep(0.01)\n"
        "print(' finished')")
    accepted = owner.execute("shell", {"command": command}, session)
    try:
        with output:
            assert output.wait_for(lambda: ("partial stderr" in owner.get(accepted["id"])["stderr"]
                                            and "partial stdout" in owner.get(accepted["id"])["stdout"]), timeout=3)
        live = owner.get(accepted["id"])
        assert live["state"] == "running" and live["finished_at"] is None
        assert live["stdout"] == "partial stdout"
    finally:
        gate.touch()
    result = owner.wait(accepted["id"], 3)
    assert result["state"] == "succeeded"
    assert result["result"]["returncode"] == 0
    assert result["result"]["stdout"] == "partial stdout finished\n"
    assert result["result"]["stderr"] == "partial stderr"
    with pytest.raises(ChildProcessError):
        os.waitpid(result["result"]["pid"], os.WNOHANG)


def test_silent_process_times_out_and_preserves_real_failure(runtime):
    """Idle timeout is a failed operation, never a successful empty result."""
    owner, session, _ = runtime
    owner.execute("cmd_timeout", {"timeout": "0.15"}, session)
    accepted = owner.execute("shell", {"command": python_command("import time; time.sleep(30)")}, session)
    result = owner.wait(accepted["id"], 4)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "idle_timeout"
    assert result["result"]["reason"] == "timeout"
    assert result["result"]["returncode"] != 0
    assert result["stdout"] == "" and result["stderr"] == ""


def test_bytes_without_newlines_extend_idle_deadline(runtime):
    """A process outliving its initial deadline stays alive while bytes arrive."""
    owner, session, _ = runtime
    owner.execute("cmd_timeout", {"timeout": "0.5"}, session)
    command = python_command("import sys,time\nfor i in range(12):\n sys.stdout.write('.');sys.stdout.flush();time.sleep(0.1)")
    accepted = owner.execute("shell", {"command": command}, session)
    result = owner.wait(accepted["id"], 4)
    assert result["state"] == "succeeded"
    assert result["result"]["stdout"] == "." * 12
    assert result["finished_at"] - result["started_at"] >= 1


def test_nonzero_exit_utf8_and_bounded_output(runtime):
    """Capture true exit codes and incremental UTF-8 without unlimited record growth."""
    owner, session, _ = runtime
    owner.output_limit = 12
    command = python_command("import os,sys; os.write(1,b'x'*30);os.write(1,b'\\xc3');os.write(1,b'\\xa9\\n');print('error',file=sys.stderr);sys.exit(7)")
    result = owner.wait(owner.execute("shell", {"command": command}, session)["id"], 3)
    assert result["state"] == "failed" and result["error"]["code"] == "process_failed"
    assert result["result"]["returncode"] == 7
    assert result["output_truncated"] is True and result["result"]["truncated"] is True
    assert result["stdout"] == "x" * 10 + "é\n"
    assert result["stderr"] == "error\n"
    assert "\ufffd" not in result["stdout"]


def test_cancel_kills_term_ignoring_descendant_and_reaps_parent(runtime, tmp_path):
    """Cancellation escalates to the whole group even after its shell has exited."""
    owner, session, output = runtime
    # A descendant ignores TERM and inherits the output pipes, so only group
    # escalation can finish the operation and close those pipes.
    child_source = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('child-ready',flush=True);time.sleep(30)"
    command = python_command(
        "import subprocess,sys,time,json; "
        f"child=subprocess.Popen([sys.executable,'-u','-c',{child_source!r}]); "
        "print('child-pid='+str(child.pid),flush=True);time.sleep(30)")
    operation = owner.execute("shell", {"command": command}, session)
    with output:
        assert output.wait_for(lambda: ("child-ready" in owner.get(operation["id"])["stdout"]
                                        and "child-pid=" in owner.get(operation["id"])["stdout"]), timeout=3)
    stdout = owner.get(operation["id"])["stdout"]
    child_pid = int(next(line.split("=", 1)[1] for line in stdout.splitlines() if line.startswith("child-pid=")))
    assert owner.cancel(operation["id"])["state"] == "cancelling"
    result = owner.wait(operation["id"], 4)
    assert result["state"] == "cancelled"
    assert result["result"]["reason"] == "cancelled"
    with pytest.raises(ChildProcessError):
        os.waitpid(result["result"]["pid"], os.WNOHANG)
    deadline = time.monotonic() + 2
    running = True
    while running and time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
            if sys.platform.startswith("linux"):
                proc_stat = Path(f"/proc/{child_pid}/stat")
                running = proc_stat.exists() and proc_stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (ProcessLookupError, FileNotFoundError):
            running = False
        if running:
            threading.Event().wait(0.02)
    assert not running, "A cancelled descendant is still executing"
    assert owner.cancel(operation["id"]) == result


def test_session_directories_and_timeouts_are_isolated(runtime, tmp_path):
    """Concurrent sessions retain their own cwd and timeout without os.chdir."""
    owner, one, _ = runtime
    two = CommandSession(tmp_path)
    subdir = tmp_path / "nested directory"
    subdir.mkdir()
    one.cwd = subdir
    original_cwd = Path.cwd()
    assert owner.execute("cmd_timeout", {"timeout": "off"}, one) == {"seconds": 0}
    assert owner.execute("cmd_timeout", {"timeout": None}, two) == {"seconds": 2}
    operation = owner.execute("shell", {"command": "pwd"}, one)
    one.cwd = tmp_path
    result = owner.wait(operation["id"], 3)
    assert result["result"]["stdout"].strip() == str(subdir)
    assert Path.cwd() == original_cwd
    two.cwd = tmp_path.parent
    with pytest.raises(ControlError, match="workspace"):
        owner.execute("shell", {"command": "pwd"}, two)


def test_cancellation_context_reaches_cmdline_backend_without_async_exceptions(runtime):
    """The operation token cancels a CLI process even if pause state is cleared."""
    owner, _, _ = runtime
    backend = UCAgentCmdLineBackend(owner.agent, owner.agent.cfg, cli_cmd_ctx="", command_idle_timeout=0)
    backend.CWD = owner.agent.workspace
    ready = threading.Event()

    def echo(text):
        """Synchronize on actual backend output rather than elapsed time."""
        if text == "ready":
            ready.set()

    owner.agent.message_echo = echo

    def external_model(context):
        """Run the real external-backend process on the operation worker."""
        code, lines = backend.process_bash_cmd(python_command("import time;print('ready',flush=True);time.sleep(30)"))
        return {"returncode": code, "lines": lines}

    operation = owner.submit("external_model", external_model, model=True)
    assert ready.wait(3)
    owner.cancel(operation["id"])
    owner.agent.set_break(False)
    result = owner.wait(operation["id"], 4)
    assert result["state"] == "cancelled"
    assert result["result"]["lines"] == ["ready"]
    assert result["result"]["returncode"] != 0
    assert backend._fail_count == 0


def test_runner_cleanup_on_output_callback_failure(tmp_path):
    """A failing output consumer cannot leave a direct child running."""
    pids = []

    def reject(stream, text):
        """Record the real child PID before simulating a frontend failure."""
        if stream == "stdout" and "\n" in text:
            pids.append(int(text.strip()))
            raise RuntimeError("output consumer failed")

    with pytest.raises(RuntimeError, match="consumer failed"):
        run_shell_process(tmp_path, python_command("import os,time;print(os.getpid(),flush=True);time.sleep(30)"), reject)
    assert len(pids) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(pids[0], os.WNOHANG)


def test_closed_output_pipes_do_not_prevent_timeout(runtime):
    """A child closing both streams can still be silent, alive and cancellable."""
    owner, session, _ = runtime
    session.shell_timeout = 0.15
    command = python_command("import os,time;os.close(1);os.close(2);time.sleep(30)")
    result = owner.wait(owner.execute("shell", {"command": command}, session)["id"], 3)
    assert result["state"] == "failed" and result["error"]["code"] == "idle_timeout"


def test_cancelled_before_launch_does_not_create_a_process(tmp_path, monkeypatch):
    """An already-cancelled context cannot launch a subprocess after cancellation."""
    cancel = threading.Event()
    cancel.set()

    def forbidden(*args, **kwargs):
        """Fail immediately if admission launches a process despite cancellation."""
        raise AssertionError("Unexpected subprocess launch")

    monkeypatch.setattr("ucagent.util.functions.subprocess.Popen", forbidden)
    result = run_shell_process(tmp_path, "echo unexpected", cancel_event=cancel)
    assert result["reason"] == "cancelled" and result["pid"] is None


def test_unavailable_activity_probe_does_not_terminate_potentially_active_work(tmp_path):
    """A failed activity probe preserves the backend's conservative idle contract."""
    probes = []

    def unavailable(activity_marks):
        """Represent a temporarily unavailable MCP activity monitor."""
        probes.append(True)
        raise RuntimeError("Activity monitor unavailable")

    result = run_shell_process(
        tmp_path, python_command("import time;time.sleep(0.3);print('finished')"),
        idle_timeout=0.1, activity_fc=unavailable)
    assert probes
    assert result["reason"] == "completed" and result["returncode"] == 0
    assert result["stdout"] == "finished\n"


def test_file_activity_during_output_poll_refreshes_deadline(tmp_path, monkeypatch):
    """A real file write during polling must be observed before declaring idle timeout."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    release = tmp_path / "release"
    marker = output_dir / "progress.txt"
    agent = Agent(tmp_path)
    agent.output_dir = str(output_dir)
    backend = UCAgentCmdLineBackend(agent, agent.cfg, cli_cmd_ctx="", command_idle_timeout=0.3)
    now = [0.0]
    cancel = threading.Event()
    observed = []
    # Replace only this module's clock; subprocess waits keep their real clock.
    monkeypatch.setattr(runtime_functions, "time", SimpleNamespace(
        monotonic=lambda: now[0], time=time.time))
    backend._workspace_files_changed()

    class FileActivitySelector(selectors.DefaultSelector):
        """Hold the first poll until the child has written, then cross the idle deadline."""

        def select(self, timeout=None):
            """Place actual file progress inside the polling window deterministically."""
            if not release.exists():
                release.touch()
                deadline = time.monotonic() + 3
                while not marker.exists():
                    assert time.monotonic() < deadline, "Child did not write its progress file"
                    threading.Event().wait(0.01)
                now[0] = 1.0
            return super().select(timeout)

    def activity(marks):
        """Use the real cached backend probe and cancel only after observing its marks."""
        active = backend._has_active_tool_call(marks)
        if marks:
            observed.extend(marks)
            # Probe work may take time; the refreshed deadline uses its completion.
            now[0] += 1.0
            cancel.set()
        return active

    monkeypatch.setattr(runtime_functions.selectors, "DefaultSelector", FileActivitySelector)
    command = python_command(
        "import pathlib,time; "
        f"release=pathlib.Path({str(release)!r});\n"
        "while not release.exists(): time.sleep(0.01)\n"
        f"pathlib.Path({str(marker)!r}).write_text('progress');time.sleep(30)")
    result = run_shell_process(tmp_path, command, cancel_event=cancel,
                               idle_timeout=0.3, activity_fc=activity)
    assert observed == ["workspace_files_changed"]
    assert result["reason"] == "cancelled", "Observed progress was misclassified as idle timeout"
    assert result["returncode"] != 0
    assert marker.read_text() == "progress"
    with pytest.raises(ChildProcessError):
        os.waitpid(result["pid"], os.WNOHANG)
