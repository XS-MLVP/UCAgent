#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import readline
import signal
import shlex
import sys
import threading
import time
from types import SimpleNamespace

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.verify_pdb import VerifyPDB
from ucagent.verify_agent import VerifyAgent
from ucagent.util.log import info


def _console_output_lines(rendered: str) -> list[str]:
    return [
        line
        for line in rendered.splitlines()
        if not line.startswith("> ")
        and not line.startswith("Executing shell command:")
        and not line.startswith("Working directory:")
        and not line.startswith("Idle timeout without output:")
        and "Command '" not in line
    ]


class _FakeAgent:
    def __init__(self, workspace: str | None = None) -> None:
        self._need_break = False
        self.break_threads: set[int] = set()
        if workspace is not None:
            self.workspace = workspace

    def set_break(self, value=True):
        self._need_break = value

    def is_break(self):
        return (
            self._need_break
            or threading.current_thread().ident in self.break_threads
        )

    def set_force_trace(self, _value):
        pass

    def message_echo(self, *_args, **_kwargs):
        pass

    def set_break_thread(self, thread_id: int) -> None:
        self.break_threads.add(thread_id)

    def clear_break_thread(self, thread_id: int) -> None:
        self.break_threads.discard(thread_id)


class _ProbePDB(VerifyPDB):
    def __init__(self, agent):
        super().__init__(agent)
        self.running_snapshots: list[list[str]] = []

    def do_probe(self, _arg):
        self.running_snapshots.append(self.get_running_commands())
        return False

    def do_tui(self, _arg):
        self.running_snapshots.append(self.get_running_commands())
        return False

    def do_probeout(self, _arg):
        print("probe output")
        return False


@pytest.fixture
def probe_pdb():
    previous = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent())
    try:
        yield pdb
    finally:
        signal.signal(signal.SIGINT, previous)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_execute_command_tracks_foreground_command(probe_pdb):
    probe_pdb.execute_command("probe demo")

    assert probe_pdb.running_snapshots == [["probe demo"]]
    assert probe_pdb.get_running_commands() == []


def test_execute_command_does_not_track_tui_itself(probe_pdb):
    probe_pdb.execute_command("tui")

    assert probe_pdb.running_snapshots == [[]]
    assert probe_pdb.get_running_commands() == []


def test_cancel_running_sleep_returns_quickly(probe_pdb):
    errors: list[BaseException] = []

    def run_sleep():
        try:
            probe_pdb.execute_command("sleep 5")
        except KeyboardInterrupt:
            pass
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_sleep)
    started = time.monotonic()
    worker.start()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if probe_pdb.get_running_commands() == ["sleep 5"]:
            break
        time.sleep(0.01)

    assert probe_pdb.get_running_commands() == ["sleep 5"]
    assert probe_pdb.cancel_last_running_command() is True

    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    assert probe_pdb.get_running_commands() == []
    assert time.monotonic() - started < 1.5


def test_execute_command_records_shared_console_transcript(probe_pdb):
    probe_pdb.execute_command("probeout demo")

    assert probe_pdb.get_console_entry_count() == 2
    assert probe_pdb.render_console_entries_since(0) == "> probeout demo\nprobe output\n"


def test_info_output_outside_command_is_recorded(probe_pdb):
    info("shared info output")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "INFO" in rendered
    assert "shared info output" in rendered


