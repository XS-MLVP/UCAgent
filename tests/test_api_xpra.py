"""Owned Xpra lifecycle, authenticated proxies and concurrent terminal coverage."""

import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
import time
from types import SimpleNamespace

import aiohttp
from fastapi.testclient import TestClient
import psutil
import pytest
from starlette.websockets import WebSocketDisconnect

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.server.api_cmd.xpra import XpraError, XpraSessionManager
from ucagent.server.api_master import PdbMasterApiServer
from ucagent.server.api_terminal import PdbWebTermServer
from ucagent.util.config import Config, load_yaml_with_env_vars
from ucagent.util import log


FAKE_XPRA = r'''#!/usr/bin/env python3
"""A real Unix HTTP/WebSocket subprocess used to test the integration boundary."""
import asyncio, gzip, json, os, shlex, subprocess, sys
from aiohttp import web
if "--version" in sys.argv:
    print("xpra v6.5.5-test")
    raise SystemExit(0)
behavior = os.environ.get("FAKE_BEHAVIOR", "normal")
if behavior == "fail":
    print("fake startup failure " + os.environ.get("TEST_TOKEN", ""), flush=True)
    raise SystemExit(9)
socket_path = next(x.split("=", 1)[1].split(",")[0] for x in sys.argv if x.startswith("--bind="))
command = next(x.split("=", 1)[1] for x in sys.argv if x.startswith("--start-child="))
print("SERVER_ARGS:" + json.dumps(sys.argv[1:]), flush=True)
print("ARGS:" + json.dumps(shlex.split(command)), flush=True)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                         stdout=subprocess.DEVNULL, start_new_session=behavior == "crash")
print("CHILD:" + str(child.pid), flush=True)
async def handler(request):
    """Return client assets or negotiate the same protocol as a real Xpra peer."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        ws = web.WebSocketResponse(protocols=["binary"])
        await ws.prepare(request)
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                await ws.send_str(message.data)
            elif message.type == web.WSMsgType.BINARY:
                await ws.send_bytes(message.data)
        return ws
    if behavior == "nohtml":
        return web.Response(status=404)
    if request.path == "/redirect":
        raise web.HTTPFound("/index.html")
    if request.path.endswith(".wasm"):
        return web.Response(body=b"\0asm\x01\0\0\0", content_type="application/wasm")
    if request.path == "/negotiated.html":
        if "unsupported-test" in request.headers.get("Accept-Encoding", ""):
            return web.Response(status=415)
        body = b"<!doctype html><html><body>Compressed client</body></html>"
        headers = {}
        if "gzip" in request.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        return web.Response(body=body, content_type="text/html", headers=headers)
    return web.Response(text="<!doctype html><html><body>Xpra test client</body></html>", content_type="text/html")
async def main():
    """Own the socket and leave cleanup to the host process manager."""
    if behavior == "timeout":
        await asyncio.Event().wait()
    if behavior == "slow":
        await asyncio.sleep(.4)
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.UnixSite(runner, socket_path).start()
    if behavior == "crash":
        asyncio.get_running_loop().call_later(.6, os._exit, 7)
    await asyncio.Event().wait()
asyncio.run(main())
'''


