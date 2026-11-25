"""Authenticate every Master WebSocket before resolving a privileged child."""

import base64
import time
from unittest.mock import Mock

from fastapi import WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from ucagent.interfaces.server.api_master import MasterApiServer
from ucagent.util.config import Config


ROUTES = [f"/{owner}/missing/{service}/ws"
          for owner in ("task", "agent") for service in ("terminal", "web-console")]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("authorization", [
    "", "Bearer master-secret", "Basic !!!", "Basic /w==",
    "Basic " + base64.b64encode(b"master-secret").decode(),
    "Basic " + base64.b64encode(b"user:wrong").decode(),
    "Basic " + base64.b64encode(b"user:child-secret").decode(),
])
def test_proxy_rejects_invalid_credentials_before_target_lookup(tmp_path, monkeypatch, route, authorization):
    """Missing, malformed and child credentials never reach lookup or upstream I/O."""
    server = MasterApiServer(workspace=str(tmp_path), password="master-secret",
                             cfg=Config({"launch": {"file_browser_roots": []}}).freeze())
    forbidden = Mock(side_effect=AssertionError("Unauthenticated target access"))
    monkeypatch.setattr(server, "_get_task", forbidden)
    monkeypatch.setattr(server, "_agents", Mock(get=forbidden))
    monkeypatch.setattr("aiohttp.ClientSession", forbidden)
    with TestClient(server._app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(route, headers={"Authorization": authorization}):
                pytest.fail("Unauthenticated proxy accepted")
    assert caught.value.code == 1008
    forbidden.assert_not_called()


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("password,authorization", [
    ("master-secret", "Basic " + base64.b64encode(b"user:master-secret").decode()),
    ("master-secret", "basic " + base64.b64encode(b"user:master-secret").decode()),
    ("", ""),
])
def test_proxy_authorized_requests_reach_target_resolution(tmp_path, route, password, authorization):
    """Valid Master credentials and intentionally open listeners retain ordinary routing."""
    server = MasterApiServer(workspace=str(tmp_path), password=password,
                             cfg=Config({"launch": {"file_browser_roots": []}}).freeze())
    with TestClient(server._app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(route, headers={"Authorization": authorization}):
                pytest.fail("Missing target accepted")
    assert caught.value.code == 4404


@pytest.mark.parametrize("route", ROUTES)
def test_authenticated_proxy_uses_child_credentials_for_real_upstream(tmp_path, monkeypatch, route):
    """An authorized browser round-trips bytes through a real child connection, never Master auth."""
    server = MasterApiServer(workspace=str(tmp_path), host="127.0.0.1", port=0, sock="",
                             password="master-secret", cfg=Config({"launch": {"file_browser_roots": []}}).freeze())
    observed = []

    @server._app.websocket("/ws")
    async def child(websocket: WebSocket):
        """Use an isolated echo transport instead of starting a real terminal or model."""
        observed.append(websocket.headers.get("authorization"))
        await websocket.accept()
        await websocket.send_text(await websocket.receive_text())
        await websocket.send_bytes(await websocket.receive_bytes())
        await websocket.receive()

    try:
        assert server.start()[0]
        service = {"status": "running", "enabled": True, "password": "child-secret", "tcp_url": server.url()}
        task = {"task_id": "missing", "terminal_api": service, "web_console": service}
        monkeypatch.setattr(server, "_get_task", lambda identifier: task)
        monkeypatch.setattr(server, "_refresh_task_runtime_info_from_agent", lambda task: None)
        with server._agents_lock:
            server._agents["missing"] = {"id": "missing", "last_seen": time.time(),
                                         "terminal_api": service, "web_console": service}
        credentials = "Basic " + base64.b64encode(b"user:master-secret").decode()
        with TestClient(server._app) as client:
            with client.websocket_connect(route, headers={"Authorization": credentials}) as socket:
                socket.send_text("safe fixture input")
                assert socket.receive_text() == "safe fixture input"
                socket.send_bytes(b"\x00\xff")
                assert socket.receive_bytes() == b"\x00\xff"
        assert len(observed) == 1
        assert base64.b64decode(observed[0].split(" ", 1)[1]).decode().partition(":")[2] == "child-secret"
    finally:
        server.stop()
