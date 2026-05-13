#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import sys
import threading
import time

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.verify_pdb import VerifyPDB
from ucagent.verify_agent import VerifyAgent
from ucagent.util.log import info


class _FakeAgent:
    def __init__(self) -> None:
        self._need_break = False
        self.break_threads: set[int] = set()

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
