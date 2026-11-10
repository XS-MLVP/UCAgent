"""Real-listener coverage for service ownership, ready endpoints and Master integration."""

from ucagent.application.launch import configure_services
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import select
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from ucagent.core.backends.cmdline import UCAgentCmdLineBackend
from ucagent.runtime.control.controller import Controller, ControlError
from ucagent.runtime.services import ServiceManager
from ucagent.interfaces.server.api_cmd import ControlApiServer
from ucagent.interfaces.server.api_master import MasterApiServer, MasterClient
from ucagent.interfaces.server.api_mcp import McpServer
from ucagent.interfaces.server.api_terminal import WebTerminalServer
from ucagent.core.stage.vstage import VerifyStage
from ucagent.util.config import Config
from ucagent import VerifyAgent


class Agent:
    """Provide state interfaces for service tests without creating a model or debugger."""

    def __init__(self, workspace):
        """Keep tool lists, runtime settings and stage status local to one workspace."""
        self.workspace = str(workspace)
        self.cfg = Config({"mission": {"name": "Service tests"}, "tools": {},
                           "mcp_server": {"host": "127.0.0.1", "port": 0, "init_prompt": "Service test"},
                           "launch": {"file_browser_roots": [str(workspace)],
                                      "default_args": {"use_zip_workspace": True}},
                           "cmd_api": {"host": "127.0.0.1", "port": 0, "xpra": {}, "waveform_viewers": {}},
                           "master_api": {"host": "127.0.0.1", "port": 0,
                                          "sync_workspace": {"on_stage_complete": True, "on_exit": True}}})
        self.tool_list_base = []
        self.tool_list_task = []
        self.tool_list_ext = []
        self.tool_list_file = []
        self.stage_manager = SimpleNamespace(
            stage_index=0, get_time_cost=lambda: 0,
            status=lambda: {"stage_list": [{"index": 0, "title": "Review evidence"}],
                            "current_stage_name": "Review evidence"})
        self.messages = []

    def is_break(self):
        """Report an idle test agent for Master heartbeat payloads."""
        return True

    def message_echo(self, text):
        """Collect backend messages without terminal capture dependencies."""
        self.messages.append(text)


def wait_until(predicate, timeout=3, *, description="Expected service state", diagnostics=None):
    """Wait for observable state; report the phase and optional snapshot only on timeout."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            detail = f"; state={diagnostics()}" if diagnostics is not None else ""
            pytest.fail(f"{description} did not arrive{detail}")
        threading.Event().wait(0.01)


@pytest.fixture
def services(tmp_path):
    """Own every listener and connection created by a test and check final cleanup."""
    owner = ServiceManager(Agent(tmp_path))
    configure_services(owner)
    yield owner
    result = owner.close(5)
    assert result["closed"], result


def test_ready_endpoint_uses_real_port_and_repeated_start_keeps_owner(services):
    """Ready means HTTP is reachable, with one resource and its allocated port."""
    assert services.get("mcp") is None
    with pytest.raises(ControlError):
        services.require_endpoint("mcp")
    result = services.start_mcp()
    assert result["ok"], result
    server = services.get("mcp")
    endpoint = services.require_endpoint("mcp")
    assert endpoint["port"] > 0 and services.agent.cfg.mcp_server.port == 0
    assert httpx.get(endpoint["url"] + "/mcp", timeout=2).status_code in {400, 405, 406}
    assert services.start_mcp()["ok"]
    assert services.get("mcp") is server
    assert services.stop("mcp")["ok"]
    assert services.stop("mcp")["ok"]
    assert server._thread is None
    with pytest.raises(ControlError):
        services.require_endpoint("mcp")
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=0.5)


def test_partial_start_failure_rolls_back_real_listener_and_preserves_occupied_port(services):
    """A later bind failure stops the earlier service without claiming the occupied socket."""
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        result = services.start_group([
            ("mcp", lambda: McpServer([], cfg=services.agent.cfg, host="127.0.0.1", port=0)),
            ("master", lambda: MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                                               host="127.0.0.1", port=port, sock="")),
        ])
        assert not result["ok"]
        assert f"master TCP 127.0.0.1:{port}" in services.status("master")["message"]
        assert result["rollback"][0]["ok"]
        assert not services.get("mcp").is_running
        assert not services.get("master").is_running
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_group_does_not_rollback_preexisting_service_when_factory_raises(services):
    """Construction failure rolls back only services actually created by this group."""
    assert services.start_mcp()["ok"]
    existing = services.get("mcp")
    factory = Mock(side_effect=RuntimeError("Invalid service configuration"))
    result = services.start_group([("mcp", Mock(side_effect=AssertionError("Duplicate instance"))),
                                   ("broken", factory)])
    assert not result["ok"] and result["rollback"] == []
    assert services.get("mcp") is existing and existing.is_ready
    assert services.status("broken")["state"] == "failed"


def test_multi_listener_failure_closes_bound_tcp_and_keeps_foreign_unix_socket(services):
    """Failure of the second listener cannot orphan TCP or unlink another server's socket."""
    with tempfile.TemporaryDirectory(prefix="uc-svc-", dir="/tmp") as directory, socket.socket(socket.AF_UNIX) as occupied:
        path = str(Path(directory) / "occupied.sock")
        occupied.bind(path)
        occupied.listen(1)
        server = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                                 host="127.0.0.1", port=0, sock=path)
        result = services.start("master", lambda: server)
        assert not result["ok"] and not server.is_running
        assert Path(path).exists()
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(path)
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", server.port), timeout=0.5)


