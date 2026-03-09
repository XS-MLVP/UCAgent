#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shlex
import sys
import types

import ucagent.cli as cli


def test_get_args_allows_web_ui_with_legacy_ui(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "--legacy-ui"],
    )
    args = cli.get_args()
    assert args.web_ui is True
    assert args.legacy_ui is True


def test_build_web_ui_command_removes_web_ui_and_adds_tui():
    cmd = cli._build_web_ui_command(
        [
            "ucagent",
            "/tmp/workspace",
            "Adder",
            "--web-ui",
            "--config",
            "config.yaml",
        ]
    )
    parts = shlex.split(cmd)
    assert parts[:6] == [
        "env",
        "PYTHONWARNINGS=ignore",
        sys.executable,
        "-m",
        "ucagent.cli",
        "/tmp/workspace",
    ]
    assert "--web-ui" not in parts
    assert "--tui" in parts
    assert "--web-ui-session" in parts
    assert "--config" in parts
    assert "config.yaml" in parts


def test_build_web_ui_command_does_not_duplicate_tui():
    cmd = cli._build_web_ui_command(
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "--tui"]
    )
    parts = shlex.split(cmd)
    assert parts.count("--tui") == 1


def test_build_web_ui_command_ignores_legacy_ui():
    cmd = cli._build_web_ui_command(
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "--legacy-ui", "--tui"]
    )
    parts = shlex.split(cmd)
    assert "--legacy-ui" not in parts
    assert parts.count("--tui") == 1


def test_suppress_web_ui_session_logs_noop():
    import ucagent.util.log as log
    log.set_silent(False)
    cli._suppress_web_ui_session_logs()
    assert log.is_silent() is True
    log.set_silent(False)


def test_silent_still_outputs_error(capsys):
    import ucagent.util.log as log

    log.set_silent(True)
    try:
        log.error("web-ui-session error")
        out = capsys.readouterr().out
        assert "web-ui-session error" in out
    finally:
        log.set_silent(False)


def test_run_web_ui_bootstrap_injects_web_ui_start(monkeypatch):
    import ucagent.verify_agent as verify_agent

    captured = {}

    class _FakeVerifyAgent:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            captured["set_break"] = None
            captured["run_called"] = False

        def set_break(self, value=True):
            captured["set_break"] = value

        def run(self):
            captured["run_called"] = True

    monkeypatch.setattr(
        sys,
        "argv",
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui"],
    )
    monkeypatch.setattr(verify_agent, "VerifyAgent", _FakeVerifyAgent)
    def _unexpected_serve(argv=None):
        raise AssertionError("unexpected call")

    monkeypatch.setattr(cli, "_serve_web_ui", _unexpected_serve)

    cli.run()

    assert captured["kwargs"]["init_cmd"] == ["web_ui_start"]
    assert captured["set_break"] is True
    assert captured["run_called"] is True


def test_run_web_ui_bootstrap_skips_parent_init_cmds(monkeypatch):
    import ucagent.verify_agent as verify_agent
    import ucagent.util.functions as functions

    captured = {}

    class _FakeVerifyAgent:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def set_break(self, value=True):
            captured["set_break"] = value

        def run(self):
            captured["run_called"] = True

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ucagent",
            "/tmp/workspace",
            "Adder",
            "--web-ui",
            "--mcp-server",
            "--mcp-server-port",
            "-1",
            "--master",
            "127.0.0.1:9999",
            "--loop",
            "--loop-msg",
            "hello",
            "--icmd",
            "status",
        ],
    )
    def _unexpected_find_port():
        raise AssertionError(
            "find_available_port should not be called in web-ui bootstrap"
        )

    monkeypatch.setattr(functions, "find_available_port", _unexpected_find_port)
    monkeypatch.setattr(verify_agent, "VerifyAgent", _FakeVerifyAgent)

    cli.run()

    assert captured["kwargs"]["init_cmd"] == ["web_ui_start"]
    assert captured["set_break"] is True
    assert captured["run_called"] is True


def test_serve_web_ui_uses_fresh_event_loop_each_time(monkeypatch):
    serve_called = []

    class _FakeServer:
        def __init__(self, command):
            self.command = command

        def serve(self):
            serve_called.append(True)

    fake_root = types.ModuleType("textual_serve")
    fake_server_mod = types.ModuleType("textual_serve.server")
    fake_server_mod.Server = _FakeServer

    monkeypatch.setitem(sys.modules, "textual_serve", fake_root)
    monkeypatch.setitem(sys.modules, "textual_serve.server", fake_server_mod)
    monkeypatch.setattr(cli, "_build_web_ui_command", lambda argv=None: "fake command")

    cli._serve_web_ui()
    cli._serve_web_ui()

    assert len(serve_called) == 2
