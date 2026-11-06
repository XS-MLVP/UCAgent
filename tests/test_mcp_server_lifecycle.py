"""Regression tests for readiness-aware MCP server lifecycle management."""

import asyncio
from contextlib import asynccontextmanager
import logging
import socket
import threading
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

import httpx
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ucagent.server.api_mcp import McpServer
from ucagent.util.config import Config
from ucagent.control.controller import Controller


def _available_port() -> int:
    """Reserve and release a loopback port for a lifecycle test."""

    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _mcp_options(*, file_tools=None, plugin_tools=None, logger=None):
    """Supply explicit tool, configuration and log dependencies without a debugger."""
    return {"tools": list(plugin_tools or []) + list(file_tools or []),
            "cfg": Config({"mcp_server": {"init_prompt": "lifecycle test"}, "tools": {}}),
            "logger": logger}


def test_mcp_start_waits_until_http_endpoint_is_reachable():
    """Successful start means uvicorn has completed application startup."""

    port = _available_port()
    server = McpServer(
        **_mcp_options(),
        host="127.0.0.1",
        port=port,
        no_file_ops=True,
    )
    try:
        ok, message = server.start(timeout=5.0)

        assert ok is True, message
        assert server.is_running is True
        try:
            urlopen(f"http://127.0.0.1:{port}/mcp", timeout=1.0)
        except HTTPError as exc:
            assert exc.code in {400, 405, 406}
    finally:
        if server.is_running:
            server.stop()


def test_mcp_start_reports_occupied_port_before_model_work():
    """A bind failure must be returned synchronously instead of looking ready."""

    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    port = int(occupied.getsockname()[1])
    try:
        server = McpServer(
            **_mcp_options(),
            host="127.0.0.1",
            port=port,
            no_file_ops=True,
        )
        started_at = time.monotonic()
        ok, message = server.start(timeout=2.0)

        assert ok is False
        assert "failed to start" in message.lower()
        assert time.monotonic() - started_at < 2.0
        assert server.is_running is False
    finally:
        occupied.close()


@asynccontextmanager
async def _connected_client(server):
    """Keep a real MCP notification stream open until its server drains it."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            server.url() + "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "shutdown-test", "version": "1"},
            }},
        )
        assert response.status_code == 200, response.text
        headers = {
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": response.headers["mcp-session-id"],
            "MCP-Protocol-Version": "2025-11-25",
        }
        initialized = await client.post(
            server.url() + "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert initialized.status_code == 202
        async with client.stream("GET", server.url() + "/mcp", headers=headers) as stream:
            assert stream.status_code == 200
            yield client, headers, stream


def test_stop_drains_connected_stream_and_allows_restart(caplog):
    """A live client observes clean EOF before stop succeeds, including after restart."""
    server = McpServer(**_mcp_options(), port=_available_port())

    async def exercise():
        """Keep the client open during both shutdowns on the same listening port."""
        for _ in range(2):
            ok, message = server.start(timeout=3)
            assert ok, message
            native, thread = server._server, server._thread
            native.config.timeout_graceful_shutdown = 0.75
            try:
                async with _connected_client(server) as (_, _, stream):
                    began = time.monotonic()
                    ok, message = await asyncio.to_thread(server.stop)
                    assert ok, message
                    assert time.monotonic() - began < 2
                    assert not thread.is_alive()
                    assert await stream.aread() == b""
                    assert server._server is None
                    assert server._server is None
            finally:
                if server.is_running:
                    server.stop(timeout=2)
    asyncio.run(exercise())
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_stop_is_isolated_from_another_connected_server(caplog):
    """Draining one instance never changes global SSE state or a peer's stream."""
    from sse_starlette.sse import AppStatus

    first = McpServer(**_mcp_options(), port=_available_port())
    second = McpServer(**_mcp_options(), port=_available_port())
    before = AppStatus.should_exit

    async def exercise():
        """Verify the second stream and session still work after the first closes."""
        async with _connected_client(first), _connected_client(second) as (client, headers, stream):
            peer = second._server
            ok, message = await asyncio.to_thread(first.stop)
            assert ok, message
            assert AppStatus.should_exit == before
            assert second.is_running and not second.is_stopping
            assert len(peer._mcp_app._streams) == 1
            ping = await client.post(
                second.url() + "/mcp", headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            )
            assert ping.status_code == 200, ping.text
            ok, message = await asyncio.to_thread(second.stop)
            assert ok, message
            assert await stream.aread() == b""
    try:
        for server in (first, second):
            ok, message = server.start(timeout=3)
            assert ok, message
        asyncio.run(exercise())
    finally:
        for server in (first, second):
            if server.is_running:
                server.stop(timeout=2)
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_stop_timeout_preserves_active_tool_and_server_ownership(caplog):
    """A slow tool can finish after stop times out; live ownership blocks restart."""
    from langchain_core.tools import StructuredTool

    entered = threading.Event()
    release = threading.Event()

    async def slow_tool() -> str:
        """Hold a real MCP POST until the test releases its execution."""
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return "finished normally"

    tool = StructuredTool.from_function(coroutine=slow_tool, name="SlowTool", description="Wait for test release.")
    server = McpServer(**_mcp_options(plugin_tools=[tool]), port=_available_port())
    ok, message = server.start(timeout=3)
    assert ok, message
    native, thread = server._server, server._thread

    async def exercise():
        """Stop with a live POST, release it, and then reap the same server."""
        async with _connected_client(server) as (client, headers, stream):
            request = asyncio.create_task(client.post(
                server.url() + "/mcp", headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "SlowTool", "arguments": {}}},
            ))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                ok, message = await asyncio.to_thread(server.stop, 0.05)
                assert not ok and "still shutting down" in message
                assert thread.is_alive() and server.is_running and server.is_stopping
                assert server._server is native and server._thread is thread
                assert server._server is native
                assert server._thread is thread
                ok, message = server.start()
                assert not ok and "shutting down" in message
                release.set()
                result = await request
                assert result.status_code == 200
                assert "finished normally" in result.text
                ok, message = await asyncio.to_thread(server.stop, 2)
                assert ok, message
                assert not thread.is_alive()
                assert not server.is_running
                assert server._server is None
                assert await stream.aread() == b""
            finally:
                release.set()
                await request
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        if server.is_running:
            server.stop(timeout=2)
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.parametrize("timeout", [0, -1, True, float('nan'), float('inf')])
def test_lifecycle_rejects_invalid_timeouts(timeout):
    """Neither startup nor shutdown accepts unbounded or ambiguous waits."""
    server = McpServer(**_mcp_options(), port=_available_port())
    assert server.start(timeout=timeout)[0] is False
    assert server.stop(timeout=timeout)[0] is (timeout == 0 and type(timeout) is int)