def test_pending_http_request_retains_resource_and_thread_until_response(services):
    """Stop cannot report success or admit a replacement while a real request is running."""
    entered, release = threading.Event(), threading.Event()
    server = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                             host="127.0.0.1", port=0, sock="")

    @server._app.get("/held-request")
    async def held_request():
        """Keep a live HTTP request active until the test releases it."""
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"finished": True}

    assert services.start("master", lambda: server)["ok"]
    native, thread = server._tcp_server, server._tcp_thread
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(httpx.get, server.url() + "/held-request", timeout=5)
        try:
            assert entered.wait(3)
            result = services.stop("master", timeout=0.02)
            assert not result["ok"] and result["state"] == "stopping"
            assert services.get("master") is server
            assert server._tcp_server is native and server._tcp_thread is thread
            assert thread.is_alive()
            with pytest.raises(ControlError):
                services.require_endpoint("master")
            replacement = Mock(side_effect=AssertionError("Must retain old owner"))
            assert not services.start("master", replacement)["ok"]
            replacement.assert_not_called()
        finally:
            release.set()
        assert request.result(timeout=3).json() == {"finished": True}
    assert services.stop("master", timeout=3)["ok"]
    assert not thread.is_alive() and server._tcp_thread is None


def test_terminal_stop_can_be_retried_without_interrupting_cleanup(services, monkeypatch):
    """Repeated stop waits for the same real cleanup coroutine instead of aborting it."""
    cleaning, release = threading.Event(), threading.Event()
    server = WebTerminalServer(host="127.0.0.1", port=0)
    original = server._cleanup_async

    async def cleanup():
        """Hold the real terminal's cleanup to expose the pending-stop state."""
        cleaning.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        await original()

    monkeypatch.setattr(server, "_cleanup_async", cleanup)
    assert services.start("terminal", lambda: server)["ok"]
    assert server.port > 0
    assert httpx.get(server.url() + "/api/status", timeout=2).status_code == 200
    thread = server._thread
    try:
        assert not services.stop("terminal", timeout=0)["ok"]
        assert cleaning.wait(2)
        assert not services.stop("terminal", timeout=0.01)["ok"]
        assert thread.is_alive() and services.get("terminal") is server
    finally:
        release.set()
    assert services.stop("terminal", timeout=3)["ok"]
    assert not thread.is_alive()


def test_backend_waits_for_ready_mcp_and_renders_allocated_port(services, tmp_path):
    """A configuration port is never used to start commands before the actual MCP endpoint."""
    template = tmp_path / "template.txt"
    template.write_text("MCP={{PORT}}")
    target = tmp_path / "rendered.txt"
    backend = UCAgentCmdLineBackend(services.agent, services.agent.cfg, cli_cmd_ctx="",
                                   render_files={str(template): str(target)})
    backend.init()
    assert not target.exists()
    with pytest.raises(ControlError):
        backend.prepare()
    assert not target.exists()
    assert services.start_mcp()["ok"]
    port = services.require_endpoint("mcp")["port"]
    backend.prepare()
    assert target.read_text() == f"MCP={port}"
    services.stop("mcp")
    with pytest.raises(ControlError):
        backend.prepare()


