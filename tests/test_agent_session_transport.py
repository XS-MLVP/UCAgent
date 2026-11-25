"""Real local HTTP, child processes, cursors and existing-runtime input ownership."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from ucagent.interfaces.server.agent_session import AgentSessionServer, RemoteAgentView, SavedAgentView
from ucagent.runtime.agent_view import LocalAgentView
from ucagent.runtime.agent_events import AgentEvents
from ucagent.util.output import AGENT_ACTOR
from test_runtime_host import make_host

@pytest.fixture
def view(tmp_path):
    host, _ = make_host(tmp_path / "workspace", mode="console")
    host.agent.cfg.set_value("backend", {"key_name": "blank"})
    host.start(); host.startup.release()
    local = LocalAgentView(host, tmp_path / "run", "super-a")
    server = AgentSessionServer(local, tmp_path / "run").start()
    host.agent.one_loop = lambda text=None: host.message_echo("received: " + (text or ""))
    try: yield local, server
    finally:
        server.close(); local.close()
        host.request_shutdown(); host.wait(3)

def test_two_clients_connect_without_constructing_an_agent(view):
    local, server = view
    one, two = RemoteAgentView(server.root), RemoteAgentView(server.root)
    snapshot = one.snapshot()
    assert snapshot["agent_id"] == two.snapshot()["agent_id"] == "super-a"
    assert snapshot["mission"]["mission_name"] == "Stage control tests"
    assert len(snapshot["mission"]["stages"]) == 3
    assert snapshot["statistics"] == local.host.controller.status()
    assert snapshot["backend"] == "blank" and snapshot["use_skills"] is False
    assert any(row["name"] == "status" for row in snapshot["commands"])
    item = one.submit_input("hello")
    deadline = time.monotonic() + 3
    while not any(x["id"] == item["id"] and x["state"] == "delivered" for x in two.snapshot()["inputs"]):
        assert time.monotonic() < deadline
        time.sleep(.02)
    rows = two.events_since()["events"]
    assert any("received: hello" in x["payload"].get("text", "") for x in rows)
    cursor = two.events_since()["cursor"]
    assert not two.events_since(cursor)["events"]
    assert local.host.snapshot()["instance"] == "ready"

def test_structured_sub_identity(view):
    local, server = view
    token = AGENT_ACTOR.set({"agent_id": "super-a/attempt-1/plan/task", "parent_id": "super-a", "role": "sub"})
    try: local.host.message_echo("sub content")
    finally: AGENT_ACTOR.reset(token)
    assert any(x["agent_id"] == "super-a/attempt-1/plan/task" for x in RemoteAgentView(server.root).events_since()["events"])

def test_authentication_and_credentials_permissions(view):
    _, server = view
    assert (server.root / "connection.json").stat().st_mode & 0o077 == 0
    with pytest.raises(HTTPError) as error:
        urlopen(f"http://127.0.0.1:{server.server.server_port}/snapshot")
    assert error.value.code == 401
    assert server.token not in json.dumps(RemoteAgentView(server.root).snapshot())

def test_saved_view_is_readonly_and_replays(view):
    local, server = view
    local.host.message_echo("final message")
    local.close()
    saved = SavedAgentView(server.root)
    assert saved.snapshot()["readonly"]
    assert saved.events_since()["events"]
    with pytest.raises(ValueError, match="read-only"): saved.submit_input("restart")

def test_event_budget_reports_gap_and_keeps_disk_history(tmp_path):
    events = AgentEvents(tmp_path, max_records=2)
    for i in range(5): events.append("a", "message", text=str(i))
    page = events.read()
    assert page["gap"] and len(page["events"]) == 2
    assert len(events.path.read_text().splitlines()) == 5

def test_real_process_attach_and_input(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_runtime_host import make_host
from ucagent.runtime.agent_view import LocalAgentView
from ucagent.interfaces.server.agent_session import AgentSessionServer
path = Path(sys.argv[1])
host, _ = make_host(path / 'workspace', mode='console')
host.agent.cfg.set_value('backend', {'key_name': 'blank'})
host.start(); host.startup.release()
host.agent.one_loop = lambda text=None: host.message_echo('child-reply:' + text)
view = LocalAgentView(host, path, 'child-super')
server = AgentSessionServer(view, path).start()
try:
    while not (path / 'stop').exists(): time.sleep(.05)
finally:
    server.close(); view.close(); host.request_shutdown(); host.wait(3)
"""
    with (tmp_path / "process.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], cwd=root, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 8
            while not (tmp_path / "connection.json").is_file():
                assert process.poll() is None, (tmp_path / "process.log").read_text()
                assert time.monotonic() < deadline
                time.sleep(.03)
            client = RemoteAgentView(tmp_path)
            assert client.snapshot()["agent_id"] == "child-super"
            client.submit_input("real process")
            while not any("child-reply:real process" in x["payload"].get("text", "") for x in client.events_since()["events"]):
                assert time.monotonic() < deadline
                time.sleep(.03)
            assert RemoteAgentView(tmp_path).snapshot()["agent_id"] == "child-super"
            assert process.poll() is None
        finally:
            (tmp_path / "stop").touch()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=5)
        assert process.returncode == 0, (tmp_path / "process.log").read_text()


