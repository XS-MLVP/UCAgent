"""Focused tests for the master-mode parallel task limit and waiting queue."""

import os
import sys
import tempfile
import time
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.server.api_master import PdbMasterApiServer
from ucagent.util.config import Config


def _mark_starting(server, task_id):
    task = server._tasks[task_id]
    task["process_status"] = "starting"
    task["started_at"] = time.time()


def _finish_task(server, task_id):
    task = server._tasks[task_id]
    task["process_status"] = "stopped"
    task["finished_at"] = time.time()


@contextmanager
def _queue_server(max_task_count):
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {"file_browser_roots": [], "default_args": {"launch_mode": ["process"]}},
            "master_api": {"max_task_count": max_task_count},
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
        yield server


def _add_compiled_workspace(server):
    ws = server._create_workspace()
    server._ensure_workspace_materialized(ws["workspace_id"])
    picker_workspace = ws["picker_workspace"]
    with open(os.path.join(picker_workspace, "Adder.v"), "w", encoding="utf-8") as fh:
        fh.write("module Adder(); endmodule\n")
    with server._workspaces_lock:
        server._workspaces[ws["workspace_id"]]["compile"] = {
            "status": "success",
            "picker_workspace": picker_workspace,
            "dut_name": "Adder",
            "selected_module": "Adder",
            "picker_extra_args": [],
        }
    return ws


def _fake_launch_factory(server):
    calls = []

    def fake_launch(req, ws, prepared, compile_info, picker_status):
        calls.append(str(req.get("workspace_id") or ""))
        task = server._create_task_record({
            "task_id": str(ws.get("task_id") or req.get("workspace_id") or ""),
            "task_name": req.get("task_name") or "Adder",
            "workspace_id": str(req.get("workspace_id") or ""),
            "launch_mode": "process",
            "workspace_dir": str(prepared.get("workspace_dir") or ""),
            "cmd_api": {"enabled": True, "status": "starting", "port": 8765},
            "terminal_api": {"enabled": False, "status": "stopped"},
            "web_console": {"enabled": False, "status": "stopped"},
        })
        _mark_starting(server, task["task_id"])
        return task

    fake_launch.calls = calls
    return fake_launch


def _launch(client, ws, task_name="task"):
    response = client.post(
        "/api/tasks",
        json={
            "workspace_id": ws["workspace_id"],
            "selected_module": "Adder",
            "dut_name": "Adder",
            "task_name": task_name,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_max_task_count_reads_config_and_falls_back_to_default():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        assert server._max_task_count() == 100

        cfg = Config({
            "launch": {"file_browser_roots": []},
            "master_api": {"max_task_count": 3},
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
        assert server._max_task_count() == 3

        for invalid in ("abc", 0, -2, None):
            cfg = Config({
                "launch": {"file_browser_roots": []},
                "master_api": {"max_task_count": invalid},
            }).freeze()
            server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
            assert server._max_task_count() == 100


def test_launch_queues_when_saturated_and_dispatches_in_order():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws1 = _add_compiled_workspace(server)
        ws2 = _add_compiled_workspace(server)
        ws3 = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            first = _launch(client, ws1, "one")
            assert first["task"]["process_status"] == "starting"

            second = _launch(client, ws2, "two")
            assert second["task"]["process_status"] == "waiting"
            assert "waiting_request" not in second["task"]
            # The task page disables CMD/Terminal for waiting tasks based on
            # these child-service flags staying off until the task starts.
            assert second["task"]["cmd_api"]["enabled"] is False
            assert second["task"]["terminal_api"]["enabled"] is False
            assert second["task"]["web_console"]["enabled"] is False

            third = _launch(client, ws3, "three")
            assert third["task"]["process_status"] == "waiting"

            assert server._waiting_queue_positions() == {
                ws2["task_id"]: 1,
                ws3["task_id"]: 2,
            }
            waiting_list = client.get("/api/tasks?status=waiting").json()["tasks"]
            assert {item["task_id"]: item["queue_position"] for item in waiting_list} == {
                ws2["task_id"]: 1,
                ws3["task_id"]: 2,
            }
            tasks_meta = client.get("/api/tasks").json()
            assert tasks_meta["max_task_count"] == 1
            agents = client.get("/api/agents").json()
            assert agents["waiting_task_count"] == 2

            _finish_task(server, ws1["task_id"])
            server._dispatch_waiting_tasks()
            assert server._tasks[ws2["task_id"]]["process_status"] == "starting"
            assert server._tasks[ws3["task_id"]]["process_status"] == "waiting"

            _finish_task(server, ws2["task_id"])
            server._dispatch_waiting_tasks()
            assert server._tasks[ws3["task_id"]]["process_status"] == "starting"
            assert server._waiting_tasks() == []

        assert fake_launch.calls == [ws1["workspace_id"], ws2["workspace_id"], ws3["workspace_id"]]


def test_new_submission_queues_behind_existing_waiters():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws1 = _add_compiled_workspace(server)
        ws2 = _add_compiled_workspace(server)
        ws3 = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws1, "one")
            assert _launch(client, ws2, "two")["task"]["process_status"] == "waiting"
            # A slot is free now, but ws2 is still waiting, so ws3 must not jump ahead.
            _finish_task(server, ws1["task_id"])
            assert _launch(client, ws3, "three")["task"]["process_status"] == "waiting"

            server._dispatch_waiting_tasks()
            assert server._tasks[ws2["task_id"]]["process_status"] == "starting"
            assert server._tasks[ws3["task_id"]]["process_status"] == "waiting"


def test_delete_waiting_task_cancels_and_removes_workspace_directory():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws1 = _add_compiled_workspace(server)
        ws2 = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws1, "one")
            assert _launch(client, ws2, "two")["task"]["process_status"] == "waiting"

        ws2_dir = ws2["workspace_dir"]
        assert os.path.isdir(ws2_dir)

        response = client.delete(f"/api/task/{ws2['task_id']}")

        assert response.status_code == 200
        assert response.json()["removed_workspace_dir"] == ws2_dir
        assert not os.path.exists(ws2_dir)
        assert ws2["workspace_id"] not in server._workspaces
        assert ws2["task_id"] not in server._tasks


def test_stop_waiting_task_leaves_record_and_workspace_for_relaunch():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws1 = _add_compiled_workspace(server)
        ws2 = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws1, "one")
            assert _launch(client, ws2, "two")["task"]["process_status"] == "waiting"

        response = client.post(f"/api/task/{ws2['task_id']}/stop", json={})

        assert response.status_code == 200
        assert response.json()["message"] == "Task removed from waiting queue"
        assert server._tasks[ws2["task_id"]]["process_status"] == "stopped"
        assert ws2["workspace_id"] in server._workspaces
        assert os.path.isdir(ws2["workspace_dir"])
        # A stopped ex-waiting task no longer blocks later dispatches.
        _finish_task(server, ws1["task_id"])
        server._dispatch_waiting_tasks()
        assert server._waiting_tasks() == []


def test_dispatch_failure_keeps_failed_task_record():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws1 = _add_compiled_workspace(server)
        ws2 = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws1, "one")
            assert _launch(client, ws2, "two")["task"]["process_status"] == "waiting"

        # The workspace disappears while the task waits (for example the master
        # database is edited or the directory is removed by hand).
        server._remove_path(ws2["workspace_dir"])
        with server._workspaces_lock:
            server._workspaces.pop(ws2["workspace_id"], None)

        _finish_task(server, ws1["task_id"])
        server._dispatch_waiting_tasks()

        failed = server._tasks[ws2["task_id"]]
        assert failed["process_status"] == "failed"
        assert failed["finished_at"]


