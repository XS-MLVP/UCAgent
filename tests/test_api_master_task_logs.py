import os
import json
import shutil
import sys
import tarfile
import tempfile
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.server.api_master import (
    PdbMasterApiServer,
    _tail_file,
    _task_logs_for_display,
    _task_stderr_tail,
)
from ucagent.util.config import Config


def test_master_launch_workspace_defaults_to_master_workspace():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)

        ws = server._create_workspace()

        assert ws["base_root"] == os.path.abspath(master_ws)
        assert ws["workspace_dir"].startswith(os.path.abspath(master_ws) + os.sep)
        assert os.path.basename(ws["workspace_dir"]) == ws["workspace_id"]
        assert ws["task_id"] == ws["workspace_id"]


def test_task_record_reuses_launch_workspace_task_id():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)

        ws = server._create_workspace()
        task = server._create_task_record({
            "task_id": ws["task_id"],
            "workspace_id": ws["workspace_id"],
        })

        assert task["task_id"] == ws["task_id"]
        assert server._get_workspace(ws["workspace_id"])["task_id"] == task["task_id"]


def test_master_server_uses_passed_config_for_launch_defaults():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {
                "file_browser_roots": [],
                "default_args": {"launch_mode": "docker_swarm"},
                "cluster": {"image": "123123123"},
            },
        }).freeze()

        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)

        assert server._enabled_launch_modes() == ["docker_swarm"]
        assert server._launch_cluster_config()["image"] == "123123123"


def test_compiled_workspace_archive_uses_sync_workspace_ignore_patterns():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {"file_browser_roots": []},
            "master_api": {
                "sync_workspace": {
                    "ignore_patterns": [
                        "*.pyc",
                        "__pycache__",
                        "uc_test_report/",
                    ],
                },
            },
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
        ws = server._create_workspace()
        picker_workspace = ws["picker_workspace"]
        os.makedirs(os.path.join(picker_workspace, "pkg", "__pycache__"), exist_ok=True)
        os.makedirs(os.path.join(picker_workspace, "uc_test_report"), exist_ok=True)
        with open(os.path.join(picker_workspace, "keep.txt"), "w", encoding="utf-8") as fh:
            fh.write("keep")
        with open(os.path.join(picker_workspace, "pkg", "keep.py"), "w", encoding="utf-8") as fh:
            fh.write("keep")
        with open(os.path.join(picker_workspace, "pkg", "module.pyc"), "wb") as fh:
            fh.write(b"ignored")
        with open(os.path.join(picker_workspace, "pkg", "__pycache__", "module.pyc"), "wb") as fh:
            fh.write(b"ignored")
        with open(os.path.join(picker_workspace, "uc_test_report", "index.html"), "w", encoding="utf-8") as fh:
            fh.write("ignored")
        ws["compile"] = {
            "status": "success",
            "picker_workspace": picker_workspace,
        }

        archive_path, _filename, temp_dir = server._create_compiled_workspace_archive(ws, "compiled")
        try:
            with tarfile.open(archive_path, "r:gz") as tf:
                names = set(tf.getnames())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        assert "workspace/keep.txt" in names
        assert "workspace/pkg/keep.py" in names
        assert "workspace/pkg/module.pyc" not in names
        assert "workspace/pkg/__pycache__" not in names
        assert "workspace/pkg/__pycache__/module.pyc" not in names
        assert "workspace/uc_test_report" not in names
        assert "workspace/uc_test_report/index.html" not in names


def test_relaunch_ucagent_info_workspace_can_be_archived_without_compile():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        ws = server._create_workspace()
        picker_workspace = ws["picker_workspace"]
        os.makedirs(os.path.join(picker_workspace, ".ucagent"), exist_ok=True)
        with open(os.path.join(picker_workspace, ".ucagent", "ucagent_info.json"), "w", encoding="utf-8") as fh:
            json.dump({"dut_name": "Adder", "selected_module": "Adder"}, fh)
        with open(os.path.join(picker_workspace, "keep.txt"), "w", encoding="utf-8") as fh:
            fh.write("keep")
        ws["compile"] = {}

        archive_path, _filename, temp_dir = server._create_compiled_workspace_archive(ws, "relaunch")
        try:
            with tarfile.open(archive_path, "r:gz") as tf:
                names = set(tf.getnames())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        assert "workspace/.ucagent/ucagent_info.json" in names
        assert "workspace/keep.txt" in names


