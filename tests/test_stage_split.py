import json
from types import SimpleNamespace

import pytest

from ucagent.cli import _is_completed_agent_shutdown
from ucagent.server.api_master import PdbMasterApiServer, _normalize_stage_segments
from ucagent.util.config import Config
from ucagent.verify_agent import VerifyAgent


def _segments():
    segments = _normalize_stage_segments([
        {
            "name": "stages-0-13",
            "stage_start": 0,
            "stage_end": 13,
            "resources": {
                "requests": {"cpu": "1", "memory": "2Gi"},
                "limits": {"cpu": "3", "memory": "4Gi"},
            },
        },
        {
            "name": "stages-15-27",
            "stage_start": 15,
            "stage_end": 27,
            "resources": {
                "requests": {"cpu": "2", "memory": "3Gi"},
                "limits": {"cpu": "4", "memory": "6Gi"},
            },
        },
    ])
    for segment in segments:
        segment["client_id"] = f"agent-s{segment['index']}"
    return segments


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("UCAGENT_STAGE_METRICS_PORT", "0")
    cfg = Config({
        "launch": {
            "file_browser_roots": [],
            "cluster": {
                "image": "ucagent:stage-split-test",
                "container_command": "ucagent",
                "k8s_namespace": "ucagent",
                "k8s_image_pull_policy": "Never",
                "k8s_service_account": "ucagent-stage-split-task",
                "k8s_node_selector": {"kubernetes.io/hostname": "node7"},
                "k8s_resources": {
                    "requests": {"cpu": "500m", "memory": "1Gi"},
                },
            },
        },
    }).freeze()
    return PdbMasterApiServer(workspace=str(tmp_path), cfg=cfg)


def _task(tmp_path, current_segment_index=0):
    return {
        "task_id": "split-task",
        "launch_mode": "k8s",
        "segments": _segments(),
        "current_segment_index": current_segment_index,
        "resolved_command": ["ucagent", "--workspace", "/tmp/workspace"],
        "env": {},
        "stdout_log_path": str(tmp_path / "stdout.log"),
        "stderr_log_path": str(tmp_path / "stderr.log"),
        "cmd_api": {"enabled": False, "status": "starting"},
        "terminal_api": {"enabled": False, "status": "starting"},
        "web_console": {"enabled": False, "status": "disabled"},
        "process_status": "running",
        "logical_status": "running",
        "started_at": 1.0,
        "cluster": {},
    }


def test_stage_segments_allow_gaps_for_runtime_skipped_stages():
    segments = _normalize_stage_segments([
        {"stage_start": 0, "stage_end": 13},
        {"stage_start": 15, "stage_end": 17},
        {"stage_start": 19, "stage_end": 27},
    ])

    assert [(item["stage_start"], item["stage_end"]) for item in segments] == [
        (0, 13),
        (15, 17),
        (19, 27),
    ]


def test_stage_segments_reject_nonzero_first_stage_and_overlaps():
    with pytest.raises(ValueError, match="must start at 0"):
        _normalize_stage_segments([{"stage_start": 1, "stage_end": 13}])
    with pytest.raises(ValueError, match="must start after stage 13"):
        _normalize_stage_segments([
            {"stage_start": 0, "stage_end": 13},
            {"stage_start": 13, "stage_end": 27},
        ])


def test_k8s_manifest_uses_segment_name_resources_labels_and_env(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)

    manifest = server._k8s_manifest(
        task,
        {},
        {
            "use_zip_workspace": True,
            "workspace_dir": str(tmp_path),
            "picker_workspace": str(tmp_path),
        },
        task["cmd_api"],
        task["terminal_api"],
        task["web_console"],
    )

    assert manifest["metadata"]["name"] == "ucagent-split-task-s0"
    assert manifest["metadata"]["labels"]["ucagent-segment-index"] == "0"
    assert manifest["spec"]["backoffLimit"] == 0
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"] == task["segments"][0]["resources"]
    env = {item["name"]: item.get("value") for item in container["env"]}
    assert env["UCAGENT_SEGMENT_INDEX"] == "0"
    assert env["UCAGENT_SEGMENT_START"] == "0"
    assert env["UCAGENT_SEGMENT_END"] == "13"


