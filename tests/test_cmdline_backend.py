#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for command-line backend process interruption."""

import json
import os
import shlex
import sys
import threading
import time
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.abackend.cmdline import UCAgentCmdLineBackend


class _FakeAgent:
    def __init__(self, workspace=None) -> None:
        self._break = False
        self.messages = []
        self.workspace = workspace or current_dir
        self.pdb = SimpleNamespace(_mcp_server=None)

    def message_echo(self, txt: str) -> None:
        self.messages.append(txt)

    def is_break(self) -> bool:
        return self._break

    def set_break(self, value=True) -> None:
        self._break = value


def test_process_bash_cmd_interrupts_silent_process():
    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(agent, config=object(), cli_cmd_ctx="")
    backend.CWD = current_dir

    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"

    def trigger_break() -> None:
        time.sleep(0.2)
        agent.set_break(True)

    breaker = threading.Thread(target=trigger_break)
    breaker.start()

    start = time.time()
    return_code, output_lines = backend.process_bash_cmd(cmd)
    elapsed = time.time() - start

    breaker.join(timeout=1)

    assert elapsed < 5
    assert return_code is not None
    assert return_code != 0
    assert output_lines == []
    assert backend._fail_count == 0


def test_process_bash_cmd_interrupts_partial_line_output():
    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(agent, config=object(), cli_cmd_ctx="")
    backend.CWD = current_dir

    cmd = (
        f"{shlex.quote(sys.executable)} -c "
        "'import sys,time; sys.stdout.write(\"partial\"); "
        "sys.stdout.flush(); time.sleep(30)'"
    )

    def trigger_break() -> None:
        time.sleep(0.2)
        agent.set_break(True)

    breaker = threading.Thread(target=trigger_break)
    breaker.start()

    start = time.time()
    return_code, output_lines = backend.process_bash_cmd(cmd)
    elapsed = time.time() - start

    breaker.join(timeout=1)

    assert elapsed < 5
    assert return_code is not None
    assert return_code != 0
    assert output_lines == ["partial"]
    assert backend._fail_count == 0


def test_process_bash_cmd_idle_timeout_is_a_retryable_failure():
    """A silent backend process becomes a failure without requesting human input."""
    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(
        agent, config=object(), cli_cmd_ctx="", command_idle_timeout=0.2
    )
    backend.CWD = current_dir

    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"
    start = time.time()
    return_code, output_lines = backend.process_bash_cmd(cmd)
    elapsed = time.time() - start

    assert elapsed < 5
    assert return_code is not None
    assert return_code != 0
    assert output_lines == []
    assert agent.is_break() is False
    assert backend._fail_count == 1


def test_process_bash_cmd_idle_timeout_waits_for_active_tool():
    """An active MCP tool suppresses the command idle timer until it finishes."""
    agent = _FakeAgent()
    busy_until = time.monotonic() + 0.35

    class _BusyTool:
        """Minimal tool activity probe for the backend timeout contract."""

        def is_busy(self):
            return time.monotonic() < busy_until

    agent.test_tools = [_BusyTool()]
    backend = UCAgentCmdLineBackend(
        agent, config=object(), cli_cmd_ctx="", command_idle_timeout=0.2
    )
    backend.CWD = current_dir

    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"
    start = time.monotonic()
    return_code, _output_lines = backend.process_bash_cmd(cmd)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.45
    assert elapsed < 5
    assert return_code != 0
    assert agent.is_break() is False
    assert backend._fail_count == 1


def test_repeated_idle_timeouts_pause_after_failure_limit():
    """Repeated command timeouts use the existing automatic failure pause."""
    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(
        agent,
        config=object(),
        cli_cmd_ctx="",
        command_idle_timeout=0.1,
        max_continue_fails=2,
    )
    backend.CWD = current_dir
    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"

    backend.process_bash_cmd(cmd)
    assert agent.is_break() is False
    backend.process_bash_cmd(cmd)

    assert agent.is_break() is True
    assert backend._fail_count == 2


def test_process_bash_cmd_uses_configured_cmd_timeout():
    """The global command timeout is inherited when backend-specific config is absent."""
    class _Config:
        @staticmethod
        def get_value(key, default=None):
            assert key == "cmd_timeout"
            return 0.2

    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(agent, config=_Config(), cli_cmd_ctx="")
    assert backend.command_idle_timeout == 0.2


def test_render_config_files_uses_context_and_creates_parent_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "mcp.json"
    template_file.write_text(
        '{"url": "http://127.0.0.1:{{PORT}}/mcp", "model": "{{OPENAI_MODEL}}"}',
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    agent = _FakeAgent(workspace=str(workspace))
    config = SimpleNamespace(mcp_server=SimpleNamespace(port=5678))
    backend = UCAgentCmdLineBackend(
        agent,
        config=config,
        cli_cmd_ctx="",
        render_files={str(template_file): "{CWD}/nested/config.json"},
    )

    backend.init()

    rendered_file = workspace / "nested" / "config.json"
    assert rendered_file.read_text(encoding="utf-8") == (
        '{"url": "http://127.0.0.1:5678/mcp", "model": "test-model"}'
    )


def test_opencode_template_denies_shell_and_external_workspace_access(
    tmp_path, monkeypatch
):
    """Rendered OpenCode sessions must use MCP gates inside the DUT workspace."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_file = os.path.abspath(
        os.path.join(current_dir, "..", "ucagent", "assets", "mcp_opencode.json")
    )
    config = SimpleNamespace(mcp_server=SimpleNamespace(port=5678))
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_BASE", "http://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-rendered")

    backend = UCAgentCmdLineBackend(
        _FakeAgent(workspace=str(workspace)),
        config=config,
        cli_cmd_ctx="",
        render_files={template_file: "{CWD}/opencode.json"},
    )
    backend.init()

    rendered = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    assert rendered["permission"] == {
        "bash": "deny",
        "external_directory": "deny",
    }
    assert rendered["provider"]["ucagent"]["options"]["apiKey"] == (
        "{env:OPENAI_API_KEY}"
    )


def test_codex_template_includes_env_key_only_when_openai_api_key_exists(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template_file = os.path.abspath(
        os.path.join(current_dir, "..", "ucagent", "assets", "mcp_codex.toml")
    )
    config = SimpleNamespace(mcp_server=SimpleNamespace(port=5678))

    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_BASE", "http://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    agent = _FakeAgent(workspace=str(workspace))
    backend = UCAgentCmdLineBackend(
        agent,
        config=config,
        cli_cmd_ctx="",
        render_files={template_file: "{CWD}/with-key.toml"},
    )
    backend.init()

    with_key = (workspace / "with-key.toml").read_text(encoding="utf-8")
    assert 'env_key = "OPENAI_API_KEY"' in with_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = UCAgentCmdLineBackend(
        agent,
        config=config,
        cli_cmd_ctx="",
        render_files={template_file: "{CWD}/without-key.toml"},
    )
    backend.init()

    without_key = (workspace / "without-key.toml").read_text(encoding="utf-8")
    assert 'env_key = "OPENAI_API_KEY"' not in without_key