def test_cluster_mounts_keep_master_source_host_path(monkeypatch):
    with tempfile.TemporaryDirectory() as master_ws, tempfile.TemporaryDirectory() as task_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        source_host_path = "/host/path/UCAgent-not-visible-inside-master-container"
        monkeypatch.setenv("UCAGENT_MASTER_SOURCE", source_host_path)

        mounts = server._cluster_mounts({"workspace_dir": task_ws})

        assert (os.path.abspath(task_ws), os.path.abspath(task_ws)) in mounts
        assert (source_host_path, "/UCAgent") in mounts


def test_master_source_overrides_process_launch_cli(monkeypatch):
    with tempfile.TemporaryDirectory() as master_ws, tempfile.TemporaryDirectory() as source_ws:
        source_cli = os.path.join(source_ws, "ucagent", "cli.py")
        os.makedirs(os.path.dirname(source_cli))
        open(source_cli, "w", encoding="utf-8").close()
        monkeypatch.setenv("UCAGENT_MASTER_SOURCE", source_ws)
        server = PdbMasterApiServer(workspace=master_ws)

        argv, _env = server._build_ucagent_command(
            {},
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "127.0.0.1", "port": 8765, "password": "pw"},
        )

        assert argv[1] == source_cli


def test_task_launch_command_preserves_human_mode():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)

        argv, _env = server._build_ucagent_command(
            {"human": True, "launch_mode": "docker_swarm"},
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "0.0.0.0", "port": 8765, "password": "pw"},
        )

        assert "--human" in argv


def test_launch_request_env_overrides_default_env():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {
                "default_env": [
                    {"ENABLE_LLM_PASS_SUGGESTION": True},
                    {"PASS_SUGGESTION_MODEL": "default-model"},
                    "OPENAI_API_KEY",
                ],
            },
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)

        _argv, env = server._build_ucagent_command(
            {
                "env": {
                    "ENABLE_LLM_PASS_SUGGESTION": "False",
                    "PASS_SUGGESTION_MODEL": "web-model",
                },
            },
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "127.0.0.1", "port": 8765, "password": "pw"},
        )

        assert env["ENABLE_LLM_PASS_SUGGESTION"] == "False"
        assert env["PASS_SUGGESTION_MODEL"] == "web-model"


def test_launch_request_env_resolves_references_from_same_payload():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {
                "default_env": [
                    {"ENABLE_LLM_SUGGESTION": True},
                    {"ENABLE_LLM_FAIL_SUGGESTION": "$ENABLE_LLM_SUGGESTION"},
                    {"ENABLE_LLM_PASS_SUGGESTION": "$ENABLE_LLM_SUGGESTION"},
                ],
            },
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)

        _argv, env = server._build_ucagent_command(
            {
                "env": {
                    "ENABLE_LLM_SUGGESTION": "true",
                    "ENABLE_LLM_FAIL_SUGGESTION": "$ENABLE_LLM_SUGGESTION",
                    "ENABLE_LLM_PASS_SUGGESTION": "$ENABLE_LLM_SUGGESTION",
                },
            },
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "127.0.0.1", "port": 8765, "password": "pw"},
        )

        assert env["ENABLE_LLM_SUGGESTION"] == "true"
        assert env["ENABLE_LLM_FAIL_SUGGESTION"] == "true"
        assert env["ENABLE_LLM_PASS_SUGGESTION"] == "true"


