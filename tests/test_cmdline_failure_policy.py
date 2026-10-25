"""Backend retry policy and managed configuration isolation regressions."""

import os
from types import SimpleNamespace

import pytest

from ucagent.abackend import cmdline
from test_cmdline_backend import _FakeAgent


@pytest.mark.parametrize("output", [
    "ERROR unexpected status 404 Not Found", "HTTP 401 Unauthorized",
    "error loading config: invalid TOML", "thread already has an active writer",
])
def test_permanent_failure_stops_without_sleep(tmp_path, monkeypatch, output):
    """Permanent errors stop the loop immediately without echoing raw credentials."""
    agent = _FakeAgent(str(tmp_path))
    backend = cmdline.UCAgentCmdLineBackend(agent, object(), "")
    backend.CWD = str(tmp_path)
    monkeypatch.setattr(cmdline, "process_bash_cmd", lambda *args, **kwargs: (1, [output], False))
    monkeypatch.setattr(cmdline.time, "sleep", lambda delay: pytest.fail("permanent error retried"))
    backend.process_bash_cmd("unused")
    assert agent.is_break()
    assert backend.last_failure["retryable"] is False


def test_transient_failure_backoff_is_bounded_and_success_resets(tmp_path, monkeypatch):
    """Rate limiting backs off, resets on success, and stops at the configured limit."""
    agent = _FakeAgent(str(tmp_path))
    backend = cmdline.UCAgentCmdLineBackend(agent, object(), "", max_continue_fails=3)
    backend.CWD = str(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(cmdline.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cmdline.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    result = [1, ["unexpected status 429 Too Many Requests"], False]
    monkeypatch.setattr(cmdline, "process_bash_cmd", lambda *args, **kwargs: tuple(result))
    backend.process_bash_cmd("unused")
    assert clock[0] == pytest.approx(1)
    assert backend.last_failure["category"] == "transient"
    result[0] = 0
    backend.process_bash_cmd("unused")
    assert backend.last_failure is None
    result[0] = 1
    for attempt in range(3):
        backend.process_bash_cmd("unused")
    assert agent.is_break()
    assert clock[0] == pytest.approx(4)


def test_codex_home_is_task_local_and_checkpoint_is_preserved(tmp_path, monkeypatch):
    """A host CODEX_HOME cannot redirect a task or erase its resume state."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("UCSWARM_MANAGED_CODEX", "1")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:8850/v1")
    monkeypatch.setenv("OPENAI_MODEL", "task-model")
    config = SimpleNamespace(backend=SimpleNamespace(key_name="codex"))
    home = tmp_path / ".codex"
    home.mkdir()
    checkpoint = home / "checkpoint"
    checkpoint.write_text("original")
    backend = cmdline.UCAgentCmdLineBackend(_FakeAgent(str(tmp_path)), config, "")
    backend.init()
    assert os.environ["CODEX_HOME"] == str(home)
    assert checkpoint.read_text() == "original"
    monkeypatch.delenv("OPENAI_MODEL")
    with pytest.raises(ValueError, match="explicit OPENAI"):
        backend.init()


def test_codex_resume_detects_local_session_and_current_mcp_port(tmp_path, monkeypatch):
    """A restored task resumes its own session and rerenders a changed MCP port."""
    monkeypatch.delenv("UCSWARM_MANAGED_CODEX", raising=False)
    monkeypatch.setenv("CODEX_HOME", "/unused-global")
    session = tmp_path / ".codex" / "sessions" / "session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("{}")
    template = tmp_path / "template"
    template.write_text("{{PORT}}")
    agent = _FakeAgent(str(tmp_path))
    agent.pdb._mcp_server = SimpleNamespace(port=10001)
    config = SimpleNamespace(backend=SimpleNamespace(key_name="codex"), mcp_server=SimpleNamespace(port=1))
    backend = cmdline.UCAgentCmdLineBackend(agent, config, "resume", cli_cmd_new="new",
        render_files={str(template): "{CWD}/port.txt"})
    backend.init()
    assert backend._call_count == 1
    agent.pdb._mcp_server.port = 10002
    commands = []
    monkeypatch.setattr(backend, "process_bash_cmd", lambda command: (commands.append(command) or 0, []))
    backend.do_work_values({"messages": [chr(0x4e2d)]}, {})
    assert commands == ["resume"]
    assert (tmp_path / "port.txt").read_text() == "10002"
    assert session.read_text() == "{}"


def test_codex_without_mcp_stops_before_running_command(tmp_path, monkeypatch):
    """Standalone launches also reject missing MCP rather than starting a blind loop."""
    monkeypatch.delenv("UCSWARM_MANAGED_CODEX", raising=False)
    monkeypatch.setenv("CODEX_HOME", "/unused-global")
    agent = _FakeAgent(str(tmp_path))
    backend = cmdline.UCAgentCmdLineBackend(agent, SimpleNamespace(backend=SimpleNamespace(key_name="codex")), "unused")
    backend.init()
    monkeypatch.setattr(backend, "process_bash_cmd", lambda command: pytest.fail("command started without MCP"))
    with pytest.raises(ValueError, match="active MCP server"):
        backend.do_work_values({"messages": ["task"]}, {})
    assert agent.is_break()


def test_first_failed_round_without_checkpoint_retries_new_session(tmp_path, monkeypatch):
    """A failed first attempt cannot resume a nonexistent model session."""
    monkeypatch.delenv("UCSWARM_MANAGED_CODEX", raising=False)
    monkeypatch.setenv("CODEX_HOME", "/unused-global")
    agent = _FakeAgent(str(tmp_path))
    agent.pdb._mcp_server = SimpleNamespace(port=10001)
    config = SimpleNamespace(backend=SimpleNamespace(key_name="codex"))
    backend = cmdline.UCAgentCmdLineBackend(agent, config, "resume", cli_cmd_new="new")
    backend.init()
    commands = []
    monkeypatch.setattr(backend, "process_bash_cmd", lambda command: (commands.append(command) or 1, []))
    for attempt in range(2):
        backend.do_work_values({"messages": ["task"]}, {})
    assert commands == ["new", "new"]
    assert backend._call_count == 0