def test_chcwd_controls_pdb_and_shell_command_cwd(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    subdir = workspace / "subdir"
    nested = subdir / "nested"
    subdir.mkdir(parents=True)
    nested.mkdir()
    (subdir / "marker.txt").write_text("demo", encoding="utf-8")
    (nested / "deep.txt").write_text("nested", encoding="utf-8")

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    process_cwd = os.getcwd()
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        pdb.execute_command("chcwd subdir")
        assert pdb._command_cwd == str(subdir)
        assert os.getcwd() == process_cwd

        pdb.execute_command("pwd")
        output = capsys.readouterr().out
        assert f"Current working directory: {subdir}" in output

        pdb.execute_command("ls")
        output = capsys.readouterr().out
        assert "marker.txt" in output

        pdb.execute_command("shell pwd")
        output = capsys.readouterr().out
        assert f"Working directory: {subdir}" in output
        assert str(subdir) in output
        assert os.getcwd() == process_cwd

        pdb.execute_command("chcwd .")
        assert pdb._command_cwd == str(workspace)

        completions = pdb.complete_cd("subdir/", "cd subdir/", 3, len("cd subdir/"))
        assert "subdir/nested/" in completions
        assert "subdir/marker.txt" not in completions

        pdb.execute_command("cd subdir")
        assert pdb._command_cwd == str(subdir)

        pdb.execute_command("cd .")
        assert pdb._command_cwd == str(subdir)

        pdb.execute_command("cd")
        assert pdb._command_cwd == str(workspace)

        pdb.execute_command("shell pwd")
        output = capsys.readouterr().out
        assert f"Working directory: {workspace}" in output
        assert str(workspace) in output
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_cmd_timeout_command_shows_and_sets_idle_timeout(probe_pdb, capsys):
    probe_pdb.execute_command("cmd_timeout")
    output = capsys.readouterr().out
    assert "Shell command idle timeout: 30 seconds" in output

    probe_pdb.execute_command("cmd_timeout 1.5")
    output = capsys.readouterr().out
    assert "Shell command idle timeout set to 1.5 seconds." in output
    assert probe_pdb._cmd_idle_timeout == 1.5

    probe_pdb.execute_command("cmd_timeout off")
    output = capsys.readouterr().out
    assert "Shell command idle timeout set to disabled." in output
    assert probe_pdb._cmd_idle_timeout == 0


def test_readline_completion_binding_uses_libedit_syntax(probe_pdb, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(readline, "__doc__", "Importing this module enables command line editing using libedit readline.")
    monkeypatch.setattr(readline, "parse_and_bind", calls.append)

    probe_pdb._bind_readline_completion()

    assert calls == ["bind ^I rl_complete"]
    assert probe_pdb._readline_completion_bind_command() == "bind ^I rl_complete"


def test_readline_completion_binding_uses_gnu_syntax(probe_pdb, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(readline, "__doc__", "GNU readline")
    monkeypatch.setattr(readline, "parse_and_bind", calls.append)

    probe_pdb._bind_readline_completion()

    assert calls == ["tab: complete"]
    assert probe_pdb._readline_completion_bind_command() == "tab: complete"


def test_shell_command_runs_while_agent_break_is_set(probe_pdb):
    probe_pdb.agent.set_break(True)

    probe_pdb.execute_command("sh -c 'echo break-ok'")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "break-ok" in _console_output_lines(rendered)
    assert "interrupted" not in rendered


def test_unknown_non_dangerous_command_executes_as_shell(probe_pdb):
    probe_pdb.execute_command("command -v sh")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "/sh" in rendered or rendered.splitlines().count("sh") > 0
    assert "Executing as bash command: command -v sh" in rendered


def test_shell_command_completion_whitelist_and_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "demo.txt").write_text("demo", encoding="utf-8")

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        assert "pytest" in pdb.api_all_cmds("py")
        assert "pytest" in pdb.completenames("py")
        assert "rm" not in pdb.api_all_cmds("r")

        completions = pdb.completedefault("de", "pytest de", len("pytest "), len("pytest de"))
        assert "demo.txt" in completions

        shell_completions = pdb.complete_shell("de", "shell pytest de", len("shell pytest "), len("shell pytest de"))
        assert "demo.txt" in shell_completions
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_shell_command_streams_output_before_completion(probe_pdb):
    code = (
        "import time; "
        "print('stream-first', flush=True); "
        "time.sleep(1.5); "
        "print('stream-second', flush=True)"
    )
    command = f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    errors: list[BaseException] = []

    def run_command():
        try:
            probe_pdb.execute_command(command)
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_command)
    worker.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            rendered = probe_pdb.render_console_entries_since(0)
            if "stream-first" in rendered:
                break
            time.sleep(0.02)

        rendered = probe_pdb.render_console_entries_since(0)
        assert "stream-first" in rendered
        assert worker.is_alive()
        assert "stream-second" not in _console_output_lines(rendered)
    finally:
        worker.join(timeout=3.0)
        if worker.is_alive():
            probe_pdb.cancel_last_running_command()
            worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    rendered = probe_pdb.render_console_entries_since(0)
    assert "stream-second" in _console_output_lines(rendered)
    assert "Command completed successfully" in rendered


def test_shell_command_pty_streams_line_buffered_output(probe_pdb):
    code = (
        "import time; "
        "print('line-buffered-first'); "
        "time.sleep(1.5); "
        "print('line-buffered-second')"
    )
    command = f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    errors: list[BaseException] = []

    def run_command():
        try:
            probe_pdb.execute_command(command)
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_command)
    worker.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
            if "line-buffered-first" in output_lines:
                break
            time.sleep(0.02)

        output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
        assert "line-buffered-first" in output_lines
        assert worker.is_alive()
        assert "line-buffered-second" not in output_lines
    finally:
        worker.join(timeout=3.0)
        if worker.is_alive():
            probe_pdb.cancel_last_running_command()
            worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
    assert "line-buffered-second" in output_lines