def test_launch_env_preview_preserves_default_env_bool_literal_case():
    with tempfile.TemporaryDirectory() as master_ws:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(
                """
launch:
  default_env:
    - "LOWER_TRUE": true
    - "LOWER_FALSE": false
    - "TITLE_TRUE": True
    - "TITLE_FALSE": False
"""
            )
            config_path = handle.name
        try:
            cfg = Config({
                "launch": {
                    "default_env": [
                        {"LOWER_TRUE": True},
                        {"LOWER_FALSE": False},
                        {"TITLE_TRUE": True},
                        {"TITLE_FALSE": False},
                    ],
                },
            })
            object.__setattr__(cfg, "_loaded_config_files", [config_path])
            cfg.freeze()
            server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)

            preview = {item["key"]: item for item in server._launch_env_preview()}
        finally:
            os.unlink(config_path)

    assert preview["LOWER_TRUE"]["raw_literal"] == "true"
    assert preview["LOWER_FALSE"]["raw_literal"] == "false"
    assert preview["TITLE_TRUE"]["raw_literal"] == "True"
    assert preview["TITLE_FALSE"]["raw_literal"] == "False"


def test_launch_env_preview_ignores_stale_bool_literal_from_overridden_default_env():
    with tempfile.TemporaryDirectory() as master_ws:
        config_paths = []
        for content in (
            """
launch:
  default_env:
    - "ENABLED": true
""",
            """
launch:
  default_env:
    - "ENABLED": "yes"
    - "OTHER": false
""",
        ):
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
                handle.write(content)
                config_paths.append(handle.name)
        try:
            cfg = Config({
                "launch": {
                    "default_env": [
                        {"ENABLED": "yes"},
                        {"OTHER": False},
                    ],
                },
            })
            object.__setattr__(cfg, "_loaded_config_files", list(config_paths))
            cfg.freeze()
            server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)

            preview = {item["key"]: item for item in server._launch_env_preview()}
        finally:
            for config_path in config_paths:
                os.unlink(config_path)

    assert preview["ENABLED"]["raw_literal"] == ""
    assert preview["OTHER"]["raw_literal"] == "false"


def test_config_as_dict_omits_loaded_config_files_metadata():
    cfg = Config({"launch": {"default_env": []}})
    object.__setattr__(cfg, "_loaded_config_files", ["/tmp/setting.yaml"])

    assert "_loaded_config_files" not in cfg.as_dict()


def test_master_source_overrides_container_launch_cli(monkeypatch):
    with tempfile.TemporaryDirectory() as master_ws:
        source_host_path = "/host/path/UCAgent-not-visible-inside-master-container"
        monkeypatch.setenv("UCAGENT_MASTER_SOURCE", source_host_path)
        server = PdbMasterApiServer(workspace=master_ws)

        command = server._container_command(["/usr/bin/python3", "/old/ucagent/cli.py", "/work", "Adder"])

        assert command[:2] == ["python3", "/UCAgent/ucagent/cli.py"]
        assert command[2:] == ["/work", "Adder"]


def test_master_source_empty_does_not_override_container_launch(monkeypatch):
    with tempfile.TemporaryDirectory() as master_ws:
        monkeypatch.delenv("UCAGENT_MASTER_SOURCE", raising=False)
        server = PdbMasterApiServer(workspace=master_ws)

        command = server._container_command(["/usr/bin/python3", "/old/ucagent/cli.py", "/work", "Adder"])

        assert command[:3] == ["ucagent", "/work", "Adder"]


def test_docker_host_master_keeps_host_gateway_and_publishes_task_ports():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {
                "cluster": {
                    "image": "ucagent:test",
                    "master_ip": [{"docker": "host.docker.internal"}],
                    "docker_network": "ucagent_net",
                },
            },
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
        task = {"task_id": "task1", "stdout_log_path": os.path.join(master_ws, "stdout.log")}
        open(task["stdout_log_path"], "w", encoding="utf-8").close()

        with patch.object(server, "_ensure_docker_task_network") as ensure_network, \
                patch.object(server, "_current_docker_container_id", return_value=""), \
                patch.object(server, "_running_inside_container", return_value=False):
            master_host = server._prepare_docker_task_network("docker", "ucagent_net", task)

        assert master_host == ""
        ensure_network.assert_called_once_with("docker", "ucagent_net")
        assert server._workspace_archive_download_url("ws1", "docker") == "http://host.docker.internal:8800/api/workspace/ws1.tar.gz"

        argv, _env = server._build_ucagent_command(
            {"launch_mode": "docker", "use_zip_workspace": True, "task_id": "ws1"},
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "0.0.0.0", "port": 8765, "password": "pw"},
        )

        master_index = argv.index("--master")
        assert argv[master_index + 1] == "host.docker.internal:8800"
        assert server._docker_extra_args(server._launch_cluster_config())[0] == "--add-host=host.docker.internal:host-gateway"
        assert server._published_ports(
            {"enabled": True, "port": 8765},
            {"enabled": True, "port": 8818},
            {"enabled": True, "port": 8000},
            "docker",
            "",
        ) == [
            {"name": "cmd-api", "host_port": 8765, "container_port": 8765},
            {"name": "terminal-api", "host_port": 8818, "container_port": 8818},
            {"name": "web-console", "host_port": 8000, "container_port": 8000},
        ]


