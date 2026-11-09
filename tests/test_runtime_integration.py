"""Cross-entrypoint contention, shutdown admission, instance isolation and real Master lifetime."""

from ucagent.interfaces.terminal.presentation import format_result, format_operation
import json
from pathlib import Path
import socket
import subprocess
import time
import threading
from unittest.mock import Mock

from fastapi.testclient import TestClient
import httpx
import pytest

from test_runtime_host import make_host
from test_runtime_cli import cli_command, ROOT
from ucagent.runtime.session import RuntimeSession
from ucagent.runtime.control.controller import ControlError
from ucagent.interfaces.server.api_cmd import ControlApiServer


def test_console_and_http_share_model_slot_and_keep_queries_responsive(tmp_path):
    """A model waiting in Console rejects HTTP competitors while status and cancellation work."""
    host, runtime = make_host(tmp_path)
    runtime.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    console = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
    server = ControlApiServer(host.controller, registry=host.registry, operations=host.operations,
                              services=host.services, host_control=host, sock="")
    entered, release = threading.Event(), threading.Event()

    def blocked():
        """Represent a model call that cannot be interrupted until its transport returns."""
        entered.set()
        assert release.wait(3)

    runtime.agent.round_hook = blocked
    host.attach_control("test")
    host.start()
    try:
        operation = console.execute_line("nr").data
        assert entered.wait(1)
        with TestClient(server._app) as client:
            assert client.post("/api/cmd", json={"cmd": "nr"}).status_code == 409
            assert client.get("/api/status").status_code == 200
            assert client.post(f"/api/operations/{operation['id']}/cancel").status_code == 200
            assert host.operations.get(operation["id"])["state"] == "cancelling"
            assert client.get("/api/runtime/status").status_code == 200
        release.set()
        assert host.operations.wait(operation["id"], 2)["state"] == "cancelled"
    finally:
        release.set()
        server.stop()
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


def test_shutdown_rejects_new_services_before_current_call_returns(tmp_path):
    """Closing stops all admission immediately, retaining the blocked operation until it returns."""
    host, runtime = make_host(tmp_path, shutdown_timeout=0.01)
    entered, release = threading.Event(), threading.Event()

    def blocked(context):
        """Hold an uninterruptible call while shutdown admission is checked."""
        entered.set()
        assert release.wait(3)

    host.start()
    operation = host.operations.submit("blocked", blocked, model=True)
    assert entered.wait(1)
    try:
        host.request_shutdown()
        factory = Mock(side_effect=AssertionError("Late service must not be constructed"))
        with pytest.raises(ControlError, match="closing"):
            host.services.start("late", factory)
        factory.assert_not_called()
        assert host.wait(0.05)["instance"] == "closing"
    finally:
        release.set()
        assert host.wait(3)["instance"] == "closed"


def test_failed_sync_result_does_not_skip_cleanup_or_report_success(tmp_path):
    """Structured failures have the same close outcome as exceptions, without skipping restoration."""
    host, runtime = make_host(tmp_path)
    restored = []
    host.services.sync_workspace_back = lambda **kwargs: [{"ok": False, "url": "http://master", "message": "upload failed"}]
    host.add_cleanup(lambda: restored.append(True))
    host.start()
    host.request_shutdown()
    result = host.wait(3)
    assert result["instance"] == "failed" and result["exit_code"] != 0, result
    assert result["errors"][0]["step"] == "sync"
    assert restored == [True]


def test_instances_cannot_query_or_cancel_each_others_operations(tmp_path):
    """An operation ID belongs to exactly one host and survives another host's shutdown."""
    one, _ = make_host(tmp_path / "one")
    two, _ = make_host(tmp_path / "two")
    one.start()
    two.start()
    operation = two.operations.submit("sleep", lambda context: context.wait(10))
    try:
        with pytest.raises(ControlError):
            one.controller.cancel_operation(operation["id"])
        one.request_shutdown()
        assert one.wait(3)["instance"] == "closed"
        assert two.operations.get(operation["id"])["state"] == "running"
    finally:
        two.request_shutdown()
        assert two.wait(3)["instance"] == "closed"


