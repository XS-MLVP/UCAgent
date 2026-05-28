import os
import sys
import tempfile

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
