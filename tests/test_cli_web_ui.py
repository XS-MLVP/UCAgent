#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import asyncio
import shlex
import sys
import types

import ucagent.cli as cli


def test_get_args_allows_web_ui(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui"],
    )
    args = cli.get_args()
    assert args.web_ui == ""


def test_get_args_allows_web_ui_with_spec(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "127.0.0.1:18000:secret"],
    )
    args = cli.get_args()
    assert args.web_ui == "127.0.0.1:18000:secret"


def test_build_web_ui_command_removes_web_ui_and_adds_session():
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
    assert "--web-ui-session" in parts
    assert "--config" in parts
    assert "config.yaml" in parts


def test_build_web_ui_command_does_not_duplicate_session():
    cmd = cli._build_web_ui_command(
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "--tui"]
    )
    parts = shlex.split(cmd)
    assert parts.count("--web-ui-session") == 1
    assert parts.count("--tui") == 1


def test_build_web_ui_command_removes_web_ui_value():
    cmd = cli._build_web_ui_command(
        [
            "ucagent",
            "/tmp/workspace",
            "Adder",
            "--web-ui",
            "0.0.0.0:18000:pw",
            "--tui",
        ]
    )
    parts = shlex.split(cmd)
    assert "--web-ui" not in parts
    assert "0.0.0.0:18000:pw" not in parts
    assert "--web-ui-session" in parts


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


def test_run_web_ui_session_uses_server_runner(monkeypatch):
    import ucagent.verify_agent as verify_agent
    import ucagent.server.web_ui_session as web_ui_session

    captured = {}

    class _FakeVerifyAgent:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            captured["set_break_called"] = False
            captured["run_called"] = False
            self.web_ui_session = False

        def set_break(self, value=True):
            captured["set_break_called"] = True

        def run(self):
            captured["run_called"] = True

    def _fake_run_web_ui_session(agent, init_cmd=None):
        captured["runner_agent"] = agent
        captured["runner_init_cmd"] = list(init_cmd or [])

    monkeypatch.setattr(
        sys,
        "argv",
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui-session"],
    )
    monkeypatch.setattr(verify_agent, "VerifyAgent", _FakeVerifyAgent)
    monkeypatch.setattr(web_ui_session, "run_web_ui_session", _fake_run_web_ui_session)

    cli.run()

    assert captured["runner_init_cmd"] == []
    assert captured["runner_agent"].web_ui_session is True
    assert captured["set_break_called"] is False
    assert captured["run_called"] is False


def test_extract_web_ui_spec_from_eq_form():
    spec = cli._extract_web_ui_spec(
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui=localhost:9000:pwd"]
    )
    assert spec == "localhost:9000:pwd"


def test_parse_web_ui_spec_defaults():
    host, port, password = cli._parse_web_ui_spec("")
    assert host == "localhost"
    assert port == 8000
    assert password == ""


def test_parse_web_ui_spec_host_port_password():
    host, port, password = cli._parse_web_ui_spec("0.0.0.0:18000:my:pw")
    assert host == "0.0.0.0"
    assert port == 18000
    assert password == "my:pw"


def test_parse_web_ui_spec_host_port_only():
    host, port, password = cli._parse_web_ui_spec("127.0.0.1:18001")
    assert host == "127.0.0.1"
    assert port == 18001
    assert password == ""


def test_parse_web_ui_spec_rejects_bad_port():
    try:
        cli._parse_web_ui_spec("127.0.0.1:notanumber")
        assert False, "Expected ValueError for non-integer port"
    except ValueError as e:
        assert "Port must be an integer" in str(e)


def test_resolve_web_ui_bind_default_port_busy_auto_increment(monkeypatch):
    import ucagent.util.functions as functions

    monkeypatch.setattr(functions, "is_port_free", lambda host, port: False)
    monkeypatch.setattr(functions, "find_available_port", lambda start_port=5000, end_port=65000: 8001)
    host, port, password = cli._resolve_web_ui_bind("")
    assert host == "localhost"
    assert port == 8001
    assert password == ""