def test_starting_mcp_is_not_exposed_to_backend_and_close_retains_owner(services, monkeypatch):
    """A worker held in startup stays owned through a shutdown deadline."""
    from ucagent.interfaces.server import mcp_http

    entered, release = threading.Event(), threading.Event()
    native = SimpleNamespace(started=False, should_exit=False)

    def serve(server):
        """Represent an SDK startup waiting on external work, without a ready endpoint."""
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(mcp_http, "create_verify_mcps", lambda *args, **kwargs: native)
    monkeypatch.setattr(mcp_http, "start_verify_mcps", serve)
    with ThreadPoolExecutor(max_workers=1) as pool:
        starting = pool.submit(services.start_mcp, timeout=0.02)
        try:
            assert entered.wait(2)
            assert services.status("mcp")["state"] == "starting"
            with pytest.raises(ControlError):
                services.require_endpoint("mcp")
            assert not services.close(0)["closed"]
            server = services.get("mcp")
            assert server._server is native and server._thread.is_alive()
        finally:
            release.set()
        assert not starting.result(timeout=3)["ok"]
    assert services.close(3)["closed"]


def test_two_service_owners_do_not_share_listeners(services, tmp_path):
    """Closing one instance leaves the other instance's MCP endpoint reachable."""
    other_path = tmp_path / "other"
    other_path.mkdir()
    other = ServiceManager(Agent(other_path))
    configure_services(other)
    try:
        assert services.start_mcp()["ok"] and other.start_mcp()["ok"]
        endpoint = other.require_endpoint("mcp")
        assert services.require_endpoint("mcp")["port"] != endpoint["port"]
        assert services.close(3)["closed"]
        assert other.get("mcp").is_ready
        assert httpx.get(endpoint["url"] + "/mcp", timeout=2).status_code in {400, 405, 406}
    finally:
        assert other.close(3)["closed"]


def test_master_registration_acknowledges_heartbeat_with_sync_capabilities(services):
    """Registration must return HTTP success after saving the agent and building capabilities."""
    master = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                             host="127.0.0.1", port=0, sock="")
    result = services.start("master", lambda: master)
    assert result["ok"], result
    response = httpx.post(master.url() + "/api/register",
                          json={**services.heartbeat_payload(), "id": "child"}, timeout=2)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ok", data
    sync = data["capabilities"]["workspace_sync_back"]
    assert sync["use_zip_workspace"] is True
    assert sync["enabled"] is False  # This child has no Master-managed task to sync back.
    assert "child" in master._agents


def test_local_self_registration_uses_ready_command_endpoint(services):
    """The same self-registration works regardless of which local listener starts first."""
    master = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                             host="127.0.0.1", port=0, sock="", access_key="local-key")
    assert services.start("master", lambda: master)["ok"]
    assert services.connections() == {}
    frontend = SimpleNamespace(agent=services.agent, stdout=None)
    result = services.start("cmd", lambda: ControlApiServer(Controller(frontend.agent), host="127.0.0.1", port=0, sock=""))
    assert result["ok"], result
    client = services.connections()[master.url()]
    wait_until(lambda: "self" in master._agents and client.is_connected,
               description="Acknowledged local self-registration", diagnostics=services.connection_status)
    endpoint = services.require_endpoint("cmd")
    assert master._agents["self"]["cmd_api_tcp"] == endpoint["url"]
    assert len(services.connections()) == 1
    services.ensure_self_connection()
    assert len(services.connections()) == 1
    assert services.stop("cmd")["ok"]
    assert services.connections() == {}


