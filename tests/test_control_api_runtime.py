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


def test_page_completion_and_workspace_reset_share_session(api, tmp_path):
    """HTTP completion follows page cwd, quotes paths, and observes same-session resets."""
    client, _, _ = api
    (tmp_path / "nested" / "inside only").mkdir(parents=True)
    assert client.post("/api/cmd", json={"cmd": "cd nested", "session_id": "page"}).status_code == 200
    result = client.get("/api/cmds", params={"prefix": "cd ins", "session_id": "page"}).json()
    assert result["data"] == ["inside only/"]
    assert result["completions"] == ["cd 'inside only/'"]
    quoted = client.get("/api/cmds", params={"prefix": 'cd "ins', "session_id": "page"}).json()
    assert quoted["completions"] == result["completions"]
    assert client.get("/api/cmds", params={"prefix": "cd ins", "session_id": "other"}).json()["data"] == []
    reset = client.post("/api/cmd", json={"cmd": "chcwd .", "session_id": "page"})
    assert reset.status_code == 200
    cwd = client.post("/api/cmd", json={"cmd": "pwd", "session_id": "page"}).json()
    assert cwd["data"]["result"]["cwd"] == str(tmp_path)
    assert client.get("/api/cmds", params={"prefix": "cd nes", "session_id": "page"}).json()["completions"] == ["cd nested/"]
    # Consumers using raw completion tokens retain the existing response field.
    assert client.get("/api/cmds", params={"prefix": "status"}).json()["data"] == ["status"]


def test_completion_uses_selected_workspace_root_and_boundary(api, tmp_path):
    """Nested workspace completion follows its own cwd and never lists parent paths."""
    client, _, _ = api
    child = tmp_path / "child"
    (child / ".ucagent").mkdir(parents=True)
    (child / ".ucagent/ucagent_info.json").write_text("{}")
    (child / "inner" / "leaf").mkdir(parents=True)
    (tmp_path / "parent-only").mkdir()
    (child / "outside").symlink_to(tmp_path, target_is_directory=True)
    query = {"sub_workspace": "child", "session_id": "page"}
    assert client.get("/api/cmds", params={**query, "prefix": "cd in"}).json()["completions"] == ["cd inner/"]
    assert client.post("/api/cmd?sub_workspace=child", json={"cmd": "cd inner", "session_id": "page"}).status_code == 200
    assert client.get("/api/cmds", params={**query, "prefix": "cd le"}).json()["completions"] == ["cd leaf/"]
    assert client.get("/api/cmds", params={**query, "prefix": "cd /in"}).json()["completions"] == ["cd /inner/"]
    for prefix in ("cd ../../", "cd /parent", "cd /outside/"):
        assert client.get("/api/cmds", params={**query, "prefix": prefix}).json()["data"] == []
    assert client.get("/api/cmds", params={"sub_workspace": "../", "prefix": "cd "}).status_code == 403


@pytest.mark.parametrize("strip_ansi", [False, True])
def test_mission_preserves_structured_state_for_live_and_saved_views(api, tmp_path, strip_ansi):
    """Both views retain presentation fields and respect explicit incomplete saved stages."""
    client, _, runtime = api
    runtime.manager.stages[0].fail_count = 2
    live = client.get("/api/mission", params={"strip_ansi": strip_ansi}).json()["data"]
    assert live["stages"][0]["fail_count"] == 2
    assert live["stages"][0]["is_current"] is True
    assert live["stages"][0]["section_index"] == "1"
    assert live["stages"][0]["stage_name"] == "stage-0"
    assert live["is_waiting_for_review"] is False
    assert "time_cost" in live["stages"][0]
    child = tmp_path / "saved"
    (child / ".ucagent").mkdir(parents=True)
    snapshot = {"mission_name": "Saved mission", "stage_index": 2, "stages_info": {
        "0": {"is_completed": False, "fail_count": 3, "time_cost": 12,
              "task": {"title": "Unfinished earlier stage", "skill_list": {"review": []}}},
        "1": {"is_completed": True, "section_index": "2.1", "stage_name": "fixture",
              "display_group": "Setup", "task": {"title": "2.1-fixture-Completed stage"}},
        "2": {"is_skipped": True, "task": {"title": "Skipped stage"}},
    }}
    (child / ".ucagent/ucagent_info.json").write_text(json.dumps(snapshot))
    response = client.get("/api/mission", params={"sub_workspace": "saved", "strip_ansi": strip_ansi})
    assert response.status_code == 200, response.text
    rows = response.json()["data"]["stages"]
    assert rows[0]["is_completed"] is False
    assert rows[0]["fail_count"] == 3 and rows[0]["time_cost"]
    assert rows[0]["skill_list"] == ["review"]
    assert rows[1]["is_completed"] is True and rows[2]["is_skipped"] is True
    assert (rows[1]["section_index"], rows[1]["stage_name"], rows[1]["display_group"]) == ("2.1", "fixture", "Setup")
    assert all(not row["can_edit_flags"] for row in rows)
    assert client.get("/static/share/stage-view.js").status_code == 200


