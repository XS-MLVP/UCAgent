#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import sys
import threading
import time

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.verify_pdb import VerifyPDB


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


@pytest.fixture
def probe_pdb():
    previous = signal.getsignal(signal.SIGINT)
    pdb = _ProbePDB(_FakeAgent())
    try:
        yield pdb
    finally:
        signal.signal(signal.SIGINT, previous)


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
