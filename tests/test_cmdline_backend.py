#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for command-line backend process interruption."""

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