def test_super_guidance_is_consumed_only_at_a_planning_boundary(tmp_path):
    from test_multi_agent import make_agent
    agent = make_agent(tmp_path)
    try:
        service = agent.multi_agent
        service._instruction = "original task"
        item = service.queue_instruction("consider the new constraint")
        assert service._instruction == "original task"
        assert item["state"] == "queued"
        service._consume_operator_instructions()
        assert service.operator_instructions[0]["state"] == "delivered"
        assert "new constraint" in service._instruction
        before = service._instruction
        service._consume_operator_instructions()
        assert service._instruction == before
    finally:
        agent.multi_agent.close(3)
        agent._startup_cleanup.close()


def test_console_does_not_duplicate_messages(view):
    """A headless child's stdout echo remains logged but is not rendered a second time."""
    local, server = view
    local.host.message_echo("unique model reply")
    local.host.output.write("operator diagnostic\n")
    events = RemoteAgentView(server.root).events_since()["events"]
    replies = [row for row in events if "unique model reply" in row["payload"].get("text", "")]
    assert len(replies) == 1 and replies[0]["kind"] == "message"
    assert any(row["kind"] == "console" and "operator diagnostic" in row["payload"]["text"] for row in events)


def test_disconnected_super_view_is_readonly_and_reconnects(view):
    """An unavailable transport never presents saved state as a live writable session."""
    from ucagent.interfaces.terminal.tui.agent_view import SuperAgentView
    local, server = view
    run = {"agent_id": "super-a", "attempt": 1, "status": "running", "result_path": str(server.root / "run_result.json")}
    client = SuperAgentView(lambda agent_id: run, "super-a")
    assert client.snapshot()["connected"] and not client.snapshot()["readonly"]
    credentials = server.root / "connection.json"
    saved = credentials.read_bytes()
    credentials.unlink()
    try:
        snapshot = client.snapshot()
        assert not snapshot["connected"] and snapshot["readonly"]
        with pytest.raises(ValueError, match="read-only"): client.submit_input("unsafe retry")
    finally:
        credentials.write_bytes(saved); credentials.chmod(0o600)
    assert client.snapshot()["connected"] and not client.snapshot()["readonly"]


def test_langchain_worker_results_are_detail_events_only(view):
    """Newly visible Sub tool bodies do not expand the Super message stream."""
    from ucagent.util.output import output_context
    local, _ = view
    actor = {"agent_id": "super-a/attempt-1/plan/task", "parent_id": "super-a", "role": "sub", "worker_attempt": 1}
    token = AGENT_ACTOR.set(actor)
    try:
        with output_context(source="tool", kind="result"):
            local.host.message_echo("worker tool body")
        local.host.message_echo("worker model message")
    finally:
        AGENT_ACTOR.reset(token)
    rows = [row for row in local.events_since()["events"] if row["agent_id"] == actor["agent_id"]]
    assert [row["kind"] for row in rows] == ["tool_detail", "message"]