def test_multiple_master_connections_reconnect_and_disconnect_independently(services, tmp_path):
    """A child can report to two real Masters and retry a temporarily stopped endpoint."""
    masters = []
    try:
        for index in range(2):
            workspace = tmp_path / f"master-{index}"
            workspace.mkdir()
            server = MasterApiServer(workspace=str(workspace), cfg=services.agent.cfg,
                                     host="127.0.0.1", port=0, sock="")
            assert server.start()[0]
            masters.append(server)
            assert services.connect(server.url(), agent_id="child", interval=0.02, reconnect_interval=0.02)["ok"]
        clients = [services.connections()[server.url()] for server in masters]
        # A registry entry is written before the HTTP response is built; require
        # the client's acknowledgement so a route failure cannot pass this gate.
        wait_until(lambda: all("child" in server._agents for server in masters)
                   and all(client.is_connected for client in clients),
                   description="Acknowledged registration with both Masters", diagnostics=services.connection_status)
        first_url = masters[0].url()
        client, other_client = clients
        assert masters[0].stop()[0]
        last_seen = masters[0]._agents["child"]["last_seen"]
        wait_until(lambda: not client.is_connected,
                   description="First Master disconnect detection", diagnostics=services.connection_status)
        assert client.is_running and other_client.is_connected
        assert masters[0].start()[0]
        assert masters[0].url() == first_url
        wait_until(lambda: client.is_connected and masters[0]._agents["child"]["last_seen"] > last_seen,
                   description="Acknowledged fresh heartbeat after restart", diagnostics=services.connection_status)
        assert services.connections()[first_url] is client
        assert all(row["ok"] for row in services.disconnect(first_url))
        assert not client.is_running
        assert services.connections() == {masters[1].url(): other_client}
        last_seen = masters[1]._agents["child"]["last_seen"]
        wait_until(lambda: other_client.is_connected and masters[1]._agents["child"]["last_seen"] > last_seen,
                   description="Second Master heartbeat after first client disconnects", diagnostics=services.connection_status)
    finally:
        services.disconnect()
        for server in masters:
            assert server.stop()[0]


def test_master_client_stop_keeps_inflight_http_worker(tmp_path, monkeypatch):
    """A heartbeat blocked inside transport is still owned after a nonblocking stop."""
    entered, release = threading.Event(), threading.Event()

    def post(*args, **kwargs):
        """Return an actual completed response only after stop has observed the worker."""
        entered.set()
        assert release.wait(4)
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {"status": "ok"})

    monkeypatch.setattr("requests.post", post)
    client = MasterClient("http://127.0.0.1:8800", payload=lambda: {}, workspace=str(tmp_path), cfg=Config({}))
    try:
        assert client.start()[0]
        assert entered.wait(2)
        thread = client._thread
        assert not client.stop(timeout=0)[0]
        assert client.is_running and client._thread is thread
        assert not client.start()[0]
    finally:
        release.set()
    assert client.stop(timeout=3)[0]
    assert not thread.is_alive() and client._thread is None


def test_stage_and_exit_sync_callbacks_preserve_order_flags_and_failure_isolation(services):
    """Completion saves before callback; sync-disabled paths and failing peers stay isolated."""
    events = []
    good = SimpleNamespace(is_running=True, sync_workspace_back=lambda **kwargs: (events.append(kwargs["reason"]) or True, "sent"))
    bad = SimpleNamespace(is_running=True, sync_workspace_back=Mock(side_effect=OSError("unreachable")))
    services._clients.update({"http://bad": bad, "http://good": good})
    try:
        manager = SimpleNamespace(workspace_sync_callback=services.sync_workspace_back,
                                  save_stage_info=lambda: events.append("save"))
        stage = VerifyStage.__new__(VerifyStage)
        stage.cfg = services.agent.cfg
        stage.vmanager = manager
        stage.name = "review"
        VerifyStage._sync_workspace_back_on_complete(stage, stage)
        assert events == ["save", "stage_complete:review"]
        result = services.sync_workspace_back(reason="manual")
        assert [row["ok"] for row in result] == [False, True]
        services.agent.cfg.set_value("master_api.sync_workspace.on_stage_complete", False)
        VerifyStage._sync_workspace_back_on_complete(stage, stage)
        assert events.count("save") == 1
        services.agent.cfg.set_value("master_api.sync_workspace.on_exit", False)
        assert services.sync_workspace_back(reason="exit") == []
        exiting = VerifyAgent.__new__(VerifyAgent)
        exiting.cfg = services.agent.cfg
        exiting.services = services
        exiting._sync_workspace_back_on_exit_done = False
        VerifyAgent._sync_workspace_back_on_exit(exiting)
        assert "exit" not in events
        services.agent.cfg.set_value("master_api.sync_workspace.on_exit", True)
        exiting._sync_workspace_back_on_exit_done = False
        VerifyAgent._sync_workspace_back_on_exit(exiting)
        VerifyAgent._sync_workspace_back_on_exit(exiting)
        assert events.count("exit") == 1
    finally:
        services._clients.clear()