def test_segment_handoff_validates_saved_stage_and_records_digest(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    server._tasks[task["task_id"]] = task
    info_dir = tmp_path / ".ucagent"
    info_dir.mkdir(exist_ok=True)
    (info_dir / "ucagent_info.json").write_text(json.dumps({
        "stage_index": 15,
        "all_completed": False,
        "stages_info": {"13": {"is_completed": True}},
    }), encoding="utf-8")
    sync_info = {
        "task_id": task["task_id"],
        "agent_id": "agent-s0",
        "target_dir": str(tmp_path),
        "archive_sha256": "abc123",
    }

    handoff = server._record_segment_handoff(
        sync_info,
        agent_id="agent-s0",
        segment_index=0,
        segment_start=0,
        segment_end=13,
    )

    assert handoff["next_stage_index"] == 15
    assert handoff["archive_sha256"] == "abc123"
    assert task["segments"][0]["status"] == "handoff_ready"


def test_segment_handoff_rejects_stage_in_unconfigured_gap(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    server._tasks[task["task_id"]] = task
    info_dir = tmp_path / ".ucagent"
    info_dir.mkdir(exist_ok=True)
    (info_dir / "ucagent_info.json").write_text(json.dumps({
        "stage_index": 14,
        "all_completed": False,
        "stages_info": {"13": {"is_completed": True}},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="outside the next segment"):
        server._record_segment_handoff(
            {
                "task_id": task["task_id"],
                "agent_id": "agent-s0",
                "target_dir": str(tmp_path),
            },
            agent_id="agent-s0",
            segment_index=0,
            segment_start=0,
            segment_end=13,
        )


def test_worker_queues_pdb_quit_after_successful_segment_handoff():
    sync_calls = []
    exit_reasons = []
    client = SimpleNamespace(
        is_running=True,
        sync_workspace_back=lambda reason: (sync_calls.append(reason) or (True, "synced")),
    )
    pdb = SimpleNamespace(
        _master_clients={"master": client},
        _in_tui=False,
        cmdqueue=[],
        _notify_master_clients_exit=lambda reason: exit_reasons.append(reason),
    )
    agent = SimpleNamespace(
        pdb=pdb,
        stage_segment_index=0,
        _sync_workspace_back_on_exit_done=False,
        _segment_exit_requested=False,
        flush_stage_events_to_master=lambda: None,
        set_break=lambda value: setattr(agent, "break_requested", value),
    )

    ok, message = VerifyAgent.complete_stage_segment(agent, 0, 1)

    assert ok is True
    assert "workspace persisted for stage 1" in message
    assert sync_calls == ["segment_complete"]
    assert agent._sync_workspace_back_on_exit_done is True
    assert agent._segment_exit_requested is True
    assert agent.break_requested is True
    assert pdb.cmdqueue == ["quit"]
    assert exit_reasons == ["segment_complete:0:0:1"]


def test_segment_handoff_without_interactive_pdb_queue_still_succeeds():
    client = SimpleNamespace(
        is_running=True,
        sync_workspace_back=lambda reason: (True, reason),
    )
    agent = SimpleNamespace(
        pdb=SimpleNamespace(
            _master_clients={"master": client},
            _notify_master_clients_exit=lambda reason: None,
        ),
        stage_segment_index=3,
        _sync_workspace_back_on_exit_done=False,
        _segment_exit_requested=False,
        flush_stage_events_to_master=lambda: None,
        set_break=lambda value: None,
    )

    ok, _ = VerifyAgent.complete_stage_segment(agent, 6, 7)

    assert ok is True
    assert agent._segment_exit_requested is True


def test_completed_intermediate_job_launches_next_segment_once(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    task["segments"][0]["handoff"] = {"ready_at": 2.0}
    launches = []
    monkeypatch.setattr(server, "_cluster_alive_status", lambda _task: (False, 0, "Complete"))
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    def start_next(current_task):
        launches.append(current_task["current_segment_index"] + 1)
        current_task["current_segment_index"] += 1
        current_task["process_status"] = "running"

    monkeypatch.setattr(server, "_start_next_k8s_segment", start_next)

    server._refresh_segmented_k8s_task(task, matched_agent=None, now=3.0)

    assert launches == [1]
    assert task["segments"][0]["status"] == "completed"
    assert task["current_segment_index"] == 1


def test_next_segment_does_not_reuse_initial_forced_stage(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    task["workspace_id"] = "workspace-1"
    task["launch_prepared"] = {
        "workspace_dir": str(tmp_path),
        "picker_workspace": str(tmp_path),
        "use_zip_workspace": True,
    }
    task["cli_args_structured"] = {"force_stage_index": 21}
    server._workspaces["workspace-1"] = {}
    captured = {}
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    def build_command(req, _prepared, _cmd_api):
        captured.update(req)
        return ["ucagent"], {}

    monkeypatch.setattr(server, "_build_ucagent_command", build_command)
    monkeypatch.setattr(server, "_start_task_k8s", lambda *_args: {})

    server._start_next_k8s_segment(task)

    assert task["current_segment_index"] == 1
    assert captured["stage_segment_index"] == 1
    assert "force_stage_index" not in captured


def test_validated_handoff_survives_post_handoff_worker_exit_error(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    task["segments"][0]["handoff"] = {"ready_at": 2.0}
    launches = []
    monkeypatch.setattr(server, "_cluster_alive_status", lambda _task: (False, 1, "Failed"))
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    def start_next(current_task):
        launches.append(current_task["current_segment_index"] + 1)
        current_task["current_segment_index"] += 1
        current_task["process_status"] = "running"

    monkeypatch.setattr(server, "_start_next_k8s_segment", start_next)

    server._refresh_segmented_k8s_task(task, matched_agent=None, now=3.0)

    assert launches == [1]
    assert task["segments"][0]["status"] == "completed"
    assert task["segments"][0]["exit_code"] == 1
    assert task["segments"][0]["post_handoff_exit_code"] == 1
    assert "validated workspace handoff" in (tmp_path / "stderr.log").read_text()


def test_worker_exit_error_without_handoff_fails_segment(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    monkeypatch.setattr(server, "_cluster_alive_status", lambda _task: (False, 1, "Failed"))
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    server._refresh_segmented_k8s_task(task, matched_agent=None, now=3.0)

    assert task["segments"][0]["status"] == "failed"
    assert task["logical_status"] == "failed"
    assert task["exit_code"] == 1


def test_k8s_completed_job_status_does_not_shift_missing_active_field(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path)
    task["cluster"] = {
        "name": "ucagent-split-task-s0",
        "namespace": "ucagent",
    }
    monkeypatch.setattr(server, "_k8s_cli_available", lambda: True)
    monkeypatch.setattr(
        server,
        "_run_control_command",
        lambda command, timeout: (
            0,
            json.dumps({"status": {"succeeded": 1}}),
            "",
        ),
    )

    alive, exit_code, detail = server._cluster_alive_status(task)

    assert alive is False
    assert exit_code == 0
    assert detail == "active=0 succeeded=1 failed=0"


def test_final_segment_requires_mission_complete_and_matching_sync(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path, current_segment_index=1)
    task["workspace_sync_back"] = {"agent_id": "agent-s1"}
    monkeypatch.setattr(server, "_cluster_alive_status", lambda _task: (False, 0, "Complete"))
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    server._refresh_segmented_k8s_task(
        task,
        matched_agent={"is_mission_complete": True},
        now=3.0,
    )

    assert task["segments"][1]["status"] == "completed"
    assert task["logical_status"] == "completed"
    assert task["process_status"] == "stopped"
    assert task["exit_code"] == 0


def test_final_segment_accepts_post_completion_exit_error(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    task = _task(tmp_path, current_segment_index=1)
    task["workspace_sync_back"] = {"agent_id": "agent-s1"}
    monkeypatch.setattr(server, "_cluster_alive_status", lambda _task: (False, 1, "Failed"))
    monkeypatch.setattr(server, "_close_task_runtime", lambda _task_id: None)

    server._refresh_segmented_k8s_task(
        task,
        matched_agent={"is_mission_complete": True},
        now=3.0,
    )

    assert task["segments"][1]["status"] == "completed"
    assert task["segments"][1]["post_completion_exit_code"] == 1
    assert task["logical_status"] == "completed"
    assert task["exit_code"] == 0


def test_completed_agent_shutdown_interrupt_detection():
    completed = SimpleNamespace(
        is_exit=lambda: True,
        stage_manager=SimpleNamespace(all_completed=True),
    )
    incomplete = SimpleNamespace(
        is_exit=lambda: False,
        stage_manager=SimpleNamespace(all_completed=True),
    )

    assert _is_completed_agent_shutdown(completed) is True
    assert _is_completed_agent_shutdown(incomplete) is False
