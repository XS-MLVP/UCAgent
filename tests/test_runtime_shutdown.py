"""Real HTTP shutdown responses, cooperative pending work and isolated cleanup failures."""

import threading
from unittest.mock import Mock

from fastapi import FastAPI
import httpx
import pytest

from test_runtime_host import make_host
from ucagent.control.controller import ControlError
from ucagent.server.api_master import MasterApiServer


def test_pending_operation_retains_closing_state_until_actual_return(tmp_path):
    """An uninterruptible call cannot release its slot or allow premature persistence."""
    host, runtime = make_host(tmp_path, shutdown_timeout=0.01)
    entered, release = threading.Event(), threading.Event()

    def blocked(context):
        """Hold a model transport until explicitly released by the test."""
        entered.set()
        assert release.wait(3)

    host.start()
    op = host.operations.submit("blocked", blocked, model=True)
    assert entered.wait(1)
    try:
        host.request_shutdown("quit")
        assert host.wait(0.05)["instance"] == "closing"
        assert host.operations.get(op["id"])["state"] == "cancelling"
        with pytest.raises(ControlError):
            host.operations.submit("extra", lambda context: None)
    finally:
        release.set()
    assert host.wait(3)["instance"] == "closed"
    assert host.operations.get(op["id"])["state"] == "cancelled"


def test_shutdown_request_returns_http_response_before_listener_cleanup(tmp_path):
    """The HTTP request only posts shutdown; the host drains its listener independently."""
    host, runtime = make_host(tmp_path)
    runtime.agent.cfg.set_value("launch", {"file_browser_roots": [str(tmp_path)], "default_args": {"use_zip_workspace": True}})
    server = MasterApiServer(workspace=str(tmp_path), cfg=runtime.agent.cfg, host="127.0.0.1", port=0, sock="")
    app = FastAPI()

    @app.post("/close")
    def close():
        """Return the accepted request before the server terminates."""
        host.request_shutdown("http")
        return {"accepted": True}

    server._app = app
    assert host.services.start("test-http", lambda: server)["ok"]
    host.start()
    response = httpx.post(server.url() + "/close", timeout=3)
    assert response.status_code == 200 and response.json() == {"accepted": True}
    assert host.wait(3)["instance"] == "closed"
    assert not server.is_running


def test_cleanup_failures_do_not_skip_other_steps_and_repeated_close_is_idempotent(tmp_path):
    """Save, sync and notification failures are reported while later cleanup still occurs."""
    host, runtime = make_host(tmp_path)
    events = []
    runtime.manager.save_stage_info = Mock(side_effect=OSError("save failed"))
    host.services.sync_workspace_back = Mock(side_effect=OSError("sync failed"))
    host.services.notify_exit = Mock(side_effect=OSError("notify failed"))
    host.add_cleanup(lambda: events.append("restored"))
    host.start()
    host.request_shutdown()
    host.request_shutdown()
    result = host.wait(3)
    assert result["instance"] == "failed" and result["exit_code"] == 1
    assert [error["step"] for error in result["errors"]] == ["save", "sync", "notify"]
    assert events == ["restored"]
    runtime.manager.save_stage_info.assert_called_once()
    host.services.sync_workspace_back.assert_called_once()
    host.services.notify_exit.assert_called_once()


def test_real_mcp_exit_returns_result_before_host_stops_server(tmp_path):
    """Approved evidence passes Complete before a real MCP Exit request closes the instance."""
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from ucagent.server.api_mcp import McpServer
    from ucagent.stage.vmanager import ToolDoExit

    host, runtime = make_host(tmp_path, exit_on_completion=True)
    runtime.agent.cfg.set_value("mcp_server", {"init_prompt": "Host lifecycle test"})
    runtime.agent.cfg.set_value("master_api.sync_workspace.on_stage_complete", False)
    host.attach_control("test-review")
    host.start()
    assert runtime.manager.exit()["exit"] is False
    runtime.control.review_stage(0, runtime.manager.control_revision, True, "Evidence reviewed")
    for index in range(3):
        runtime.manager.set_current_stage_journal("Verified stage evidence")
        result = runtime.manager.complete(1)
        assert result["complete"], result
    tool = ToolDoExit().set_function(runtime.manager.tool_exit)
    server = McpServer([tool], cfg=runtime.agent.cfg, host="127.0.0.1", port=0)
    assert host.services.start("mcp", lambda: server)["ok"]

    async def call_exit():
        """Use the real MCP initialization and tool protocol over loopback TCP."""
        async with streamable_http_client(server.url() + "/mcp", terminate_on_close=False) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                await session.list_tools()
                response = await session.call_tool("Exit", {})
                assert not response.is_error, response
                assert "exit: true" in response.content[0].text.lower()

    try:
        asyncio.run(call_exit())
        assert host.wait(3)["instance"] == "closed", host.snapshot()
        assert host.snapshot()["task_outcome"] == "completed"
        assert not server.is_running
    finally:
        host.request_shutdown()
        host.wait(3)
