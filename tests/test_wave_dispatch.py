"""Generic waveform dispatch, JSON confinement and owned viewer lifecycle."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from test_api_xpra import cmd_server, xpra_config
from ucagent.util.waveform_viewer import (
    build_waveform_viewer_markdown_link, decode_waveform_viewer_token,
    encode_waveform_viewer_payload, parse_waveform_viewer_markdown_link,
)


@pytest.mark.parametrize("extension", ["fst", "vcd", "fsdb"])
def test_wave_links_are_viewer_independent(extension):
    """Evidence selects artifacts, not programs or simulator-specific endpoints."""
    payload = {"v": 1, "file": f"wave.{extension}", "daidir": "design.daidir"}
    link = build_waveform_viewer_markdown_link(payload)
    assert "](/wave/?wave=" in link
    assert parse_waveform_viewer_markdown_link(link)[1] == payload


@pytest.mark.parametrize("use_file", [False, True])
def test_surfer_dispatch_does_not_launch_or_change_surfer(cmd_server, tmp_path, monkeypatch, use_file):
    """Both input forms resolve logical evidence before forwarding a vanilla v1 token."""
    waveform = tmp_path / "tests/data/toffee_tmp_20261025000000_001/master/test_case.fst"
    waveform.parent.mkdir(parents=True)
    waveform.touch()
    payload = {"v": 2, "test_dir": "tests", "test_case": "test_case", "daidir": "unused"}
    (tmp_path / "view.json").write_text(json.dumps(payload))
    monkeypatch.setattr(cmd_server._xpra, "create", lambda **kwargs: pytest.fail("Surfer must not launch Xpra"))
    query = {"config": "view.json"} if use_file else {"wave": encode_waveform_viewer_payload(payload)}
    with TestClient(cmd_server._app) as client:
        assert client.post("/wave/", params=query).status_code == 401
        client.auth = ("admin", cmd_server.password)
        assert client.get("/wave/", params=query).status_code == 200
        response = client.post("/wave/", params=query)
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["viewer_path"])
    assert url.path == "../surfer/"
    assert decode_waveform_viewer_token(parse_qs(url.query)["wave"][0]) == {
        "v": 1, "file": waveform.relative_to(tmp_path).as_posix()}


def test_gui_uses_trusted_command_json_reuse_and_cleanup(cmd_server, tmp_path, monkeypatch):
    """A custom tool works without adding simulator branches to the dispatcher."""
    (tmp_path / "wave.fsdb").touch()
    database = tmp_path / "design with spaces.daidir"
    database.mkdir()
    calls = []
    cmd_server.pdb.agent.cfg.cmd_api.from_dict({"wave": {"viewers": {
        "fsdb": {"viewer": "xpra", "command": ["custom-eda", "{file}", "{daidir}"]}}}})

    def create(**kwargs):
        """Emulate the configured script's explicit readiness handshake."""
        manifest = Path(shlex.split(kwargs["command"])[-1])
        calls.append(manifest)
        data = json.loads(manifest.read_text())
        assert data["command"] == ["custom-eda", str(tmp_path / "wave.fsdb"), str(database)]
        (manifest.parent / "ready.txt").touch()
        return {"id": "owned"}

    monkeypatch.setattr(cmd_server._xpra, "create", create)
    monkeypatch.setattr(cmd_server._xpra, "socket_path", lambda session: "socket")
    payload = {"v": 1, "file": "wave.fsdb", "daidir": database.name}
    with TestClient(cmd_server._app) as client:
        client.auth = ("admin", cmd_server.password)
        for _ in range(2):
            response = client.post("/wave/", params={"wave": encode_waveform_viewer_payload(payload)})
            assert response.json() == {"viewer_path": "../api/xpra/sessions/owned/view"}
        assert "/wave/" in client.get("/openapi.json").json()["paths"]
    assert len(calls) == 1 and calls[0].exists()
    cmd_server.close_sessions()
    assert not calls[0].exists()