def test_startup_timeout_preserves_live_thread_until_it_exits(monkeypatch):
    """A startup timeout cannot orphan its thread or allow a competing restart."""
    from ucagent.util import functions

    release = threading.Event()
    native = SimpleNamespace(started=False, should_exit=False)

    def create(*args, **kwargs):
        """Return a server whose startup is deliberately held by the test."""
        return native

    def serve(server):
        """Remain alive through startup cleanup until explicitly released."""
        release.wait(timeout=3)

    monkeypatch.setattr(functions, 'create_verify_mcps', create)
    monkeypatch.setattr(functions, 'start_verify_mcps', serve)
    server = McpServer(**_mcp_options(), port=_available_port())
    try:
        ok, message = server.start(timeout=0.01)
        assert not ok and 'shutdown is still pending' in message
        assert server.is_running and server.is_stopping
        assert server._server is native
        assert server.start()[0] is False
        release.set()
        server._thread.join(timeout=2)
        assert not server.is_running
        ok, message = server.stop(timeout=2)
        assert ok and 'MCP server stopped' in message
        assert server._thread is None and server._server is None
    finally:
        release.set()
        server.stop(timeout=2)


def test_services_retain_wrapper_when_failed_start_is_still_stopping(monkeypatch, tmp_path):
    """The current frontend delegates ownership of a pending wrapper to ServiceManager."""
    from ucagent.server import api_mcp
    from ucagent.control.runtime.services import ServiceManager

    pending = SimpleNamespace(
        is_running=True, is_ready=False, is_stopping=True, host="127.0.0.1", port=5000,
        started_at=None, url=lambda: "http://127.0.0.1:5000",
        start=lambda timeout: (False, "shutdown pending"), stop=lambda timeout: (False, "shutdown pending"),
    )
    monkeypatch.setattr(api_mcp, "McpServer", lambda *args, **kwargs: pending)
    agent = SimpleNamespace(workspace=str(tmp_path), cfg=Config({}), tool_list_base=[],
                            tool_list_task=[], tool_list_ext=[], tool_list_file=[])
    services = ServiceManager(agent)
    result = services.start_mcp(host="127.0.0.1", port=5000)
    assert not result["ok"] and result["message"] == "shutdown pending"
    assert services.get("mcp") is pending
    result = services.start_mcp(host="127.0.0.1", port=5000)
    assert not result["ok"] and services.status("mcp")["state"] == "stopping"
    assert services.get("mcp") is pending



@pytest.mark.parametrize('response_state', ['pending', 'streaming', 'complete'])
def test_get_drain_completes_response_once_and_rejects_new_requests(response_state):
    """A shutdown race must leave valid HTTP framing and reject subsequent work."""
    from ucagent.server.mcp_http import _DrainableMcpApp

    async def exercise():
        """Drain before headers, during a stream, or after the body has ended."""
        entered = asyncio.Event()
        messages = []

        async def app(scope, receive, send):
            """Pause a GET at the selected stage of its HTTP response."""
            if response_state != 'pending':
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            if response_state == 'complete':
                await send({'type': 'http.response.body', 'body': b'done', 'more_body': False})
            entered.set()
            await asyncio.Event().wait()

        async def receive():
            """Keep the connection open until server shutdown ends the response."""
            await asyncio.Event().wait()

        async def send(message):
            """Record response messages without assuming the underlying server."""
            messages.append(message)

        wrapped = _DrainableMcpApp(app)
        task = asyncio.create_task(wrapped({'type': 'http', 'method': 'GET'}, receive, send))
        await entered.wait()
        wrapped.drain()
        await asyncio.wait_for(task, timeout=1)
        expected_status = 503 if response_state == 'pending' else 200
        assert [msg['status'] for msg in messages if msg['type'] == 'http.response.start'] == [expected_status]
        endings = [msg for msg in messages if msg['type'] == 'http.response.body' and not msg.get('more_body', False)]
        assert len(endings) == 1
        if response_state == 'complete':
            assert endings[0]['body'] == b'done'
        for method in ('GET', 'POST'):
            messages.clear()
            await wrapped({'type': 'http', 'method': method}, receive, send)
            assert messages[0]['status'] == 503
    asyncio.run(exercise())