def test_docker_container_master_uses_configured_network_alias_for_task():
    with tempfile.TemporaryDirectory() as master_ws:
        cfg = Config({
            "launch": {
                "cluster": {
                    "image": "ucagent:test",
                    "master_ip": [{"docker": "ucagent_master"}],
                    "docker_network": "ucagent_net",
                },
            },
        }).freeze()
        server = PdbMasterApiServer(workspace=master_ws, cfg=cfg)
        task = {"task_id": "task1", "stdout_log_path": os.path.join(master_ws, "stdout.log")}
        open(task["stdout_log_path"], "w", encoding="utf-8").close()

        with patch.object(server, "_ensure_docker_task_network"), \
                patch.object(server, "_current_docker_container_id", return_value="abcdef123456"), \
                patch.object(server, "_docker_container_networks", return_value=({"ucagent_net": {"Aliases": ["ucagent_master"]}}, "")):
            master_host = server._prepare_docker_task_network("docker", "ucagent_net", task)

        assert master_host == "ucagent_master"
        assert server._workspace_archive_download_url("ws1", "docker", master_host) == "http://ucagent_master:8800/api/workspace/ws1.tar.gz"

        argv, _env = server._build_ucagent_command(
            {"launch_mode": "docker", "use_zip_workspace": True, "task_id": "ws1"},
            {"workspace_dir": master_ws, "picker_workspace": master_ws, "dut_name": "Adder"},
            {"host": "0.0.0.0", "port": 8765, "password": "pw"},
            master_host,
        )

        master_index = argv.index("--master")
        assert argv[master_index + 1] == "ucagent_master:8800"
        assert argv[2] == "http://ucagent_master:8800/api/workspace/ws1.tar.gz"
        assert server._published_ports(
            {"enabled": True, "port": 8765},
            {"enabled": True, "port": 8818},
            {"enabled": True, "port": 8000},
            "docker",
            master_host,
        ) == []


def test_swarm_task_cmd_proxy_uses_service_dns_over_agent_task_ip():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_name": "swarm",
                "launch_mode": "docker_swarm",
                "cmd_api": {
                    "enabled": True,
                    "status": "running",
                    "port": 8765,
                    "password": "pw",
                    "base_url_internal": "http://127.0.0.1:8765",
                },
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        task["cluster"] = {"mode": "docker_swarm", "name": "ucagent-test-task"}
        task["client_id"] = "agent-1"

        changed = server._merge_task_agent_runtime_info(task, {"id": "agent-1", "cmd_api_tcp": "http://10.0.1.109:8765"})

        assert changed
        assert task["cmd_api"]["tcp_url"] == "http://10.0.1.109:8765"
        assert task["cmd_api"]["base_url_internal"] == "http://127.0.0.1:8765"
        assert server._cmd_proxy_url(task, "api/status") == "http://ucagent-test-task:8765/api/status"


def test_swarm_task_finish_keeps_service_for_debug_logs():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_id": "task-finished",
                "task_name": "swarm",
                "launch_mode": "docker_swarm",
                "cmd_api": {"enabled": True, "status": "starting", "port": 8765},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        task["cluster"] = {"mode": "docker_swarm", "name": "ucagent-task-finished"}
        task["process_status"] = "running"
        task["started_at"] = time.time() - 30

        with patch.object(server, "_cluster_alive_status", return_value=(False, 0, "complete")), \
                patch.object(server, "_probe_child_service", return_value=False), \
                patch.object(server, "_docker_swarm_task_detail", return_value="Complete 1 second ago"), \
                patch.object(server, "_remove_docker_swarm_service") as remove_service:
            server._refresh_task_states()

        assert task["process_status"] == "stopped"
        assert task["exit_code"] == 0
        remove_service.assert_not_called()