def test_reorder_waiting_queue_changes_dispatch_order():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws_active = _add_compiled_workspace(server)
        ws_a = _add_compiled_workspace(server)
        ws_b = _add_compiled_workspace(server)
        ws_c = _add_compiled_workspace(server)
        ws_d = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws_active, "active")
            for ws in (ws_a, ws_b, ws_c):
                assert _launch(client, ws)["task"]["process_status"] == "waiting"

            response = client.post(
                "/api/tasks/waiting/order",
                json={"task_ids": [ws_c["task_id"], ws_a["task_id"], ws_b["task_id"]]},
            )
            assert response.status_code == 200
            assert response.json()["task_ids"] == [ws_c["task_id"], ws_a["task_id"], ws_b["task_id"]]
            assert server._waiting_queue_positions() == {
                ws_c["task_id"]: 1,
                ws_a["task_id"]: 2,
                ws_b["task_id"]: 3,
            }

            # A submission made after a reorder lands at the back of the queue.
            assert _launch(client, ws_d)["task"]["process_status"] == "waiting"
            assert server._waiting_queue_positions()[ws_d["task_id"]] == 4

            _finish_task(server, ws_active["task_id"])
            server._dispatch_waiting_tasks()
            assert server._tasks[ws_c["task_id"]]["process_status"] == "starting"

            _finish_task(server, ws_c["task_id"])
            server._dispatch_waiting_tasks()
            assert server._tasks[ws_a["task_id"]]["process_status"] == "starting"
            assert server._tasks[ws_b["task_id"]]["process_status"] == "waiting"


def test_reorder_waiting_queue_validates_payload_and_keeps_order():
    with _queue_server(1) as server:
        client = TestClient(server._app)
        ws_active = _add_compiled_workspace(server)
        ws_a = _add_compiled_workspace(server)
        ws_b = _add_compiled_workspace(server)
        fake_launch = _fake_launch_factory(server)

        with patch.object(server, "_launch_validated_task", side_effect=fake_launch):
            _launch(client, ws_active, "active")
            _launch(client, ws_a, "a")
            _launch(client, ws_b, "b")

        id_a, id_b = ws_a["task_id"], ws_b["task_id"]
        original = {id_a: 1, id_b: 2}
        payloads = [
            {"task_ids": "not-a-list"},
            {"task_ids": []},
            {"task_ids": [id_a, id_b, "unknown-task"]},
            {"task_ids": [id_a]},
            {"task_ids": [id_a, id_a, id_b]},
            {},
        ]
        for payload in payloads:
            response = client.post("/api/tasks/waiting/order", json=payload)
            assert response.status_code == 400, payload
            assert server._waiting_queue_positions() == original


def test_task_public_hides_waiting_request_payload():
    with _queue_server(1) as server:
        task = server._create_task_record({"task_id": "queued", "task_name": "queued"})
        task["process_status"] = "waiting"
        task["waiting_request"] = {"env": {"OPENAI_API_KEY": "secret"}}

        data = server._task_public(task, include_logs=True)

        assert "waiting_request" not in data
        assert data["process_status"] == "waiting"
        # The stored record itself keeps the request for dispatch.
        assert task["waiting_request"]["env"]["OPENAI_API_KEY"] == "secret"