def test_event_views_auth_partial_messages_and_browser_local_cursors(api):
    """Independent browser cursors read identical model history without destructive consumption."""
    client, host, _ = api
    host.attach_control("tui", messages=True)
    host.message_echo("partial", end="")
    first = client.get("/api/events").json()
    assert first["available"] and first["data"][-1]["text"] == "partial"
    assert client.get("/api/events").json()["data"] == first["data"]
    tail = client.get("/api/events?tail=true").json()
    assert tail["data"] == []
    assert client.get("/api/events").json()["data"] == first["data"]
    host.message_echo(" remainder")
    next_page = client.get("/api/events", params={"after": tail["cursor"], "generation": first["generation"]}).json()
    assert next_page["data"][-1]["text"] == " remainder\n"
    assert client.get("/api/events", auth=("user", "wrong")).status_code == 401
    assert client.get("/api/events?view=unknown").status_code == 400
    assert client.get("/api/events?limit=1001").status_code == 422
    assert client.get("/api/events?after=-1").status_code == 422
    host.detach_control("tui")


def test_saved_workspace_never_displays_live_host_output_or_operations(api, tmp_path):
    """Historical views cannot misattribute Master output or clear another instance's transcript."""
    client, host, _ = api
    (tmp_path / "child/.ucagent").mkdir(parents=True)
    (tmp_path / "child/.ucagent/ucagent_info.json").write_text("{}")
    host.message_echo("host-only message")
    host.output.inject("host raw output")
    events = client.get("/api/events?sub_workspace=child").json()
    assert events["available"] is False and events["data"] == []
    assert client.get("/api/console?sub_workspace=child").json()["data"] == []
    assert client.get("/api/runtime/status?sub_workspace=child").json()["data"]["operations"] == []
    assert client.get("/api/events?sub_workspace=../").status_code == 403
    assert client.delete("/api/console?sub_workspace=child").status_code == 403
    assert any("host raw output" in line for line in client.get("/api/console").json()["data"])


def test_shell_events_preserve_stream_identity_and_failure_summary(api):
    """A shell stderr stream and a failed operation remain visible in the default activity view."""
    client, host, _ = api
    response = client.post("/api/cmd", json={"cmd": "shell printf out; printf err >&2; exit 7", "session_id": "page"})
    result = host.operations.wait(response.json()["operation_id"], 3)
    assert result["state"] == "failed"
    rows = client.get("/api/events").json()["data"]
    assert any(row["stream"] == "stderr" and "err" in row["text"] for row in rows)
    assert any(row["kind"] == "result" and row["level"] == "ERROR" for row in rows)
    assert all(row["operation_id"] == result["id"] for row in rows)
    assert result["session_id"] is not None
    assert all(row["session_id"] == result["session_id"] for row in rows)


def test_saved_workspace_command_results_are_local_to_selected_workspace(api, tmp_path):
    """A saved workspace's file commands stay usable without displaying parent operations."""
    client, host, _ = api
    (tmp_path / "child/.ucagent").mkdir(parents=True)
    (tmp_path / "child/.ucagent/ucagent_info.json").write_text("{}")
    parent = client.post("/api/cmd", json={"cmd": "pwd", "session_id": "page"}).json()
    child = client.post("/api/cmd?sub_workspace=child", json={"cmd": "pwd", "session_id": "page"}).json()
    rows = client.get("/api/runtime/status?sub_workspace=child").json()["data"]["operations"]
    assert [row["id"] for row in rows] == [child["operation_id"]]
    assert rows[0]["result"]["cwd"] == str(tmp_path / "child")
    assert parent["operation_id"] != child["operation_id"]
    assert not any(row["operation_id"] == child["operation_id"] for row in host.events.read("activity")["data"])