def test_swarm_launch_removes_exited_same_name_service_before_create():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_id": "task-relaunch",
                "task_name": "swarm",
                "launch_mode": "docker_swarm",
                "cmd_api": {"enabled": True, "status": "starting", "port": 8765},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        task["resolved_command"] = ["python3", "ucagent/cli.py", "/work", "Adder"]
        events = []

        def fake_context(_task, _env, _prepared, _mode):
            return {
                "cfg": {"image": "ucagent:test", "swarm_extra_args": []},
                "name": "ucagent-task-relaunch",
                "env": {},
                "mounts": [],
                "network": "",
                "picker_workspace": "/tmp",
                "command": ["ucagent", "/work", "Adder"],
            }

        def fake_state(name):
            events.append(f"state:{name}")
            return {"exists": True, "active": False, "exited": True, "detail": "Complete 2 minutes ago"}

        def fake_remove(name, task=None, reason=""):
            events.append(f"rm:{name}:{reason}")
            return True

        def fake_run(cmd, timeout=10.0):
            events.append(cmd[:3])
            return 0, "service-id\n", ""

        with patch.object(server, "_cluster_launch_context", side_effect=fake_context), \
                patch.object(server, "_docker_cli_available", return_value=True), \
                patch.object(server, "_docker_swarm_service_state", side_effect=fake_state), \
                patch.object(server, "_remove_docker_swarm_service", side_effect=fake_remove), \
                patch.object(server, "_run_control_command", side_effect=fake_run), \
                patch.object(server, "_start_external_log_capture"):
            cluster = server._start_task_docker_swarm(
                task,
                {},
                {"workspace_dir": master_ws, "picker_workspace": master_ws, "use_zip_workspace": False},
                {"enabled": True, "port": 8765},
                {"enabled": False},
                {"enabled": False},
            )

        assert events[0] == "state:ucagent-task-relaunch"
        assert events[1] == "rm:ucagent-task-relaunch:exited service before relaunch"
        assert events[2] == ["docker", "service", "create"]
        assert cluster["name"] == "ucagent-task-relaunch"
        assert cluster["id"] == "service-id"


def test_swarm_launch_rejects_active_same_name_service():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_id": "task-active",
                "task_name": "swarm",
                "launch_mode": "docker_swarm",
                "cmd_api": {"enabled": True, "status": "starting", "port": 8765},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        task["resolved_command"] = ["python3", "ucagent/cli.py", "/work", "Adder"]

        with patch.object(server, "_cluster_launch_context", return_value={
                "cfg": {"image": "ucagent:test", "swarm_extra_args": []},
                "name": "ucagent-task-active",
                "env": {},
                "mounts": [],
                "network": "",
                "picker_workspace": "/tmp",
                "command": ["ucagent", "/work", "Adder"],
            }), \
                patch.object(server, "_docker_swarm_service_state", return_value={
                    "exists": True,
                    "active": True,
                    "exited": False,
                    "detail": "Running 10 seconds ago",
                }), \
                patch.object(server, "_run_control_command") as run_command:
            try:
                server._start_task_docker_swarm(
                    task,
                    {},
                    {"workspace_dir": master_ws, "picker_workspace": master_ws, "use_zip_workspace": False},
                    {"enabled": True, "port": 8765},
                    {"enabled": False},
                    {"enabled": False},
                )
            except ValueError as exc:
                assert "still active" in str(exc)
            else:
                raise AssertionError("Expected active Swarm service to block launch")

        run_command.assert_not_called()


