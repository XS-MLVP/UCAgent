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