def test_shell_idle_timeout_resets_after_output(probe_pdb):
    probe_pdb._cmd_idle_timeout = 1.0
    code = (
        "import time\n"
        "for idx in range(4):\n"
        "    print(f'tick-{idx}', flush=True)\n"
        "    time.sleep(0.35)\n"
        "print('still-alive', flush=True)\n"
    )

    probe_pdb.execute_command(
        f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    )

    rendered = probe_pdb.render_console_entries_since(0)
    output_lines = _console_output_lines(rendered)
    assert "tick-0" in output_lines
    assert "tick-3" in output_lines
    assert "still-alive" in output_lines
    assert "timed out" not in rendered


def test_shell_idle_timeout_kills_quiet_command(probe_pdb):
    probe_pdb._cmd_idle_timeout = 0.4
    code = (
        "import time; "
        "print('quiet-start', flush=True); "
        "time.sleep(5); "
        "print('quiet-late', flush=True)"
    )

    started = time.monotonic()
    probe_pdb.execute_command(
        f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    )

    rendered = probe_pdb.render_console_entries_since(0)
    output_lines = _console_output_lines(rendered)
    assert time.monotonic() - started < 2.0
    assert "quiet-start" in output_lines
    assert "quiet-late" not in output_lines
    assert "timed out after 0.4 seconds without output" in rendered