def test_service_commands_validate_options_and_return_actual_status(services):
    """Explicit dispatch shares the same owner and rejects unsupported options."""
    with pytest.raises(ControlError) as caught:
        services.execute("start_mcp_server", {"argv": ["--unsupported"]}, None)
    assert caught.value.code == "invalid_argument"
    result = services.execute("start_mcp_server_no_file_ops", {"argv": ["127.0.0.1", "0"]}, None)
    assert result["ok"] and result["endpoint"]["port"] > 0
    assert services.execute("mcp_server_status", {}, None)["endpoint"] == result["endpoint"]
    assert services.execute("stop_mcp_server", {}, None)["state"] == "stopped"


@pytest.mark.parametrize("method", ["_pty_read_loop", "_pty_stdin_relay"])
def test_idle_terminal_relays_can_stop_without_new_input(method, monkeypatch):
    """Real idle pipe reads must observe shutdown without injected thread exceptions."""
    server = WebTerminalServer(host="127.0.0.1", port=0)
    entered = threading.Event()
    original_select = select.select

    def polling(*args, **kwargs):
        """Signal that the relay reached its actual bounded input wait."""
        entered.set()
        return original_select(*args, **kwargs)

    monkeypatch.setattr(select, "select", polling)
    read_fd, write_fd = os.pipe()
    server._pty_active = True
    thread = threading.Thread(target=getattr(server, method), args=(read_fd, write_fd))
    thread.start()
    try:
        assert entered.wait(2)
        server._pty_active = False
        thread.join(2)
        assert not thread.is_alive()
    finally:
        server._pty_active = False
        os.close(read_fd)
        os.close(write_fd)
        thread.join(2)


@pytest.mark.parametrize("service_name", ["cmd", "master"])
@pytest.mark.parametrize("collision", ["stale", "live", "file"])
def test_automatic_unix_socket_collision_uses_owned_path(services, service_name, collision):
    """Default socket collisions preserve existing paths and publish the actual new endpoint."""
    if service_name == "cmd":
        server = ControlApiServer(services.controller, services=services, port=0)
    else:
        server = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                                 host="127.0.0.1", port=0)
    original = Path(server.sock)
    occupied = None
    try:
        if collision == "file":
            original.write_text("existing unrelated file")
        else:
            occupied = socket.socket(socket.AF_UNIX)
            occupied.bind(str(original))
            if collision == "live":
                occupied.listen(4)
            else:
                occupied.close()
                occupied = None
        identity = original.stat().st_ino
        result = services.start(service_name, lambda: server)
        assert result["ok"], result
        endpoint = services.require_endpoint(service_name)
        actual = Path(endpoint["sock"])
        assert actual != original and actual.is_socket()
        assert original.stat().st_ino == identity
        assert httpx.get(endpoint["url"] + "/", timeout=2).status_code == 200
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(actual)), base_url="http://localhost") as client:
            assert client.get("/").status_code == 200
        assert services.stop(service_name)["ok"]
        assert not actual.exists() and original.stat().st_ino == identity
        if occupied is not None:
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                probe.connect(str(original))
        if collision == "file":
            assert original.read_text() == "existing unrelated file"
    finally:
        services.stop(service_name)
        if occupied is not None:
            occupied.close()
        original.unlink(missing_ok=True)


@pytest.mark.parametrize("service_name", ["cmd", "master"])
def test_explicit_stale_socket_reports_address_and_preserves_path(services, service_name):
    """An explicitly configured socket cannot silently move even if its listener has exited."""
    with tempfile.TemporaryDirectory(prefix="uc-explicit-", dir="/tmp") as directory:
        path = Path(directory) / "stale.sock"
        with socket.socket(socket.AF_UNIX) as previous:
            previous.bind(str(path))
        identity = path.stat().st_ino
        if service_name == "cmd":
            server = ControlApiServer(services.controller, services=services, port=0, sock=str(path))
        else:
            server = MasterApiServer(workspace=services.agent.workspace, cfg=services.agent.cfg,
                                     host="127.0.0.1", port=0, sock=str(path))
        result = services.start(service_name, lambda: server)
        assert not result["ok"]
        assert "Unix socket " + str(path) in result["message"]
        assert path.stat().st_ino == identity and server.sock == str(path)
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", server.port), timeout=0.5)
