#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for command-line backend process interruption."""

import json
import os
import shlex
import sys
import threading
import time
import tomllib
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


def _render_model_backend_templates(tmp_path, monkeypatch):
    """Render every model-configured MCP backend template into a workspace.

    Returns the workspace holding one rendered file per template, named after
    the backend. OPENAI_CONTEXT_SIZE must be set or deleted by the caller.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = SimpleNamespace(mcp_server=SimpleNamespace(port=5678))
    assets = os.path.abspath(os.path.join(current_dir, "..", "ucagent", "assets"))
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_BASE", "http://example.test/v1")
    render_files = {
        os.path.join(assets, name): f"{{CWD}}/{name}"
        for name in (
            "mcp_codex.toml",
            "mcp_opencode.json",
            "mcp_kilo.json",
            "mcp_qwen.json",
            "mcp_iflow.json",
        )
    }
    backend = UCAgentCmdLineBackend(
        _FakeAgent(workspace=str(workspace)),
        config=config,
        cli_cmd_ctx="",
        render_files=render_files,
    )
    backend.init()
    return workspace


def test_backend_templates_declare_context_size_when_set(tmp_path, monkeypatch):
    """OPENAI_CONTEXT_SIZE reaches each backend's native context-window field."""

    monkeypatch.setenv("OPENAI_CONTEXT_SIZE", "400000")
    workspace = _render_model_backend_templates(tmp_path, monkeypatch)

    codex = tomllib.loads(
        (workspace / "mcp_codex.toml").read_text(encoding="utf-8")
    )
    assert codex["model_auto_compact_token_limit"] == 400000

    opencode = json.loads((workspace / "mcp_opencode.json").read_text(encoding="utf-8"))
    assert (
        opencode["provider"]["ucagent"]["models"]["test-model"]["limit"]
        == {"context": 400000}
    )

    kilo = json.loads((workspace / "mcp_kilo.json").read_text(encoding="utf-8"))
    assert kilo["provider"]["ucagent"]["models"]["test-model"]["limit"] == {
        "context": 400000
    }

    qwen = json.loads((workspace / "mcp_qwen.json").read_text(encoding="utf-8"))
    assert qwen["modelProviders"]["openai"][0]["generationConfig"] == {
        "contextWindowSize": 400000
    }

    iflow = json.loads((workspace / "mcp_iflow.json").read_text(encoding="utf-8"))
    assert iflow["tokensLimit"] == 400000


def test_backend_templates_declare_output_size_with_context_size(tmp_path, monkeypatch):
    """OPENAI_OUTPUT_SIZE becomes limit.output only beside a declared context."""

    monkeypatch.setenv("OPENAI_CONTEXT_SIZE", "400000")
    monkeypatch.setenv("OPENAI_OUTPUT_SIZE", "32000")
    workspace = _render_model_backend_templates(tmp_path, monkeypatch)

    expected = {"context": 400000, "output": 32000}
    opencode = json.loads((workspace / "mcp_opencode.json").read_text(encoding="utf-8"))
    assert (
        opencode["provider"]["ucagent"]["models"]["test-model"]["limit"] == expected
    )

    kilo = json.loads((workspace / "mcp_kilo.json").read_text(encoding="utf-8"))
    assert kilo["provider"]["ucagent"]["models"]["test-model"]["limit"] == expected


def test_backend_templates_omit_context_size_when_unset(tmp_path, monkeypatch):
    """Without OPENAI_CONTEXT_SIZE the rendered backend configs stay unchanged."""

    monkeypatch.delenv("OPENAI_CONTEXT_SIZE", raising=False)
    workspace = _render_model_backend_templates(tmp_path, monkeypatch)

    assert "model_auto_compact_token_limit" not in (
        workspace / "mcp_codex.toml"
    ).read_text(encoding="utf-8")

    opencode = json.loads((workspace / "mcp_opencode.json").read_text(encoding="utf-8"))
    assert "limit" not in opencode["provider"]["ucagent"]["models"]["test-model"]

    kilo = json.loads((workspace / "mcp_kilo.json").read_text(encoding="utf-8"))
    assert "limit" not in kilo["provider"]["ucagent"]["models"]["test-model"]

    qwen = json.loads((workspace / "mcp_qwen.json").read_text(encoding="utf-8"))
    assert "generationConfig" not in qwen["modelProviders"]["openai"][0]

    iflow = json.loads((workspace / "mcp_iflow.json").read_text(encoding="utf-8"))
    assert "tokensLimit" not in iflow
    assert "mcpServers" in iflow


def test_idle_timeout_suppressed_by_workspace_file_changes(tmp_path):
    """A silent process that keeps writing files is forward progress."""

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    agent = _FakeAgent(workspace=str(tmp_path))
    agent.output_dir = str(output_dir)
    backend = UCAgentCmdLineBackend(
        agent, config=object(), cli_cmd_ctx="", command_idle_timeout=0.3
    )
    backend.CWD = current_dir

    marker = output_dir / "progress.txt"
    cmd = (
        f"{shlex.quote(sys.executable)} -c "
        "'import time\n"
        "for i in range(8):\n"
        "    time.sleep(0.2)\n"
        f"    open(r\"{marker}\", \"a\").write(f\"{{i}}\\n\")\n"
        "time.sleep(30)'"
    )
    start = time.monotonic()
    return_code, _lines = backend.process_bash_cmd(cmd)
    elapsed = time.monotonic() - start

    assert return_code != 0
    assert elapsed >= 1.2, "file changes must suppress the idle timeout"
    assert elapsed < 15, "final 30s sleep must still trip the idle timeout"
    assert marker.read_text(encoding="utf-8").count("\n") == 8


def test_idle_timeout_fires_without_file_changes(tmp_path):
    """No output and no file activity still times out at the configured limit."""

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "static.txt").write_text("unchanged\n", encoding="utf-8")
    agent = _FakeAgent(workspace=str(tmp_path))
    agent.output_dir = str(output_dir)
    backend = UCAgentCmdLineBackend(
        agent, config=object(), cli_cmd_ctx="", command_idle_timeout=0.3
    )
    backend.CWD = current_dir

    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"
    start = time.monotonic()
    return_code, _lines = backend.process_bash_cmd(cmd)
    elapsed = time.monotonic() - start

    assert return_code != 0
    assert elapsed < 2.0
    assert backend._fail_count == 1
