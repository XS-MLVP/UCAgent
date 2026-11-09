"""Authenticated controls exercise real operation ownership and per-session directories."""

import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from test_runtime_host import make_host
from ucagent.interfaces.server.api_cmd import ControlApiServer


@pytest.fixture
def api(tmp_path):
    """Serve the actual control routes against a host with real stages and execution."""
    host, runtime = make_host(tmp_path)
    runtime.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    server = ControlApiServer(host.controller, registry=host.registry, operations=host.operations,
                              services=host.services, host_control=host, sock="", password="control-secret")
    client = TestClient(server._app)
    client.auth = ("user", "control-secret")
    host.attach_control("test-http")
    host.start()
    yield client, host, runtime
    server.stop()
    host.request_shutdown()
    assert host.wait(3)["instance"] == "closed"


def test_submission_status_and_cancellation_follow_real_operation(api):
    """Acceptance has an ID; cancellation completes only through the worker."""
    client, host, runtime = api
    response = client.post("/api/cmd", json={"cmd": "sleep 10"})
    assert response.status_code == 200, response.text
    operation_id = response.json()["operation_id"]
    assert client.get(f"/api/operations/{operation_id}").json()["data"]["state"] == "running"
    assert client.post(f"/api/operations/{operation_id}/cancel").status_code == 200
    assert host.operations.wait(operation_id, 2)["state"] == "cancelled"
    assert client.get("/api/runtime/status").json()["data"]["instance"] == "ready"
    assert client.get("/api/pdb_status").status_code == 404
    assert client.post("/api/interrupt").status_code == 404


def test_failures_authentication_and_unknown_commands_are_explicit(api):
    """A failed shell stays failed, and unknown input never reaches the shell."""
    client, host, _ = api
    assert client.get("/api/runtime/status", auth=("user", "wrong")).status_code == 401
    assert client.post("/api/cmd", json={"cmd": "echo dangerous"}).status_code == 404
    response = client.post("/api/cmd", json={"cmd": "shell exit 7"})
    result = host.operations.wait(response.json()["operation_id"], 2)
    assert result["state"] == "failed" and result["result"]["returncode"] == 7
    assert client.get("/api/operations/unknown").status_code == 404


def test_batch_waits_for_predecessor_and_preserves_parse_errors(api, tmp_path):
    """Ordered commands observe predecessor side effects and report invalid rows."""
    client, host, _ = api
    response = client.post("/api/cmds/batch", json={"cmds": [
        "shell printf first > sequence.txt", "shell cat sequence.txt", "sleep invalid", "pwd"]})
    result = host.operations.wait(response.json()["operation_id"], 3)
    assert result["state"] == "failed", result
    rows = result["result"]
    assert host.operations.get(rows[1]["operation_id"])["stdout"] == "first"
    assert rows[2]["error"]["code"] == "invalid_argument"
    assert rows[3]["state"] == "succeeded"


def test_session_directories_and_subworkspace_permissions_are_isolated(api, tmp_path):
    """Directory changes are local, while child views cannot mutate the parent workflow."""
    client, host, _ = api
    child = tmp_path / "child"
    (child / ".ucagent").mkdir(parents=True)
    (child / ".ucagent/ucagent_info.json").write_text("{}")
    assert client.post("/api/cmd", json={"cmd": "cd child", "session_id": "a"}).status_code == 200
    for session, expected in [("a", child), ("b", tmp_path)]:
        response = client.post("/api/cmd", json={"cmd": "pwd", "session_id": session})
        assert response.json()["data"]["result"]["cwd"] == str(expected)
    assert client.post("/api/cmd?sub_workspace=child", json={"cmd": "hmcheck_pass"}).status_code == 403
    assert client.post("/api/cmd?sub_workspace=child", json={"cmd": "cd .."}).status_code == 400
    assert client.post("/api/cmd", json={"cmd": "pwd", "cwd": "../"}).status_code == 403


def test_review_rejects_stale_revision_and_preserves_completion_gate(api):
    """HTTP approval uses the exact displayed target and cannot itself complete the stage."""
    client, host, runtime = api
    revision = client.get("/api/stages/state").json()["data"]["control_revision"]
    body = {"index": 0, "expected_revision": revision, "approved": True, "message": "Reviewed"}
    assert client.post("/api/stages/review", json=body).status_code == 200
    assert client.post("/api/stages/review", json=body).status_code == 409
    assert runtime.manager.stages[0].get_hmcheck_state() == (True, "Reviewed")
    assert runtime.manager.stages[0].is_completed() is False


def test_remote_shell_confirmation_is_structured_and_never_reads_stdin(api, tmp_path, monkeypatch):
    """The existing dangerous-command confirmation is supplied explicitly over HTTP."""
    client, host, _ = api

    def unexpected_input(*args):
        """Fail if a service request attempts interactive confirmation."""
        raise AssertionError("HTTP must not read stdin")

    monkeypatch.setattr("builtins.input", unexpected_input)
    target = tmp_path / "temporary.txt"
    target.write_text("disposable test file")
    response = client.post("/api/cmd", json={"cmd": "shell rm temporary.txt"})
    assert response.status_code == 400 and target.exists()
    response = client.post("/api/cmd", json={"cmd": "shell rm temporary.txt", "confirmed": True})
    assert host.operations.wait(response.json()["operation_id"], 2)["state"] == "succeeded"
    assert not target.exists()