def test_cleanup_stale_swarm_services_deletes_old_or_untracked_exited_services():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        now = time.time()
        old_task = server._create_task_record({"task_id": "old"})
        old_task["process_status"] = "stopped"
        old_task["finished_at"] = now - 3700
        recent_task = server._create_task_record({"task_id": "recent"})
        recent_task["process_status"] = "stopped"
        recent_task["finished_at"] = now - 120
        removed = []

        with patch.object(server, "_docker_swarm_local_state", return_value="active"), \
                patch.object(server, "_list_ucagent_swarm_services", return_value=[
                    {"name": "ucagent-old"},
                    {"name": "ucagent-recent"},
                    {"name": "ucagent-untracked"},
                ]), \
                patch.object(server, "_docker_swarm_service_state", return_value={
                    "exists": True,
                    "active": False,
                    "exited": True,
                    "detail": "Complete 2 hours ago",
                    "last_status_at": now - 7200,
                }), \
                patch.object(server, "_remove_docker_swarm_service", side_effect=lambda name: removed.append(name) or True):
            cleaned = server._cleanup_stale_swarm_services()

        assert cleaned == 2
        assert removed == ["ucagent-old", "ucagent-untracked"]


def test_relaunch_drops_finished_old_task_record_before_launch():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        client = TestClient(server._app)
        ws = server._create_workspace()
        workspace_id = ws["workspace_id"]
        picker_workspace = ws["picker_workspace"]
        os.makedirs(picker_workspace, exist_ok=True)
        with server._workspaces_lock:
            ws_locked = server._workspaces[workspace_id]
            ws_locked["compile"] = {
                "status": "success",
                "picker_workspace": picker_workspace,
                "dut_name": "Adder",
                "selected_module": "Adder",
                "main_verilog_path": os.path.join(picker_workspace, "Adder.v"),
                "compiled_main_verilog_path": os.path.join(picker_workspace, "Adder.v"),
                "picker_extra_args": [],
            }
        old_task = server._create_task_record(
            {
                "task_id": ws["task_id"],
                "workspace_id": workspace_id,
                "launch_mode": "docker_swarm",
                "cmd_api": {"enabled": True, "status": "stopped"},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        old_task["process_status"] = "stopped"
        old_task["finished_at"] = time.time() - 30
        old_task["cluster"] = {"mode": "docker_swarm", "name": f"ucagent-{old_task['task_id']}"}

        launched = []

        def fake_run_launch(req):
            launched.append(dict(req))
            return server._create_task_record(
                {
                    "task_id": req["task_id"],
                    "workspace_id": req["workspace_id"],
                    "launch_mode": "docker_swarm",
                    "cmd_api": {"enabled": True, "status": "starting"},
                    "terminal_api": {"enabled": False, "status": "stopped"},
                    "web_console": {"enabled": False, "status": "stopped"},
                }
            )

        with patch.object(server, "_run_task_launch", side_effect=fake_run_launch):
            response = client.post("/api/relaunch", json={"task_id": old_task["task_id"]})

        assert response.status_code == 200
        assert launched[0]["task_id"] == old_task["task_id"]
        assert server._tasks[old_task["task_id"]]["process_status"] == "pending"


def test_relaunch_ucagent_info_preserves_requested_zip_workspace():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        client = TestClient(server._app)
        ws = server._create_workspace()
        workspace_id = ws["workspace_id"]
        picker_workspace = ws["picker_workspace"]
        os.makedirs(os.path.join(picker_workspace, ".ucagent"), exist_ok=True)
        with open(os.path.join(picker_workspace, ".ucagent", "ucagent_info.json"), "w", encoding="utf-8") as fh:
            json.dump({"dut_name": "Adder", "selected_module": "Adder"}, fh)

        old_task = server._create_task_record(
            {
                "task_id": ws["task_id"],
                "workspace_id": workspace_id,
                "cmd_api": {"enabled": True, "status": "stopped"},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        old_task["process_status"] = "stopped"
        old_task["finished_at"] = time.time() - 30
        launched = []

        def fake_run_launch(req):
            launched.append(dict(req))
            return server._create_task_record(
                {
                    "task_id": req["task_id"],
                    "workspace_id": req["workspace_id"],
                    "cmd_api": {"enabled": True, "status": "starting"},
                    "terminal_api": {"enabled": False, "status": "stopped"},
                    "web_console": {"enabled": False, "status": "stopped"},
                }
            )

        with patch.object(server, "_run_task_launch", side_effect=fake_run_launch):
            response = client.post("/api/relaunch", json={"task_id": old_task["task_id"], "use_zip_workspace": True})

        assert response.status_code == 200
        assert launched[0]["_relaunch_from_ucagent_info"] is True
        assert launched[0]["use_zip_workspace"] is True


def test_process_task_cmd_proxy_can_use_agent_reported_tcp_url():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_name": "process",
                "launch_mode": "process",
                "cmd_api": {
                    "enabled": True,
                    "status": "running",
                    "port": 8765,
                    "password": "pw",
                    "base_url_internal": "http://127.0.0.1:8765",
                },
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )

        server._merge_task_agent_runtime_info(task, {"cmd_api_tcp": "http://10.0.1.109:8765"})

        assert task["cmd_api"]["base_url_internal"] == "http://10.0.1.109:8765"
        assert server._cmd_proxy_url(task, "api/status") == "http://10.0.1.109:8765/api/status"


def test_master_task_log_capture_drains_fast_failed_process():
    with tempfile.TemporaryDirectory() as master_ws, tempfile.TemporaryDirectory() as task_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_name": "fast-fail",
                "workspace_dir": task_ws,
                "cmd_api": {"enabled": True, "status": "starting"},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": False, "status": "stopped"},
            }
        )
        task["resolved_command"] = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "print('stdout before'); "
                "print('Traceback (most recent call last):', file=sys.stderr); "
                "print('RuntimeError: master task boom', file=sys.stderr); "
                "sys.exit(7)"
            ),
        ]

        proc = server._start_task_process(task, os.environ.copy())
        proc.wait(timeout=5)
        server._drain_finished_task_runtime(task)

        assert task["process_status"] == "failed"
        assert task["exit_code"] == 7
        assert "stdout before" in _tail_file(task["stdout_log_path"])
        stderr = _tail_file(task["stderr_log_path"])
        assert "Traceback (most recent call last)" in stderr
        assert "RuntimeError: master task boom" in stderr


