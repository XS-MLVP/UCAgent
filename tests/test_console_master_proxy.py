"""Exercise classified console reads through real CMD and both Master HTTP proxies."""

import re
import time
from urllib.parse import urljoin

import httpx
import pytest

from test_runtime_host import make_host
from ucagent.interfaces.server.api_cmd import ControlApiServer
from ucagent.interfaces.server.api_master import MasterApiServer
from ucagent.util.config import Config


@pytest.fixture
def console_servers(tmp_path, monkeypatch):
    """Run isolated authenticated listeners without starting a model or managed task process."""
    host, runtime = make_host(tmp_path / "agent")
    runtime.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    host.start()
    cmd = ControlApiServer(host.controller, registry=host.registry, operations=host.operations,
                           services=host.services, host_control=host, host="127.0.0.1", port=0,
                           sock="", password="child-secret")
    master = MasterApiServer(workspace=str(tmp_path / "master"), host="127.0.0.1", port=0,
                             sock="", password="master-secret",
                             cfg=Config({"launch": {"file_browser_roots": [str(tmp_path)]}}).freeze())
    try:
        assert cmd.start()[0]
        assert master.start()[0]
        # Only task lookup is supplied: forwarding, authentication, HTML and static
        # delivery all use the real servers. No launch queue or process is involved.
        task = {"id": "console-task", "cmd_api": {"status": "running", "tcp_url": cmd.url(),
                                                   "password": "child-secret"}}

        def get_task(task_id):
            """Resolve the one fixture task without fabricating a running child process."""
            if task_id != task["id"]:
                raise KeyError(task_id)
            return task

        monkeypatch.setattr(master, "_get_task", get_task)
        with master._agents_lock:
            master._agents["console-agent"] = {"id": "console-agent", "last_seen": time.time(),
                                              "cmd_api_tcp": cmd.url(), "cmd_api_password": "child-secret"}
        host.message_echo("MODEL_PROXY_OUTPUT")
        host.events.append("GET /api/status 200\n", view="system", source="http", kind="log")
        yield host, cmd, master
    finally:
        master.stop()
        cmd.stop()
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


@pytest.mark.parametrize("entry", ["direct", "task", "agent"])
def test_console_script_and_event_reads_share_the_mounted_cmd_prefix(console_servers, entry):
    """HTML rewrites static URLs only; each script must keep event reads inside its CMD mount."""
    host, cmd, master = console_servers
    prefix = {"direct": "", "task": "/task/console-task/cmd", "agent": "/agent/console-agent/cmd"}[entry]
    base = cmd.url() if entry == "direct" else master.url()
    password = "child-secret" if entry == "direct" else "master-secret"
    with httpx.Client(auth=("user", password), timeout=5) as client:
        response = client.get(base + prefix + "/")
        assert response.status_code == 200
        script_path = re.search(r'<script src="([^"]*/static/share/console-view.js)"', response.text).group(1)
        assert script_path == prefix + "/static/share/console-view.js"
        script = client.get(base + script_path)
        assert script.status_code == 200
        assert "new URL('../../api/events',scriptUrl).pathname" in script.text
        events_url = urljoin(base + script_path, "../../api/events")
        assert events_url == base + prefix + "/api/events"
        if entry != "direct":
            # This was the old component's erroneous request destination.
            assert client.get(base + "/api/events").status_code == 404
        page = client.get(events_url, params={"view": "activity"}).json()
        assert any("MODEL_PROXY_OUTPUT" in row["text"] for row in page["data"])
        assert not any(row["source"] == "http" for row in page["data"])
        host.message_echo("NEXT_PROXY_OUTPUT", end="")
        next_page = client.get(events_url, params={"view": "activity", "after": page["cursor"],
                                                   "generation": page["generation"]}).json()
        assert [row["text"] for row in next_page["data"]] == ["NEXT_PROXY_OUTPUT"]
        assert client.get(events_url, params={"view": "system"}).json()["data"]
        assert client.get(events_url, params={"view": "raw"}).json()["data"]
        assert client.get(events_url, params={"view": "activity", "tail": "true"}).json()["data"] == []
        assert client.get(events_url, params={"view": "activity"}).json()["data"]
        assert client.get(events_url, auth=("user", "wrong")).status_code == 401