@pytest.mark.parametrize("condition,expected", [
    ("missing", 404), ("escape", 400), ("json_escape", 400), ("db_escape", 400),
    ("db_link_escape", 400), ("ambiguous", 409), ("command", 400), ("both", 400),
    ("oversized", 400), ("tcl_error", 502), ("timeout", 504),
])
def test_dispatch_failures(cmd_server, tmp_path, monkeypatch, condition, expected):
    """Untrusted input cannot choose commands, escape the workspace or leak failed sessions."""
    if condition != "missing":
        (tmp_path / "wave.fsdb").touch()
    payload = {"v": 1, "file": "wave.fsdb"}
    if condition == "escape":
        (tmp_path / "wave.fsdb").unlink()
        (tmp_path / "wave.fsdb").symlink_to("/etc/passwd")
    if condition in ("db_escape", "db_link_escape"):
        database = tmp_path / "design"
        if condition == "db_escape":
            database.symlink_to("/etc", target_is_directory=True)
        else:
            database.mkdir()
            (database / "simv.kdb").symlink_to("/etc/passwd")
        payload["daidir"] = "design"
    if condition in ("tcl_error", "timeout"):
        database = tmp_path / "design.daidir"
        database.mkdir()
        (database / "simv.kdb").write_text("KDB=TRUE")
    if condition == "command":
        payload["command"] = ["untrusted"]
    manifest = tmp_path / "view.json"
    if condition == "json_escape":
        manifest.symlink_to("/etc/passwd")
    else:
        manifest.write_text(" " * 65537 if condition == "oversized" else json.dumps(payload))
    deleted = []

    def create(**kwargs):
        """Emulate startup without assuming transport readiness means application readiness."""
        output = Path(shlex.split(kwargs["command"])[-1]).parent
        if condition == "tcl_error":
            (output / "error.txt").write_text("Cannot add signal")
        return {"id": "failed"}

    monkeypatch.setattr(cmd_server._xpra, "create", create)
    monkeypatch.setattr(cmd_server._xpra, "delete", deleted.append)
    monkeypatch.setattr(cmd_server._xpra, "socket_path", lambda session: "socket")
    cmd_server.pdb.agent.cfg.cmd_api.xpra.from_dict({"startup_timeout": .01})
    query = {"config": "view.json"}
    if condition == "both":
        query["wave"] = encode_waveform_viewer_payload({"v": 1, "file": "wave.fsdb"})
    with TestClient(cmd_server._app) as client:
        response = client.post("/wave/", params=query, auth=("admin", cmd_server.password))
    assert response.status_code == expected, response.text
    assert deleted == (["failed"] if condition in ("tcl_error", "timeout") else [])


def test_launcher_preserves_json_as_data(tmp_path):
    """The simulator-neutral adapter hex-encodes special characters for Tcl."""
    script = Path(__file__).parents[1] / "ucagent/scripts/sim/launch.py"
    value = 'TOP.bus[7:0]; [exec touch /tmp/never-create-this]$x"{}\\'
    manifest = tmp_path / "wave.json"
    manifest.write_text(json.dumps({"file": value, "signals": [value],
                                    "command": [sys.executable, "-c", "pass"]}))
    subprocess.run([sys.executable, str(script), str(manifest)], check=True)
    data = (tmp_path / "data.tcl").read_text()
    assert value not in data
    assert value.encode().hex() in data
    manifest.write_text(json.dumps({"command": ["/nonexistent/tool"]}))
    assert subprocess.run([sys.executable, str(script), str(manifest)], capture_output=True).returncode != 0
    assert (tmp_path / "error.txt").is_file()


@pytest.mark.parametrize("parameter", ["sub_workspace", "sub_worspace"])
def test_subworkspace_forwarding(cmd_server, tmp_path, parameter):
    """A redirected Surfer token keeps its resolved child-workspace context."""
    child = tmp_path / "child"
    (child / ".ucagent").mkdir(parents=True)
    (child / ".ucagent/ucagent_info.json").write_text("{}")
    (child / "wave.fst").touch()
    query = {parameter: "child", "wave": encode_waveform_viewer_payload({"v": 1, "file": "wave.fst"})}
    with TestClient(cmd_server._app) as client:
        response = client.post("/wave/", params=query, auth=("admin", cmd_server.password))
    assert response.status_code == 200, response.text
    assert parse_qs(urlsplit(response.json()["viewer_path"]).query)["sub_worspace"] == ["child"]