def test_real_master_stays_alive_without_model_and_shuts_down_via_http(tmp_path):
    """BlankBackend Master remains available with no stdin and rejects model commands."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = cli_command(tmp_path, backend="blank") + ["--as-master", "127.0.0.1:0", "--export-cmd-api", f"127.0.0.1:{port}"]
    logfile = tmp_path / "master.log"
    with logfile.open("w") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                deadline = time.monotonic() + 12
                while True:
                    assert process.poll() is None and time.monotonic() < deadline, logfile.read_text()
                    try:
                        if client.get("/api/runtime/status").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.05)
                assert client.post("/api/cmd", json={"cmd": "nr"}).status_code == 400
                assert client.get("/api/runtime/status").json()["data"]["instance"] == "ready"
                assert client.post("/api/cmd", json={"cmd": "quit"}).status_code == 200
            process.wait(timeout=10)
            assert process.returncode == 0, logfile.read_text()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_force_exit_requires_explicit_process_owned_action(tmp_path):
    """Ordinary quit drains; only an explicit force argument calls process termination."""
    called = []
    host, runtime = make_host(tmp_path, force_exit=called.append)
    host.start()
    host.registry.execute("q force", runtime.session)
    assert called == [130]
    result = host.wait(3)
    assert result["close_reason"] == "forced_exit"


def test_owned_operation_output_does_not_leak_between_instances(tmp_path):
    """Concurrent runtime owners share stream plumbing but route operation output by context."""
    one, _ = make_host(tmp_path / "one")
    two, _ = make_host(tmp_path / "two")
    one.output.install()
    two.output.install()
    try:
        operation = one.operations.submit("print", lambda context: print("owned-output-token"))
        assert one.operations.wait(operation["id"], 2)["state"] == "succeeded"
        assert any("owned-output-token" in line for line in one.output.get_lines())
        assert not any("owned-output-token" in line for line in two.output.get_lines())
    finally:
        one.output.close()
        two.output.close()
        one.operations.close(2)
        two.operations.close(2)


def test_external_stage_thread_receives_model_cancellation(tmp_path):
    """A stage tool on another thread passes cancellation to its actual child process."""
    from concurrent.futures import ThreadPoolExecutor
    from ucagent.util.functions import run_shell_process
    host, runtime = make_host(tmp_path)
    started, finished = threading.Event(), threading.Event()

    def model(context):
        """Wait as an external model transport would for its MCP tool response."""
        assert finished.wait(4)

    def check(**kwargs):
        """Exercise the ordinary process runner inside the real coordinated Check path."""
        result = run_shell_process(tmp_path, "printf ready; sleep 30",
                                   lambda stream, text: started.set(), idle_timeout=0)
        return result["reason"] != "cancelled", result["reason"]

    runtime.gate.do_check = check
    operation = host.operations.submit("model", model, model=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        tool = pool.submit(runtime.manager.check, 2)
        try:
            assert started.wait(2)
            host.operations.cancel(operation["id"])
            result = tool.result(timeout=3)
            assert result["check_pass"] is False
        finally:
            finished.set()
    assert host.operations.wait(operation["id"], 2)["state"] == "cancelled"
    assert host.operations.close(2)["closed"]


def test_remote_client_can_query_and_cancel_a_real_http_operation(tmp_path):
    """The shipped client and real control listener use the same operation protocol."""
    import sys
    host, runtime = make_host(tmp_path)
    runtime.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    server = ControlApiServer(host.controller, registry=host.registry, operations=host.operations,
                             services=host.services, host_control=host, host="127.0.0.1", port=0, sock="")
    assert host.services.start("cmd", lambda: server)["ok"]
    host.start()
    script = ROOT / "ucagent/scripts/ucagent-client/scripts/ucagent_client.py"

    def client(command, *arguments):
        """Exercise argparse and actual HTTP transport in a separate process."""
        result = subprocess.run([sys.executable, str(script), command, "--url", server.url(), *arguments],
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    try:
        operation = client("cmd", "sleep", "30")["operation_id"]
        assert client("operation", operation)["data"]["state"] == "running"
        client("cancel", operation)
        assert host.operations.wait(operation, 2)["state"] == "cancelled"
    finally:
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


def test_closing_rejects_synchronous_mutations_but_keeps_queries(tmp_path):
    """Shutdown admission also covers direct control handlers outside operation workers."""
    host, runtime = make_host(tmp_path, shutdown_timeout=0.01)
    entered, release = threading.Event(), threading.Event()

    def blocked(context):
        """Keep the instance in closing long enough to exercise synchronous HTTP-style controls."""
        entered.set()
        assert release.wait(3)

    runtime.agent.set_system_message = Mock()
    host.start()
    host.operations.submit("blocked", blocked, model=True)
    assert entered.wait(1)
    try:
        host.request_shutdown()
        with pytest.raises(ControlError) as error:
            host.registry.execute("set_sys_tips changed", runtime.session)
        assert error.value.code == "closing"
        runtime.agent.set_system_message.assert_not_called()
        assert host.registry.execute("status", runtime.session).data["invoke_round"] == 0
    finally:
        release.set()
        assert host.wait(3)["instance"] == "closed"


def test_external_process_calls_real_mcp_check_complete_and_exit(tmp_path):
    """A separate tool client traverses real gates and receives Exit before owned shutdown."""
    import sys
    from ucagent.interfaces.server.api_mcp import McpServer
    from ucagent.core.stage.vmanager import ToolDoCheck, ToolDoComplete, ToolDoExit, ToolSetCurrentStageJournal

    host, runtime = make_host(tmp_path, exit_on_completion=True)
    runtime.agent.cfg.set_value("mcp_server", {"init_prompt": "External lifecycle test"})
    runtime.agent.cfg.set_value("master_api.sync_workspace.on_stage_complete", False)
    runtime.control.review_stage(0, runtime.manager.control_revision, True, "Review accepted")
    tools = [ToolDoCheck().set_function(runtime.manager.tool_check),
             ToolDoComplete().set_function(runtime.manager.tool_complete),
             ToolSetCurrentStageJournal().set_function(runtime.manager.tool_set_journal),
             ToolDoExit().set_function(runtime.manager.tool_exit)]
    server = McpServer(tools, cfg=runtime.agent.cfg, host="127.0.0.1", port=0)
    assert host.services.start("mcp", lambda: server)["ok"]
    host.start()
    source = '''
import asyncio
import sys
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def run():
    async with streamable_http_client(sys.argv[1], terminate_on_close=False) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            await session.list_tools()
            for index in range(3):
                response = await session.call_tool("SetCurrentStageJournal", {"journal": "Verified evidence"})
                assert not response.is_error, response
                response = await session.call_tool("Check", {"timeout": 2})
                assert yaml.safe_load(response.content[0].text)["check_pass"], response
                response = await session.call_tool("Complete", {"timeout": 2})
                assert yaml.safe_load(response.content[0].text)["complete"], response
            response = await session.call_tool("Exit", {})
            assert yaml.safe_load(response.content[0].text)["exit"], response
            print("EXIT_RESPONSE_RECEIVED")
asyncio.run(run())
'''
    try:
        result = subprocess.run([sys.executable, "-c", source, server.url() + "/mcp"],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "EXIT_RESPONSE_RECEIVED" in result.stdout
        assert host.wait(3)["instance"] == "closed"
        assert host.snapshot()["task_outcome"] == "completed"
    finally:
        host.request_shutdown()
        host.wait(3)