@pytest.fixture
def xpra_config(tmp_path):
    """Install an executable peer so tests require no X11 or Xpra installation."""
    executable = tmp_path / "xpra-test"
    executable.write_text(FAKE_XPRA.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
    executable.chmod(0o700)
    return Config({"cmd_api": {"xpra": dict(executable=str(executable), startup_timeout=2,
                                            shutdown_timeout=.3, terminal_command=["/usr/bin/env"])}})


@pytest.fixture
def manager(tmp_path, xpra_config):
    """Always reap the test peer and all of its child processes."""
    instance = XpraSessionManager(tmp_path, xpra_config)
    yield instance
    instance.close()


@pytest.fixture
def cmd_server(tmp_path, xpra_config):
    """Restore the existing process-wide console capture after every API test."""
    pdb = SimpleNamespace(agent=SimpleNamespace(workspace=str(tmp_path), cfg=xpra_config), stdout=None)
    server = PdbCmdApiServer(pdb, port=0, sock="", password="cmd-test-password")
    yield server
    if server._running:
        threads = [server._tcp_thread, server._sock_thread]
        server.stop()
        for thread in threads:
            if thread:
                thread.join(timeout=5)
    server.close_sessions()
    if sys.stdout is server._console_capture:
        sys.stdout = server._console_capture._original
    log.set_console_sync_handler(server._original_sync_handler)
    atexit.unregister(server.close_sessions)


def _wait_for(predicate, timeout=5):
    """Wait for an external process transition with a bounded deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("Timed out waiting for process state")


def _start_listener(server):
    """Start a real listener and return its OS-assigned TCP port."""
    ok, message = server.start()
    assert ok, message
    _wait_for(lambda: server._tcp_server.started)
    return server._tcp_server.servers[0].sockets[0].getsockname()[1]


@pytest.mark.parametrize("key,value", [("max_sessions", 0), ("max_sessions", True),
    ("max_sessions", "5"), ("startup_timeout", -1), ("startup_timeout", float("inf")),
    ("shutdown_timeout", False), ("terminal_command", []), ("terminal_command", "xterm -e"),
    ("executable", ""), ("html_dir", [])])
def test_invalid_configuration_is_an_actionable_optional_feature_error(tmp_path, xpra_config, key, value):
    """Invalid feature settings cannot silently change quotas or command behavior."""
    xpra_config.cmd_api.xpra.from_dict({key: value})
    instance = XpraSessionManager(tmp_path, xpra_config)
    status = instance.status()
    assert not status["available"]
    assert status["diagnostic"]["error_code"] == "XPRA_CONFIG_INVALID"
    with pytest.raises(XpraError) as error:
        instance.create(sys.executable)
    assert error.value.status == 503


def test_prerequisite_diagnostics_and_empty_list(tmp_path, xpra_config):
    """Missing binaries and HTML5 files remain distinguishable from no sessions."""
    xpra_config.cmd_api.xpra.executable = "/no-such-xpra-binary"
    instance = XpraSessionManager(tmp_path, xpra_config)
    assert instance.status()["diagnostic"]["error_code"] == "XPRA_NOT_FOUND"
    assert instance.list() == dict(sessions=[], active_count=0, max_sessions=5)
    xpra_config.cmd_api.xpra.executable = str(tmp_path / "xpra-test")
    xpra_config.cmd_api.xpra.html_dir = str(tmp_path / "absent-html5")
    assert XpraSessionManager(tmp_path, xpra_config).status()["diagnostic"]["error_code"] == "XPRA_HTML5_MISSING"


def test_lifecycle_console_quoting_and_owned_cleanup(manager):
    """Launch quoted argv, wrap console commands and reap the entire owned tree."""
    session = manager.create(shlex.join([sys.executable, "argument with spaces"]), mode="console", name="console")
    session_id = session["id"]
    assert session["status"] == "running"
    _wait_for(lambda: any(line.startswith("CHILD:") for line in manager.get(session_id)["log_tail"]))
    details = manager.get(session_id)
    arguments = json.loads(next(line[5:] for line in details["log_tail"] if line.startswith("ARGS:")))
    assert arguments == ["/usr/bin/env", sys.executable, "argument with spaces"]
    child_pid = int(next(line[6:] for line in details["log_tail"] if line.startswith("CHILD:")))
    process = manager._sessions[session_id].process
    socket_dir = Path(manager.socket_path(session_id)).parent
    assert socket_dir.stat().st_mode & 0o777 == 0o700
    assert manager.delete(session_id) == dict(id=session_id, deleted=True)
    assert process.poll() is not None
    assert not socket_dir.exists()
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    assert manager.list()["active_count"] == 0
    with pytest.raises(XpraError, match="does not exist"):
        manager.get(session_id)


@pytest.mark.parametrize("idle_timeout", [-1, 1, 60])
def test_single_client_and_idle_timeout_server_contract(manager, idle_timeout):
    """Enforce exclusive takeover and count disconnected time at the Xpra server."""
    session = manager.create(sys.executable, idle_timeout=idle_timeout)
    assert session["idle_timeout"] == idle_timeout
    assert manager.list()["sessions"][0]["idle_timeout"] == idle_timeout
    details = manager.get(session["id"])
    arguments = json.loads(next(line[len("SERVER_ARGS:"):] for line in details["log_tail"] if line.startswith("SERVER_ARGS:")))
    assert "--sharing=no" in arguments
    assert "--lock=no" in arguments
    assert "--exit-with-client=no" in arguments
    assert "--idle-timeout=0" in arguments
    assert f"--server-idle-timeout={max(0, idle_timeout)}" in arguments


@pytest.mark.parametrize("idle_timeout", [0, -2, True, "5", 1.5, 4_294_968])
def test_invalid_idle_timeouts_do_not_launch_sessions(manager, idle_timeout):
    """Invalid idle seconds cannot consume capacity or silently disable expiry."""
    with pytest.raises(XpraError) as error:
        manager.create(sys.executable, idle_timeout=idle_timeout)
    assert error.value.status == 422
    assert error.value.detail["error_code"] == "XPRA_IDLE_TIMEOUT_INVALID"
    assert manager.list()["active_count"] == 0


@pytest.mark.parametrize("behavior,status,code", [("fail",503,"XPRA_START_FAILED"),
    ("timeout",504,"XPRA_START_TIMEOUT"), ("nohtml",503,"XPRA_HTML5_MISSING")])
def test_start_failures_release_capacity_and_redact_logs(manager, behavior, status, code):
    """Every failed startup leaves a bounded diagnostic and no active process."""
    with pytest.raises(XpraError) as error:
        manager.create(sys.executable, env={"FAKE_BEHAVIOR": behavior, "TEST_TOKEN": "secret-for-redaction"})
    assert error.value.status == status
    assert error.value.detail["error_code"] == code
    assert "secret-for-redaction" not in json.dumps(error.value.detail)
    assert manager.list()["active_count"] == 0
    assert all(s.process is None or s.process.poll() is not None for s in manager._sessions.values())


def test_quota_is_atomic_and_stop_cancels_creation(tmp_path, xpra_config):
    """Parallel listeners cannot overbook or spawn after shutdown snapshots work."""
    xpra_config.cmd_api.xpra.max_sessions = 1
    instance = XpraSessionManager(tmp_path, xpra_config)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(instance.create, sys.executable, env={"FAKE_BEHAVIOR": "slow"})
            _wait_for(lambda: instance.list()["active_count"] == 1)
            with pytest.raises(XpraError) as error:
                instance.create(sys.executable)
            assert error.value.status == 409
            instance.close()
            with pytest.raises(XpraError):
                pending.result(timeout=5)
        assert instance.list()["active_count"] == 0
        with pytest.raises(XpraError) as error:
            instance.create(sys.executable)
        assert error.value.detail["error_code"] == "XPRA_STOPPING"
    finally:
        instance.close()


@pytest.mark.parametrize("changes,code", [({"command":"'unterminated"},"XPRA_COMMAND_INVALID"),
    ({"command":"not-an-installed-application"},"XPRA_COMMAND_NOT_FOUND"),
    ({"cwd":"../"},"XPRA_CWD_INVALID"), ({"env":{"BAD=NAME":"value"}},"XPRA_ENV_INVALID")])
def test_invalid_launch_inputs(manager, changes, code):
    """Malformed commands and escaping directories fail before reserving capacity."""
    with pytest.raises(XpraError) as error:
        manager.create(**dict({"command":sys.executable}, **changes))
    assert error.value.detail["error_code"] == code
    assert manager.list()["active_count"] == 0


def test_symlink_escape_and_missing_terminal_are_rejected(manager, tmp_path):
    """Directory checks follow symlinks and console mode checks its own program."""
    with tempfile.TemporaryDirectory() as outside:
        (tmp_path / "escape").symlink_to(outside)
        with pytest.raises(XpraError) as error:
            manager.create(sys.executable, cwd="escape")
        assert error.value.detail["error_code"] == "XPRA_CWD_INVALID"
    manager.options["terminal_command"] = ["/no-such-terminal"]
    with pytest.raises(XpraError) as error:
        manager.create(sys.executable, mode="console")
    assert error.value.detail["error_code"] == "XPRA_TERMINAL_NOT_FOUND"


@pytest.mark.parametrize("deny_group_cleanup", [False, True])
def test_unexpected_exit_updates_state_and_releases_quota(manager, monkeypatch, deny_group_cleanup):
    """A crashed Xpra parent must reap children even in separate process groups."""
    session = manager.create(sys.executable, env={"FAKE_BEHAVIOR": "crash"})
    process = manager._sessions[session["id"]].process
    denied = []
    if deny_group_cleanup:
        original_killpg = os.killpg

        def killpg(pid, sig):
            """Model an exited group that cannot be signaled on the host platform."""
            if pid == process.pid and sig == signal.SIGKILL and process.poll() is not None:
                denied.append(pid)
                raise PermissionError("The exited process group cannot be signaled.")
            return original_killpg(pid, sig)

        monkeypatch.setattr(os, "killpg", killpg)
    details = manager.get(session["id"])
    child_pid = int(next(line[6:] for line in details["log_tail"] if line.startswith("CHILD:")))
    directory = Path(manager.socket_path(session["id"])).parent
    _wait_for(lambda: manager.get(session["id"])["status"] == "failed")
    assert manager.list()["active_count"] == 0
    assert manager.get(session["id"])["last_error"]["error_code"] == "XPRA_PROCESS_EXITED"
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    _wait_for(lambda: not directory.exists())
    if deny_group_cleanup:
        assert denied == [process.pid]


def test_rest_assets_and_structured_validation_use_one_prefix(cmd_server):
    """The manager, viewer and canonical REST routes share /api/xpra/."""
    with TestClient(cmd_server._app) as client:
        client.auth = ("ignored", cmd_server.password)
        assert client.get("/api/xpra/").status_code == 200
        assert client.get("/api/xpra/status").json()["available"]
        invalid = client.post("/api/xpra/sessions", json={"command":sys.executable,"env":{"TOKEN":123}})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["error_code"] == "XPRA_REQUEST_INVALID"
        assert "123" not in invalid.text
        response = client.post("/api/xpra/sessions", json={"command":sys.executable})
        assert response.status_code == 201, response.text
        session_id = response.json()["id"]
        assert response.json()["idle_timeout"] == -1
        prefix = f"/api/xpra/sessions/{session_id}"
        view = client.get(prefix+"/view")
        assert view.status_code == 200
        assert view.headers["cache-control"] == "no-store"
        for entry in ("", "index.html", "connect.html"):
            redirect = client.get(prefix+"/client/"+entry, follow_redirects=False)
            assert redirect.status_code == 307
            assert redirect.headers["location"] == "../view"
        surface = client.get(prefix+"/client/display.html")
        assert surface.headers["content-type"].startswith("text/html")
        assert 'id="screen"' in surface.text
        assert "login_form" not in surface.text
        assert "connect.html" not in surface.text
        assert client.head(prefix+"/client/display.html").headers["content-length"] == str(len(surface.content))
        script = client.get(prefix+"/client/ucagent.js")
        assert script.headers["content-type"].startswith("text/javascript")
        assert script.headers["cache-control"] == "no-store"
        assert "new XpraClient" in script.text
        assert client.get(prefix+"/client/code.wasm").content.startswith(b"\0asm")
        redirect = client.get(prefix+"/client/redirect", follow_redirects=False)
        assert redirect.headers["location"] == "index.html"
        assert client.get(prefix+"/client/%252e%252e/private").status_code == 422
        assert client.delete(prefix).json()["deleted"]
        assert client.get(prefix).status_code == 404
        assert client.get("/api/xpra-session").status_code == 404


def test_default_presets_cover_terminal_browser_and_code_agents():
    """Ship a GUI browser and console launchers with editable workspace defaults."""
    settings = load_yaml_with_env_vars(str(Path(__file__).resolve().parents[1] / "ucagent/setting.yaml"))
    presets = settings["cmd_api"]["xpra"]["presets"]
    assert [(p["label"], p["command"]) for p in presets] == [
        ("Terminal", "bash -l"),
        ("Browser", "chromium --no-first-run --no-default-browser-check about:blank"),
        ("Codex", "codex"), ("OpenCode", "opencode"), ("Qwen Code", "qwen")]
    assert all(p["mode"] == ("gui" if p["label"] == "Browser" else "console")
               and p["name"] == p["label"] and p["cwd"] == "." and p["env"] == {}
               and p["idle_timeout"] == -1 for p in presets)


@pytest.mark.parametrize("idle_timeout", [None, 60])
def test_presets_publish_only_configured_form_fields_without_starting_xpra(cmd_server, idle_timeout):
    """Resolved config replaces the shortcut list and does not require installed CLIs."""
    configured = [{"label": "Custom code agent", "command": "missing-agent --profile 'code review'",
                   "name": "Review", "mode": "console", "cwd": "project",
                   "env": {"TERM": "xterm-256color", "PROMPT_HINT": "quoted \"text\"\nnext line"}}]
    if idle_timeout is not None:
        configured[0]["idle_timeout"] = idle_timeout
    cmd_server.pdb.agent.cfg.cmd_api.xpra.from_dict({"presets": configured})
    cmd_server._xpra.options["executable"] = "/missing-xpra"
    with TestClient(cmd_server._app) as client:
        client.auth = ("user", cmd_server.password)
        response = client.get("/api/xpra/presets")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"presets": [dict(configured[0], idle_timeout=-1 if idle_timeout is None else idle_timeout)]}
        assert "executable" not in response.text
        assert client.get("/api/xpra/status").json()["diagnostic"]["error_code"] == "XPRA_NOT_FOUND"
    assert cmd_server._xpra.list()["sessions"] == []


@pytest.mark.parametrize("idle_timeout", [0, -2, True, "60", 1.5, None, 4_294_968])
def test_rest_rejects_invalid_idle_seconds(cmd_server, idle_timeout):
    """HTTP validation preserves strict seconds and actionable field locations."""
    with TestClient(cmd_server._app) as client:
        response = client.post("/api/xpra/sessions", auth=("user", cmd_server.password),
                               json={"command": sys.executable, "idle_timeout": idle_timeout})
        assert response.status_code == 422
        assert "body.idle_timeout" in response.json()["detail"]["fields"]
    assert cmd_server._xpra.list()["sessions"] == []


@pytest.mark.parametrize("cfg", [None, Config(), Config({"cmd_api": {"xpra": {}}}),
                               Config({"cmd_api": {"xpra": {"presets": []}}})])
def test_empty_or_absent_presets_hide_shortcuts_without_fallback(cmd_server, cfg):
    """Empty or unspecified lists leave manual creation available."""
    cmd_server.pdb.agent.cfg = cfg
    with TestClient(cmd_server._app) as client:
        assert client.get("/api/xpra/presets", auth=("user", cmd_server.password)).json() == {"presets": []}


@pytest.mark.parametrize("configured", [None, {}, "codex", [{}], [{"label": " ", "command": "codex"}],
    [{"label": "Codex", "command": 42}], [{"label": "Codex", "command": "codex", "mode": "terminal"}],
    [{"label": "Codex", "command": "codex", "env": {"TOKEN": {"secret": "config-secret-value"}}}],
    [{"label": "Codex", "command": "codex", "idle_timeout": 0}],
    [{"label": "Codex", "command": "codex", "password": "config-secret-value"}]])
def test_invalid_presets_have_bounded_errors_and_preserve_manual_creation(cmd_server, configured):
    """Malformed shortcut settings never leak values or disable the session API."""
    cmd_server.pdb.agent.cfg.cmd_api.xpra.from_dict({"presets": configured})
    with TestClient(cmd_server._app) as client:
        client.auth = ("user", cmd_server.password)
        response = client.get("/api/xpra/presets")
        assert response.status_code == 503
        assert response.json()["detail"]["error_code"] == "XPRA_PRESETS_INVALID"
        assert "config-secret-value" not in response.text
        assert "Manual session creation" in response.json()["detail"]["next_action"]
        assert client.get("/api/xpra/").status_code == 200
        created = client.post("/api/xpra/sessions", json={"command": sys.executable})
        assert created.status_code == 201, created.text
        assert client.delete("/api/xpra/sessions/" + created.json()["id"]).status_code == 200


@pytest.mark.parametrize("path", ["/api/xpra/","/api/xpra/status","/api/xpra/presets","/api/xpra/sessions",
    "/api/xpra/sessions/unknown/view","/api/xpra/sessions/unknown/client/index.html",
    "/api/xpra/sessions/unknown/client/display.html","/api/xpra/sessions/unknown/client/ucagent.js"])
def test_all_feature_http_surfaces_require_cmd_auth(cmd_server, path):
    """No page, resource or API gains an exception to existing CMD protection."""
    with TestClient(cmd_server._app) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, auth=("user","wrong")).status_code == 401
        assert client.get("/docs").status_code == 200


def test_websocket_auth_origin_binary_and_browser_reconnect(cmd_server):
    """Authenticate upgrades, reject cross-origin access and preserve sessions."""
    session = cmd_server._xpra.create(sys.executable)
    path = f"/api/xpra/sessions/{session['id']}/client/"
    with TestClient(cmd_server._app) as client:
        for headers in ({}, {"authorization": aiohttp.BasicAuth("user", "wrong").encode()}):
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(path, headers=headers):
                    pass
            assert error.value.code == 4401
        client.auth = ("user", cmd_server.password)
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path, headers={"origin":"https://other.example"}):
                pass
        assert error.value.code == 4403
        for _ in range(2):
            with client.websocket_connect(path, subprotocols=["binary"], headers={"origin":"http://testserver"}) as ws:
                assert ws.accepted_subprotocol == "binary"
                ws.send_text("keyboard")
                assert ws.receive_text() == "keyboard"
                ws.send_bytes(b"pixels\x00\xff")
                assert ws.receive_bytes() == b"pixels\x00\xff"
        assert cmd_server._xpra.get(session["id"])["status"] == "running"


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_browser_grant_authenticates_only_the_owned_websocket(cmd_server, scheme):
    """Browsers may omit Basic on upgrades; scoped grants preserve API protection."""
    session = cmd_server._xpra.create(sys.executable)
    prefix = f"/api/xpra/sessions/{session['id']}"
    origin = scheme + "://testserver"
    websocket_url = ("wss" if scheme == "https" else "ws") + "://testserver" + prefix + "/client/"
    with TestClient(cmd_server._app, base_url=origin) as client:
        assert client.post(prefix+"/connect").status_code == 401
        grant = client.post(prefix+"/connect", auth=("user", cmd_server.password))
        assert grant.status_code == 204
        assert grant.headers["cache-control"] == "no-store"
        cookie = grant.headers["set-cookie"]
        assert f"Path={prefix}/client/" in cookie
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=300" in cookie
        assert ("Secure" in cookie) == (scheme == "https")
        assert cmd_server.password not in cookie
        token = client.cookies.get("ucagent_xpra_ws")
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(websocket_url):
                pass
        assert error.value.code == 4401
        with client.websocket_connect(websocket_url, headers={"origin":origin}) as ws:
            ws.send_bytes(b"browser-cookie\x00")
            assert ws.receive_bytes() == b"browser-cookie\x00"
        assert client.get("/api/xpra/sessions").status_code == 401
        assert client.post(prefix+"/connect").status_code == 401
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(websocket_url, headers={"origin":"https://elsewhere.example"}):
                pass
        assert error.value.code == 4403
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/api/xpra/sessions/"+"0"*32+"/client/", headers={
                    "origin":"http://testserver", "cookie":"ucagent_xpra_ws="+token}):
                pass
        assert error.value.code == 4401


@pytest.mark.parametrize("mutation", ["tampered", "expired", "future", "malformed", "restart"])
def test_browser_grants_reject_forgery_expiry_and_service_restart(cmd_server, monkeypatch, mutation):
    """Copied, malformed or stale connection grants must never become API credentials."""
    session = cmd_server._xpra.create(sys.executable)
    prefix = f"/api/xpra/sessions/{session['id']}"
    original_app = cmd_server._app
    with TestClient(original_app) as client:
        grant = client.get(prefix+"/view", auth=("user", cmd_server.password))
        assert "HttpOnly" in grant.headers["set-cookie"]
        token = client.cookies.get("ucagent_xpra_ws")
    if mutation == "tampered":
        token = token[:-1] + ("0" if token[-1] != "0" else "1")
    elif mutation == "expired":
        issued_at = time.time()
        monkeypatch.setattr("ucagent.server.api_cmd.transport.time.time", lambda: issued_at+301)
    elif mutation == "future":
        issued_at = time.time()
        monkeypatch.setattr("ucagent.server.api_cmd.transport.time.time", lambda: issued_at-600)
    elif mutation == "malformed":
        token = "not-a-signed-grant"
    if mutation == "restart":
        original_app = cmd_server._build_app()
    with TestClient(original_app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(prefix+"/client/", headers={
                    "origin":"http://testserver", "cookie":"ucagent_xpra_ws="+token}):
                pass
        assert error.value.code == 4401


def test_passwordless_cmd_policy_is_preserved(cmd_server):
    """A server built without a password also permits the new feature."""
    cmd_server.password = ""
    cmd_server._app = cmd_server._build_app()
    session = cmd_server._xpra.create(sys.executable)
    with TestClient(cmd_server._app) as client:
        assert client.get("/api/xpra/sessions").status_code == 200
        with client.websocket_connect(f"/api/xpra/sessions/{session['id']}/client/") as ws:
            ws.send_text("passwordless")
            assert ws.receive_text() == "passwordless"


@pytest.mark.parametrize("tcp", [True, False], ids=["tcp", "unix"])
def test_cmd_listeners_carry_real_xpra_upgrades(cmd_server, tcp):
    """Both actual Uvicorn backends must support the new binary transport."""
    with tempfile.TemporaryDirectory(prefix="uca-xws-", dir="/tmp") as directory:
        cmd_server.tcp = tcp
        cmd_server.sock = "" if tcp else directory + "/cmd.sock"
        session = cmd_server._xpra.create(sys.executable)
        ok, message = cmd_server.start()
        assert ok, message
        listener = cmd_server._tcp_server if tcp else cmd_server._sock_server
        _wait_for(lambda: listener.started)

        async def exchange():
            """Use the selected listener with HTTP Basic credentials and binary frames."""
            port = listener.servers[0].sockets[0].getsockname()[1] if tcp else 80
            connector = None if tcp else aiohttp.UnixConnector(path=cmd_server.sock)
            async with aiohttp.ClientSession(connector=connector, auth=aiohttp.BasicAuth("",cmd_server.password)) as client:
                async with client.ws_connect(f"http://127.0.0.1:{port}/api/xpra/sessions/{session['id']}/client/", protocols=["binary"]) as ws:
                    await ws.send_bytes(b"through-listener\x00")
                    assert (await ws.receive(timeout=3)).data == b"through-listener\x00"
        asyncio.run(exchange())


@pytest.mark.parametrize("kind", ["task", "agent"])
def test_master_http_and_ws_proxy_auth_prefix_and_credentials(cmd_server, tmp_path, kind):
    """Both Master proxies authenticate their caller and inject child credentials."""
    port = _start_listener(cmd_server)
    session = cmd_server._xpra.create(sys.executable)
    master = PdbMasterApiServer(workspace=str(tmp_path), host="127.0.0.1", port=0, sock="",
                                password="master-test-password", cfg=Config({"launch":{"file_browser_roots":[], "default_args": {}}}))
    child = dict(status="running",base_url_internal=f"http://127.0.0.1:{port}",password=cmd_server.password)
    master._tasks["test"] = dict(task_id="test",cmd_api=child,launch_mode="local")
    prefix = f"/{kind}/test/cmd/api/xpra"
    with TestClient(master._app, client=("127.0.0.1", 50000)) as client:
        registered = client.post("/api/register", json={
            "id": "test", "cmd_api_tcp": f"http://127.0.0.1:{port}",
            "cmd_api_password": cmd_server.password,
        })
        assert registered.status_code == 200
        assert cmd_server.password not in registered.text
        master._save_db()
        assert cmd_server.password not in Path(master._db_path).read_text()
        for path in ("/api/agents", "/api/agent/test"):
            response = client.get(path, auth=("user", master.password))
            assert response.status_code == 200
            assert cmd_server.password not in response.text
        assert client.get(prefix+"/sessions").status_code == 401
        assert client.get(prefix+"/presets").status_code == 401
        assert client.get(prefix+"/", auth=("user", "wrong")).status_code == 401
        for headers in ({}, {"authorization": aiohttp.BasicAuth("user", "wrong").encode()}):
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(prefix+f"/sessions/{session['id']}/client/", headers=headers):
                    pass
            assert error.value.code == 4401
        client.auth = ("user", master.password)
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(prefix+f"/sessions/{session['id']}/client/", headers={"origin":"https://other.example"}):
                pass
        assert error.value.code == 4403
        assert client.get(prefix+"/sessions").status_code == 200
        cmd_server.pdb.agent.cfg.cmd_api.xpra.from_dict({"presets": [{"label": "Proxy shortcut", "command": "codex", "mode": "console"}]})
        shortcut = client.get(prefix+"/presets")
        assert shortcut.status_code == 200
        assert shortcut.json()["presets"][0]["label"] == "Proxy shortcut"
        assert shortcut.json()["presets"][0]["command"] == "codex"
        assert client.get(prefix+"/").status_code == 200
        display_path = prefix+f"/sessions/{session['id']}/client/"
        redirect = client.get(display_path+"index.html", follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "../view"
        assert 'id="screen"' in client.get(display_path+"display.html").text
        assert "new XpraClient" in client.get(display_path+"ucagent.js").text
        asset = prefix+f"/sessions/{session['id']}/client/negotiated.html"
        compressed = client.get(asset, headers={"Accept-Encoding": "unsupported-test, gzip"})
        assert compressed.status_code == 200
        assert "Compressed client" in compressed.text
        assert "content-encoding" not in compressed.headers
        head = client.head(asset)
        assert head.status_code == 200
        assert head.headers["content-length"] == str(len(compressed.content))
        with client.websocket_connect(prefix+f"/sessions/{session['id']}/client/",subprotocols=["binary"],headers={"origin":"http://testserver"}) as ws:
            assert ws.accepted_subprotocol == "binary"
            ws.send_bytes(b"master-pixels")
            assert ws.receive_bytes() == b"master-pixels"
        granted = client.post(prefix+f"/sessions/{session['id']}/connect")
        assert granted.status_code == 204
        assert f"Path={prefix}/sessions/{session['id']}/client/" in granted.headers["set-cookie"]
        assert all(secret not in granted.headers["set-cookie"] for secret in (master.password, cmd_server.password))
        token = client.cookies.get("ucagent_xpra_ws")
        client.auth = None
        with client.websocket_connect(prefix+f"/sessions/{session['id']}/client/",headers={"origin":"http://testserver"}) as ws:
            ws.send_text("browser-through-master")
            assert ws.receive_text() == "browser-through-master"
        assert client.get(prefix+"/sessions").status_code == 401
        assert client.post(prefix+f"/sessions/{session['id']}/connect").status_code == 401
        other = "agent" if kind == "task" else "task"
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/{other}/test/cmd/api/xpra/sessions/{session['id']}/client/",headers={
                    "origin":"http://testserver", "cookie":"ucagent_xpra_ws="+token}):
                pass
        assert error.value.code == 4401
        # A heartbeat must replace a removed password as well as a set one.
        assert client.post("/api/register", json={
            "id": "test", "cmd_api_tcp": f"http://127.0.0.1:{port}",
            "cmd_api_password": "",
        }).status_code == 200
        assert master._agents["test"]["cmd_api_password"] == ""
    if master._proxy_session is not None:
        asyncio.run(master._proxy_session.close())


def test_simultaneous_tcp_and_unix_listeners_share_capacity(cmd_server):
    """Independent listener loops must reserve the same manager's single slot."""
    cmd_server._xpra.options["max_sessions"] = 1
    cmd_server._xpra.max_sessions = 1
    with tempfile.TemporaryDirectory(prefix="uca-xdual-", dir="/tmp") as directory:
        cmd_server.sock = directory + "/cmd.sock"
        port = _start_listener(cmd_server)
        _wait_for(lambda: cmd_server._sock_server.started)

        async def reserve():
            """Race real HTTP clients on each listener and compare their views."""
            auth = aiohttp.BasicAuth("", cmd_server.password)
            async with aiohttp.ClientSession(auth=auth) as tcp, aiohttp.ClientSession(
                auth=auth, connector=aiohttp.UnixConnector(path=cmd_server.sock)
            ) as unix:
                responses = await asyncio.gather(*(
                    client.post(url+"/api/xpra/sessions", json={"command": sys.executable,
                        "env": {"FAKE_BEHAVIOR": "slow"}})
                    for client, url in ((tcp, f"http://127.0.0.1:{port}"), (unix, "http://localhost"))))
                try:
                    assert sorted(response.status for response in responses) == [201, 409]
                    async with tcp.get(f"http://127.0.0.1:{port}/api/xpra/sessions") as response:
                        tcp_list = await response.json()
                    async with unix.get("http://localhost/api/xpra/sessions") as response:
                        assert await response.json() == tcp_list
                    assert tcp_list["active_count"] == 1
                finally:
                    for response in responses:
                        response.release()
        asyncio.run(reserve())


def test_terminal_console_and_xpra_remain_independent(cmd_server):
    """Three simultaneous services retain input/output when another is stopped."""
    port = _start_listener(cmd_server)
    session = cmd_server._xpra.create(sys.executable)
    console_input = []
    command = shlex.join([sys.executable, "-u", "-c",
                          "import sys; print('READY',flush=True); "
                          "\nfor line in sys.stdin: print('TERM:'+line.strip(),flush=True)"])
    terminal = PdbWebTermServer(command, host="127.0.0.1", port=0, password="terminal-test")
    console = PdbWebTermServer(host="127.0.0.1", port=0, password="console-test",
                               console_input_callback=console_input.append)
    try:
        assert terminal.start()[0]
        assert console.start()[0]
        terminal_port = terminal._site._server.sockets[0].getsockname()[1]
        console_port = console._site._server.sockets[0].getsockname()[1]

        async def receive_marker(websocket, marker):
            """Accumulate PTY chunks until the expected output has arrived."""
            result = b""
            async with asyncio.timeout(5):
                while marker not in result:
                    message = await websocket.receive()
                    assert message.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY)
                    result += message.data.encode() if isinstance(message.data, str) else message.data
            return result

        async def exchange():
            """Exercise keyboard events on all services before and after teardown."""
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(f"http://127.0.0.1:{terminal_port}/ws",auth=aiohttp.BasicAuth("","terminal-test")) as term_ws, \
                    client.ws_connect(f"http://127.0.0.1:{console_port}/ws",auth=aiohttp.BasicAuth("","console-test")) as console_ws, \
                    client.ws_connect(f"http://127.0.0.1:{port}/api/xpra/sessions/{session['id']}/client/",auth=aiohttp.BasicAuth("",cmd_server.password)) as xpra_ws:
                    await receive_marker(term_ws,b"READY")
                    await term_ws.send_str("first\n")
                    await receive_marker(term_ws,b"TERM:first")
                    await console_ws.send_str("console-first\r")
                    await receive_marker(console_ws,b"\r\n")
                    assert console_input == ["console-first"]
                    await xpra_ws.send_bytes(b"xpra-first")
                    assert (await xpra_ws.receive(timeout=3)).data == b"xpra-first"
                    await asyncio.to_thread(console.stop)
                    await xpra_ws.send_bytes(b"after-console-stop")
                    assert (await xpra_ws.receive(timeout=3)).data == b"after-console-stop"
                    await asyncio.to_thread(cmd_server._xpra.delete,session["id"])
                    await term_ws.send_str("after-xpra-delete\n")
                    await receive_marker(term_ws,b"TERM:after-xpra-delete")
                    assert terminal.is_running
        asyncio.run(exchange())
    finally:
        console.stop()
        terminal.stop()
