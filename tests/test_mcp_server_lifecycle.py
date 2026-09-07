"""Regression tests for readiness-aware MCP server lifecycle management."""

import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ucagent.server.api_mcp import PdbMcpServer
from ucagent.util.config import Config


def _available_port() -> int:
    """Reserve and release a loopback port for a lifecycle test."""

    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _fake_pdb(*, file_tools=None, plugin_tools=None):
    """Build the minimum PDB/agent surface consumed by PdbMcpServer."""

    agent = SimpleNamespace(
        tool_list_base=[],
        tool_list_task=[],
        tool_list_ext=[],
        tool_list_waveform=[],
        tool_list_plugin=list(plugin_tools or []),
        tool_list_file=list(file_tools or []),
        cfg=Config(
            {
                "mcp_server": {"init_prompt": "lifecycle test"},
                "tools": {},
            }
        ),
        _mcps_logger=None,
        _mcps=None,
        _mcp_server_thread=None,
    )
    return SimpleNamespace(agent=agent)


def test_mcp_start_waits_until_http_endpoint_is_reachable():
    """Successful start means uvicorn has completed application startup."""

    port = _available_port()
    server = PdbMcpServer(
        _fake_pdb(),
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
        server = PdbMcpServer(
            _fake_pdb(),
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
