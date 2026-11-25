"""Regression boundaries for cleanup ownership, history recovery and safe operator data."""

import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_runtime_host import make_host
from test_control_api_runtime import api
from test_global_agent import runtime as global_runtime, start, prepare
from ucagent.core.stage.work import StageWork
from ucagent.runtime.session import RuntimeSession
from ucagent.runtime.control.commands import CommandSession
from ucagent.util.redaction import REDACTED


@pytest.fixture
def host(tmp_path):
    """Own cleanup even when testing construction before the supervisor starts."""
    instance, _ = make_host(tmp_path)
    yield instance
    instance.request_shutdown()
    assert instance.wait(3)["instance"] in {"closed", "failed"}


@pytest.mark.parametrize("contents", [b'{broken-secret', b'{}', b'[1]', b'null', b'\xff'])
def test_corrupt_history_is_preserved_and_session_recovers(host, contents, caplog):
    """Invalid JSON, UTF-8 and list shapes cannot prevent interactive startup."""
    path = Path(host.agent.workspace) / ".ucagent/command_history.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(contents)
    session = RuntimeSession(host, result_formatter=Mock(), operation_formatter=Mock())
    assert session.get_cmd_history() == []
    assert [item.read_bytes() for item in path.parent.glob("command_history.corrupt-*.json")] == [contents]
    assert "broken-secret" not in caplog.text
    session.record_cmd_history("status café")
    session.record_cmd_history("status café")
    session.save_cmd_history()
    assert json.loads(path.read_text(encoding="utf-8")) == ["status café"]
    restored = RuntimeSession(host, result_formatter=Mock(), operation_formatter=Mock())
    assert restored.get_cmd_history() == ["status café"]


def test_history_replace_failure_retains_last_valid_data(host, monkeypatch):
    """A failed atomic commit cannot truncate history or leave abandoned temporary files."""
    session = RuntimeSession(host, result_formatter=Mock(), operation_formatter=Mock())
    session.record_cmd_history("status")
    session.save_cmd_history()
    session.record_cmd_history("help")
    original = session._history_file.read_bytes()
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(OSError):
        session.save_cmd_history()
    assert session._history_file.read_bytes() == original
    assert not list(session._history_file.parent.glob(".command-history-*"))


def test_history_failed_quarantine_never_overwrites_original(host, monkeypatch):
    """Recovery can remain read-only when preserving damaged input is not possible."""
    path = Path(host.agent.workspace) / ".ucagent/command_history.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(Path, "replace", Mock(side_effect=PermissionError("read-only")))
    session = RuntimeSession(host, result_formatter=Mock(), operation_formatter=Mock())
    session.record_cmd_history("status")
    session.save_cmd_history()
    assert path.read_text() == "{invalid"


def test_config_redaction_covers_subtrees_urls_headers_and_environment(host):
    """The config command never reveals secrets or mutates resolved configuration."""
    config = {"api_key": "api-secret", "key_name": "backend-name", "max_tokens": 123,
              "nested": [{"accessToken": "nested-secret", "public_key": "public"}],
              "headers": {"Authorization": "Bearer header-secret", "X-API-Key": "key-secret"},
              "endpoint": "https://user:url-secret@example.test/api?token=query-secret&mode=read",
              "env": ["OPENAI_API_KEY=env-secret", "MODEL=model-name"],
              "credentials": {"value": "credential-secret"}}
    host.agent.cfg.set_value("test_config", config)
    rendered = host.controller.config_detail("test_config")
    assert "secret" not in json.dumps(rendered)
    assert rendered["key_name"] == "backend-name" and rendered["max_tokens"] == 123
    assert rendered["nested"][0]["public_key"] == "public"
    assert host.controller.config_detail("test_config.api_key") == REDACTED
    assert host.controller.config_detail("test_config.credentials.value") == REDACTED
    assert host.controller.config_detail()["test_config"] == rendered
    assert host.agent.cfg.get_value("test_config.api_key") == "api-secret"
    assert host.registry.execute("config_detail test_config.api_key", CommandSession(Path(host.agent.workspace))).data == REDACTED