def test_master_task_logs_include_web_console_capture_only_for_exception():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_name": "web-console-fail",
                "cmd_api": {"enabled": True, "status": "stopped"},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": True, "status": "stopped"},
            }
        )
        with open(task["stderr_log_path"], "w", encoding="utf-8") as fh:
            fh.write("outer stderr\n")
        with open(task["web_console_log_path"], "w", encoding="utf-8") as fh:
            fh.write("Traceback (most recent call last):\n")
            fh.write("ValueError: web console inner failure\n")

        merged = _task_stderr_tail(task)

        assert "outer stderr" in merged
        assert "Traceback (most recent call last)" in merged
        assert "ValueError: web console inner failure" in merged

        with open(task["web_console_log_path"], "w", encoding="utf-8") as fh:
            fh.write("normal web console line\n")

        normal = _task_stderr_tail(task)
        assert "outer stderr" in normal
        assert "normal web console line" not in normal


def test_master_task_logs_show_normal_outer_logs_without_web_console_noise():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        task = server._create_task_record(
            {
                "task_name": "running",
                "cmd_api": {"enabled": True, "status": "running"},
                "terminal_api": {"enabled": False, "status": "stopped"},
                "web_console": {"enabled": True, "status": "running"},
            }
        )
        task["process_status"] = "running"
        task["exit_code"] = None
        with open(task["stdout_log_path"], "w", encoding="utf-8") as fh:
            fh.write("normal stdout\n")
        with open(task["stderr_log_path"], "w", encoding="utf-8") as fh:
            fh.write("normal stderr\n")
        with open(task["web_console_log_path"], "w", encoding="utf-8") as fh:
            fh.write("normal web console\n")

        logs = _task_logs_for_display(task)
        assert "normal stdout" in logs["stdout"]
        assert "normal stderr" in logs["stderr"]
        assert "normal web console" not in logs["stderr"]