@pytest.mark.parametrize('failure', ['cancel', 'error'])
def test_get_stream_preserves_external_failures(failure):
    """Draining support must never suppress real app errors or external cancellation."""
    from ucagent.server.mcp_http import _DrainableMcpApp

    async def exercise():
        """Interrupt a live GET without requesting the server's own drain."""
        entered = asyncio.Event()
        messages = []

        async def app(scope, receive, send):
            """Wait for external cancellation or raise an application failure."""
            entered.set()
            if failure == 'error':
                raise RuntimeError('application failure')
            await asyncio.Event().wait()

        async def receive():
            """Keep the test connection open until the request is interrupted."""
            await asyncio.Event().wait()

        async def send(message):
            """Capture any response incorrectly synthesized for a failed app."""
            messages.append(message)

        wrapped = _DrainableMcpApp(app)
        task = asyncio.create_task(wrapped({'type': 'http', 'method': 'GET'}, receive, send))
        await entered.wait()
        if failure == 'cancel':
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else RuntimeError):
            await task
        assert not messages
        assert not wrapped._streams
    asyncio.run(exercise())


@pytest.mark.parametrize('kind', ['cmd', 'master'])
def test_embedded_api_start_preserves_shared_uvicorn_logging(tmp_path, kind, short_socket_dir):
    """Starting either API listener leaves existing MCP loggers and handlers intact."""
    from ucagent.server.api_cmd import ControlApiServer
    from ucagent.server.api_master import MasterApiServer

    # Importing the SDK may initialize its own logging, so snapshot after imports.
    loggers = [logging.getLogger(name) for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'uvicorn.asgi')]
    before = [(logger.level, tuple(logger.handlers), logger.propagate, logger.disabled) for logger in loggers]
    cfg = Config({'launch': {'file_browser_roots': []}, 'cmd_api': {'xpra': {}, 'waveform_viewers': {}}})
    if kind == 'cmd':
        pdb = SimpleNamespace(agent=SimpleNamespace(workspace=str(tmp_path), cfg=cfg), stdout=None)
        server = ControlApiServer(Controller(pdb.agent), port=_available_port(), sock=str(short_socket_dir / 'cmd.sock'))
    else:
        server = MasterApiServer(workspace=str(tmp_path), cfg=cfg, port=_available_port(), sock=str(short_socket_dir / 'master.sock'))
    threads = []
    try:
        ok, message = server.start()
        assert ok, message
        threads = [server._tcp_thread, server._sock_thread]
        deadline = time.monotonic() + 2
        while not (server._tcp_server.started and server._sock_server.started) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server._tcp_server.started and server._sock_server.started
        after = [(logger.level, tuple(logger.handlers), logger.propagate, logger.disabled) for logger in loggers]
        assert after == before
    finally:
        server.stop()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


@pytest.fixture
def short_socket_dir():
    """Keep Unix socket names below the platform path-length limit."""
    with tempfile.TemporaryDirectory(prefix='uc-mcp-', dir='/tmp') as directory:
        yield Path(directory)


def test_mcp_logging_bridge_is_thread_scoped_and_removed_on_stop(caplog):
    """MCP never patches getLogger, and a stopped TUI logger cannot accumulate handlers."""
    received = []
    get_logger = logging.getLogger
    loggers = [get_logger(name) for name in ('uvicorn.error', 'uvicorn.access')]
    for logger in loggers:
        caplog.set_level(logging.DEBUG, logger=logger.name)
    before = [tuple(logger.handlers) for logger in loggers]
    logger = SimpleNamespace(log=lambda *args, **kwargs: received.append(args))
    server = McpServer(**_mcp_options(logger=logger), port=_available_port())
    try:
        for _ in range(2):
            ok, message = server.start(timeout=3)
            assert ok, message
            assert logging.getLogger is get_logger
            assert all(len(logger.handlers) == len(handlers) + 1 for logger, handlers in zip(loggers, before))
            loggers[0].warning('different-server-thread')
            assert not any('different-server-thread' in str(record) for record in received)
            assert server.stop(timeout=2)[0] is True
            assert [tuple(logger.handlers) for logger in loggers] == before
        assert any('Uvicorn running' in str(record) for record in received)
    finally:
        if server.is_running:
            server.stop(timeout=2)