def test_http_config_results_and_operation_history_are_redacted(api):
    """Authenticated reads cannot persist the raw secret as a replayable operation result."""
    client, host, _ = api
    host.agent.cfg.set_value("private_test", {"api_key": "synthetic-http-secret"})
    response = client.post("/api/cmd", json={"cmd": "config_detail private_test"})
    assert response.status_code == 200
    assert "synthetic-http-secret" not in response.text
    assert REDACTED in response.text
    assert "synthetic-http-secret" not in json.dumps(host.operations.list())


@pytest.mark.parametrize("owner", ["agent_sessions", "multi_agent", "operations", "services"])
def test_shutdown_retries_failing_owners_without_losing_supervisor(tmp_path, owner):
    """Even a persistent close failure retains ownership and drains after recovery."""
    host, _ = make_host(tmp_path, shutdown_timeout=0.01)
    entered, release = threading.Event(), threading.Event()
    if owner == "agent_sessions":
        target = host.agent_sessions = SimpleNamespace(close=lambda: {"closed": True})
    elif owner == "multi_agent":
        target = host.agent.multi_agent = SimpleNamespace(close=lambda timeout: {"closed": True},
                                                        has_active=lambda: False, issue=None, status=lambda: {"tasks": []})
    else:
        target = getattr(host, owner)
    close = target.close

    def failing_close(*args, **kwargs):
        """Model a recoverable owner failure without dropping its live state."""
        entered.set()
        if not release.is_set():
            raise RuntimeError("owner still live")
        return close(*args, **kwargs)

    target.close = failing_close
    host.start()
    try:
        host.request_shutdown()
        assert entered.wait(2)
        state = host.wait(0.25)
        assert state["instance"] == "closing" and host._thread.is_alive()
        assert state["errors"] == [{"step": owner, "message": "owner still live"}]
        assert owner not in host._steps
    finally:
        release.set()
    state = host.wait(3)
    assert state["instance"] == "failed" and state["exit_code"] == 1
    assert host._closed.is_set() and owner in host._steps


def test_global_cancel_failure_retains_child_for_shutdown_retry(global_runtime, monkeypatch):
    """A cancellation exception neither loses the process handle nor closes the session early."""
    agent_id = start(global_runtime)
    prepare(global_runtime)
    handle = global_runtime.handles[agent_id]
    cancel = global_runtime.launcher.cancel
    monkeypatch.setattr(global_runtime.launcher, "cancel", Mock(side_effect=RuntimeError("cancel failed")))
    with pytest.raises(RuntimeError, match="cancel failed"):
        global_runtime.close()
    assert global_runtime.handles[agent_id] is handle
    assert global_runtime.has_active()
    monkeypatch.setattr(global_runtime.launcher, "cancel", cancel)
    assert global_runtime.close() == {"closed": True}
    assert not global_runtime.handles and not global_runtime.has_active()


@pytest.mark.parametrize("field", ["detail", "evidence"])
def test_review_invalidates_when_prior_stage_content_changes(tmp_path, field):
    """Rewording earlier unresolved work invalidates review without claiming state progress."""
    work = StageWork(tmp_path, "DUT")
    stages = [SimpleNamespace(name=name, is_skipped=lambda: False, is_reached=lambda: True)
              for name in ("first", "second")]
    work.update(stages, 0, "human", "input", "Owner: provide contract", "missing R1")
    work.update(stages, 1, "review", "", "", "Reviewed full scope")
    before = work.view(stages, 1)
    assert before["reviewed"]
    changes = {"detail": "Owner: provide contract", "evidence": "missing R1"}
    changes[field] += "; additional finding"
    work.update(stages, 0, "human", "input", **changes)
    after = StageWork(tmp_path, "DUT").view(stages, 1)
    assert after["states"] == before["states"] and not after["reviewed"]
    work.update(stages, 1, "review", "", "", "Reviewed changed scope")
    assert work.view(stages, 1)["reviewed"]
