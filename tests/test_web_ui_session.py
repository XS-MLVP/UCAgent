#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from ucagent.server.web_ui_session import WebUISession


class _DummyStageManager:
    def __init__(self):
        self.saved = False

    def save_stage_info(self):
        self.saved = True


class _DummyAgent:
    def __init__(self):
        self.pdb = None
        self.stage_manager = _DummyStageManager()
        self.break_values = []
        self.force_trace_values = []
        self.run_loop_called = 0
        self.one_loop_args = []
        self.exit_called = False

    def set_break(self, value=True):
        self.break_values.append(value)

    def set_force_trace(self, value):
        self.force_trace_values.append(value)

    def run_loop(self):
        self.run_loop_called += 1

    def one_loop(self, msg=None):
        self.one_loop_args.append(msg)

    def set_continue_msg(self, msg):
        self.continue_msg = msg

    def exit(self):
        self.exit_called = True


class _DummyDelegate:
    def __init__(self):
        self.prompt = "(UnityChip) "
        self.stdout = object()
        self.stderr = object()
        self.history_file = "/tmp/ucagent-history"
        self.calls = []

    def parseline(self, line):
        if not line:
            return None, "", line
        parts = line.split(" ", 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        return cmd, arg, line

    def completedefault(self, text, line, begidx, endidx):
        return []

    def api_all_cmds(self, prefix=""):
        return ["continue", "tui", "web_ui_start", "status"]

    def onecmd(self, line):
        self.calls.append(line)
        return line


def test_web_ui_session_continue_runs_agent_loop():
    agent = _DummyAgent()
    delegate = _DummyDelegate()
    agent.pdb = delegate
    session = WebUISession(agent, delegate=delegate)

    session.onecmd("continue")

    assert agent.break_values == [False]
    assert agent.force_trace_values == [False]
    assert agent.run_loop_called == 1
    assert delegate.calls == []


def test_web_ui_session_filters_nested_ui_commands():
    agent = _DummyAgent()
    delegate = _DummyDelegate()
    agent.pdb = delegate
    session = WebUISession(agent, delegate=delegate)

    assert session.api_all_cmds() == ["continue", "status"]


def test_web_ui_session_delegates_other_commands():
    agent = _DummyAgent()
    delegate = _DummyDelegate()
    agent.pdb = delegate
    session = WebUISession(agent, delegate=delegate)

    session.onecmd("status")

    assert delegate.calls == ["status"]