def test_chcwd_rejects_paths_outside_workspace(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        pdb.execute_command(f"chcwd {outside}")
        output = capsys.readouterr().out

        assert "outside the workspace" in output
        assert pdb._command_cwd == str(workspace)
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_add_cmds_falls_back_when_tui_app_stopped(probe_pdb):
    class _DeadKeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("stopped app should not process commands")

    class _DeadApp:
        key_handler = _DeadKeyHandler()

        def call_from_thread(self, *_args, **_kwargs):
            raise RuntimeError("App is not running")

    probe_pdb._in_tui = True
    probe_pdb._tui_app = _DeadApp()

    probe_pdb.add_cmds(["sleep 5", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit"]


def test_add_cmds_with_exit_in_tui_defers_to_pdb_queue(probe_pdb):
    class _KeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("exit batches should not be executed inside the TUI")

    class _App:
        def __init__(self):
            self.key_handler = _KeyHandler()
            self.quit_requested = 0

        def call_from_thread(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        def action_quit(self):
            self.quit_requested += 1

    app = _App()
    probe_pdb._in_tui = True
    probe_pdb._tui_app = app

    probe_pdb.add_cmds(["sleep 5", "quit", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit", "quit"]
    assert app.quit_requested == 1


def test_add_cmds_with_exit_handles_stopped_tui_app(probe_pdb):
    class _KeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("stopped app should not process commands")

    class _DeadApp:
        def __init__(self):
            self.key_handler = _KeyHandler()

        def call_from_thread(self, *_args, **_kwargs):
            raise RuntimeError("App is not running")

        def action_quit(self):
            raise AssertionError("stopped app should not quit synchronously")

    probe_pdb._in_tui = True
    probe_pdb._tui_app = _DeadApp()

    probe_pdb.add_cmds(["sleep 5", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit"]


def test_exit_on_completion_defers_until_work_finishes():
    class _PdbRecorder:
        def __init__(self):
            self.cmds = []

        def add_cmds(self, cmds):
            self.cmds.append(cmds)

    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion = True
    agent._exit_on_completion_pending = False
    agent._exit_on_completion_queued = False
    agent._is_work_busy = False
    agent._need_break = True
    agent.stream_output = False
    agent.pdb = _PdbRecorder()

    def do_work_values(_instructions, _config):
        assert agent.is_work_busy()
        agent.try_exit_on_completion()
        assert agent.pdb.cmds == []

    agent.do_work_values = do_work_values

    agent.do_work({}, {})

    assert agent._need_break is False
    assert agent.pdb.cmds == [["sleep 5", "quit", "quit", "quit"]]


def test_do_work_recovers_pending_tool_calls_before_reraising():
    class _Backend:
        def __init__(self):
            self.errors = []

        def recover_pending_tool_calls(self, error):
            self.errors.append(error)
            return 1

    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion_pending = False
    agent._is_work_busy = False
    agent.stream_output = False
    agent.backend = _Backend()

    def fail_work(_instructions, _config):
        raise RuntimeError("tool execution failed")

    agent.do_work_values = fail_work

    with pytest.raises(RuntimeError, match="tool execution failed"):
        agent.do_work({}, {})

    assert len(agent.backend.errors) == 1
    assert agent.is_work_busy() is False


def test_loop_retry_budget_is_not_refreshed_without_agent_progress(probe_pdb):
    calls = 0
    probe_pdb.max_loop_retry = 2
    probe_pdb.retry_delay_start = 0
    probe_pdb.retry_delay_end = 0
    probe_pdb.loop_alive_time = -1
    probe_pdb.agent.invoke_round = 0

    def fail_without_progress(_message):
        nonlocal calls
        calls += 1
        if calls >= 3:
            probe_pdb.agent.set_break(True)
        raise RuntimeError("deterministic failure")

    probe_pdb.agent.run_loop = fail_without_progress

    probe_pdb.do_loop("")

    assert calls == 2


def test_loop_retry_budget_can_refresh_after_agent_progress(probe_pdb):
    calls = 0
    probe_pdb.max_loop_retry = 2
    probe_pdb.retry_delay_start = 0
    probe_pdb.retry_delay_end = 0
    probe_pdb.loop_alive_time = -1
    probe_pdb.agent.invoke_round = 0

    def fail_after_progress(_message):
        nonlocal calls
        calls += 1
        probe_pdb.agent.invoke_round += 1
        if calls >= 3:
            probe_pdb.agent.set_break(True)
        raise RuntimeError("failure after progress")

    probe_pdb.agent.run_loop = fail_after_progress

    probe_pdb.do_loop("")

    assert calls == 3


def _failure_result(error="same actionable failure"):
    return {
        "check_pass": False,
        "failure_summary": {
            "stage_index": 19,
            "stage_name": "generate_random_test_cases",
            "failed_checker_name": "random_test_check",
            "failed_checker_class": "RandomTestCasesChecker",
            "error_code": "TEST_REPORT_MISMATCH",
            "error": error,
            "next_action": "Repair the reported artifact and call Check again.",
        },
    }


def _stall_probe(max_stalled_rounds=3):
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._max_stalled_rounds = max_stalled_rounds
    agent._stalled_rounds = 0
    agent._last_stall_signature = None
    agent._need_human = False
    agent.stage_manager = SimpleNamespace(
        validation_revision=0,
        stage_index=19,
        last_check_info={},
    )
    return agent


def _record_validation_round(agent, result, stage_index=19):
    previous_revision = agent.stage_manager.validation_revision
    previous_stage_index = agent.stage_manager.stage_index
    agent.stage_manager.validation_revision += 1
    agent.stage_manager.stage_index = stage_index
    agent.stage_manager.last_check_info = result
    agent._update_stalled_rounds(previous_revision, previous_stage_index)


def test_unchanged_checker_diagnostic_pauses_agent_loop():
    agent = _stall_probe(max_stalled_rounds=3)

    for _ in range(3):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 3
    assert agent._need_human is True


def test_changed_checker_diagnostic_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)

    _record_validation_round(agent, _failure_result())
    _record_validation_round(agent, _failure_result("different actionable failure"))

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_dynamic_summary_metadata_does_not_hide_unchanged_failure():
    agent = _stall_probe(max_stalled_rounds=2)
    first = _failure_result()
    second = _failure_result()
    first["failure_summary"]["details"] = {"attempt": 1}
    second["failure_summary"]["details"] = {"attempt": 2}

    _record_validation_round(agent, first)
    _record_validation_round(agent, second)

    assert agent._stalled_rounds == 2
    assert agent._need_human is True


def test_validation_progress_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)
    _record_validation_round(agent, _failure_result())

    _record_validation_round(
        agent,
        {"check_pass": False, "progress_summary": {"status": "batch_advanced"}},
    )

    assert agent._stalled_rounds == 0
    assert agent._last_stall_signature is None


def test_round_without_new_validation_does_not_count_as_stalled():
    agent = _stall_probe(max_stalled_rounds=2)
    _record_validation_round(agent, _failure_result())

    revision = agent.stage_manager.validation_revision
    agent._update_stalled_rounds(revision, agent.stage_manager.stage_index)

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_disabled_stall_protection_does_not_pause_agent():
    agent = _stall_probe(max_stalled_rounds=0)

    for _ in range(4):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 0
    assert agent._need_human is False


@pytest.mark.parametrize("value", [True, -1, 1.5, "3", None])
def test_max_stalled_rounds_rejects_ambiguous_values(value):
    with pytest.raises(ValueError, match="max_stalled_rounds"):
        VerifyAgent._validated_max_stalled_rounds(value)


@pytest.mark.parametrize("value", [0, 1, 3])
def test_max_stalled_rounds_accepts_non_negative_integers(value):
    assert VerifyAgent._validated_max_stalled_rounds(value) == value