def test_relaunch_ucagent_info_switches_between_config_backups():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        ws = server._create_workspace()
        workspace_id = ws["workspace_id"]
        picker_workspace = ws["picker_workspace"]
        info_dir = os.path.join(picker_workspace, ".ucagent")
        info_path = os.path.join(info_dir, "ucagent_info.json")
        os.makedirs(info_dir, exist_ok=True)

        with server._workspaces_lock:
            ws_locked = server._workspaces[workspace_id]
            ws_locked["compile"] = {
                "status": "success",
                "picker_workspace": picker_workspace,
                "dut_name": "Adder",
                "selected_module": "Adder",
            }

        with open(info_path, "w", encoding="utf-8") as fh:
            json.dump({"config_file": "config_a.yaml", "stage_index": 3, "a_state": True}, fh)

        switch_to_b = server._clear_relaunch_ucagent_info(
            workspace_id=workspace_id,
            target_config="/tmp/anywhere/config_b.yaml",
        )

        assert switch_to_b["backed_up"] is True
        assert switch_to_b["initialized"] is True
        assert os.path.isfile(switch_to_b["backup_path"])
        assert os.path.basename(switch_to_b["backup_path"]).startswith("ucagent_info_config_a.yaml_")
        with open(switch_to_b["backup_path"], "r", encoding="utf-8") as fh:
            assert json.load(fh)["stage_index"] == 3
        with open(info_path, "r", encoding="utf-8") as fh:
            current = json.load(fh)
        assert current["config_file"] == "/tmp/anywhere/config_b.yaml"
        assert "stage_index" not in current

        with open(info_path, "w", encoding="utf-8") as fh:
            json.dump({"config_file": "config_b.yaml", "stage_index": 7, "b_state": True}, fh)

        switch_to_a = server._clear_relaunch_ucagent_info(
            workspace_id=workspace_id,
            target_config="config_a.yaml",
        )

        assert switch_to_a["backed_up"] is True
        assert switch_to_a["restored"] is True
        assert os.path.isfile(switch_to_a["backup_path"])
        assert os.path.basename(switch_to_a["backup_path"]).startswith("ucagent_info_config_b.yaml_")
        with open(switch_to_a["backup_path"], "r", encoding="utf-8") as fh:
            assert json.load(fh)["stage_index"] == 7
        with open(info_path, "r", encoding="utf-8") as fh:
            assert json.load(fh)["stage_index"] == 3

        switch_back_to_b = server._clear_relaunch_ucagent_info(
            workspace_id=workspace_id,
            target_config="config_b.yaml",
        )

        assert switch_back_to_b["restored"] is True
        with open(info_path, "r", encoding="utf-8") as fh:
            restored_b = json.load(fh)
        assert restored_b["stage_index"] == 7
        assert restored_b["b_state"] is True


def test_agent_list_keeps_cached_launch_task_id_after_task_record_delete():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        client = TestClient(server._app)

        register = client.post("/api/register", json={"id": "agent-1", "host": "worker-1"})
        assert register.status_code == 200

        task = server._create_task_record({"task_id": "task-1", "client_id": "agent-1"})
        task["process_status"] = "stopped"

        removed = client.delete("/api/task/task-1")
        assert removed.status_code == 200

        response = client.get("/api/agents")
        assert response.status_code == 200
        agents = response.json()["agents"]
        agent = next(item for item in agents if item["id"] == "agent-1")
        assert agent["launch"] is True
        assert agent["launch_task_exists"] is False
        assert agent["launch_task_id"] == "task-1"


def test_agent_delete_block_rejoin_controls_removed_set():
    with tempfile.TemporaryDirectory() as master_ws:
        server = PdbMasterApiServer(workspace=master_ws)
        client = TestClient(server._app)

        assert client.post("/api/register", json={"id": "offline-agent", "host": "worker-1"}).status_code == 200
        delete_stale = client.delete("/api/agent/offline-agent?block_rejoin=false")
        assert delete_stale.status_code == 200
        assert "offline-agent" not in server._removed

        assert client.post("/api/register", json={"id": "online-agent", "host": "worker-2"}).status_code == 200
        unregister = client.delete("/api/agent/online-agent?block_rejoin=true")
        assert unregister.status_code == 200
        assert "online-agent" in server._removed