def test_resolve_web_ui_bind_specified_port_busy_raises(monkeypatch):
    import ucagent.util.functions as functions

    monkeypatch.setattr(functions, "is_port_free", lambda host, port: False)
    try:
        cli._resolve_web_ui_bind("127.0.0.1:18001:pw")
        assert False, "Expected ValueError when specified port is occupied"
    except ValueError as e:
        assert "unavailable" in str(e)


def test_is_valid_basic_auth():
    good = "Basic " + base64.b64encode(b"user:secret").decode("ascii")
    bad = "Basic " + base64.b64encode(b"user:oops").decode("ascii")
    assert cli._is_valid_basic_auth(good, "secret") is True
    assert cli._is_valid_basic_auth(bad, "secret") is False
    assert cli._is_valid_basic_auth("", "secret") is False


def test_serve_web_ui_can_run_multiple_times(monkeypatch):
    captured = {"serve_calls": 0, "hosts": [], "ports": []}

    class _FakeServer:
        def __init__(
            self,
            command,
            host="localhost",
            port=8000,
            title=None,
            public_url=None,
            statics_path="./static",
            templates_path="./templates",
        ):
            self.command = command
            self.host = host
            self.port = port
            self._password = ""

        def serve(self):
            captured["serve_calls"] += 1
            captured["hosts"].append(self.host)
            captured["ports"].append(self.port)

        async def _make_app(self):
            class _FakeApp:
                def __init__(self):
                    self.middlewares = []

            return _FakeApp()

    fake_root = types.ModuleType("textual_serve")
    fake_server_mod = types.ModuleType("textual_serve.server")
    fake_server_mod.Server = _FakeServer

    monkeypatch.setitem(sys.modules, "textual_serve", fake_root)
    monkeypatch.setitem(sys.modules, "textual_serve.server", fake_server_mod)
    monkeypatch.setattr(cli, "_build_web_ui_command", lambda argv=None: "fake command")
    monkeypatch.setattr(
        cli,
        "_resolve_web_ui_bind",
        lambda spec: ("localhost", 8000, "") if spec == "" else ("0.0.0.0", 18000, "pw"),
    )

    cli._serve_web_ui(["ucagent", "/tmp/workspace", "Adder", "--web-ui"])
    cli._serve_web_ui(
        ["ucagent", "/tmp/workspace", "Adder", "--web-ui", "0.0.0.0:18000:pw"]
    )

    assert captured["serve_calls"] == 2
    assert captured["hosts"] == ["localhost", "0.0.0.0"]
    assert captured["ports"] == [8000, 18000]


def test_serve_web_ui_recreates_closed_event_loop(monkeypatch):
    captured = {"loop_closed": None}

    class _FakeServer:
        def __init__(self, *args, **kwargs):
            pass

        def serve(self):
            loop = asyncio.get_event_loop()
            captured["loop_closed"] = loop.is_closed()

    fake_root = types.ModuleType("textual_serve")
    fake_server_mod = types.ModuleType("textual_serve.server")
    fake_server_mod.Server = _FakeServer

    monkeypatch.setitem(sys.modules, "textual_serve", fake_root)
    monkeypatch.setitem(sys.modules, "textual_serve.server", fake_server_mod)
    monkeypatch.setattr(cli, "_build_web_ui_command", lambda argv=None: "fake command")
    monkeypatch.setattr(cli, "_resolve_web_ui_bind", lambda spec: ("localhost", 8000, ""))

    closed_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(closed_loop)
    closed_loop.close()

    try:
        cli._serve_web_ui(["ucagent", "/tmp/workspace", "Adder", "--web-ui"])
        assert captured["loop_closed"] is False
    finally:
        current_loop = asyncio.get_event_loop()
        if not current_loop.is_closed():
            current_loop.close()
        asyncio.set_event_loop(None)
