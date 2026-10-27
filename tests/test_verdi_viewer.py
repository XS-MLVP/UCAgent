"""Verdi routing, confined artifacts, launch lifecycle and safe playback contracts."""

from pathlib import Path
import shlex

from fastapi.testclient import TestClient
import pytest

from test_api_xpra import cmd_server, xpra_config
from ucagent.util.verdi import render_verdi_playback, tcl_string
from ucagent.util.waveform_viewer import (
    build_waveform_viewer_url, build_waveform_viewer_markdown_link,
    encode_waveform_viewer_payload, parse_waveform_viewer_markdown_link,
    WaveformViewerProtocolError,
)


@pytest.mark.parametrize("payload", [
    {"v": 1, "file": "waves/test.fsdb"},
    {"v": 2, "test_dir": "tests", "test_case": "test_bug", "viewer": "verdi"},
])
def test_verdi_links_roundtrip_and_reject_wrong_route(payload):
    """Viewer selection is canonical and cannot be changed without its payload."""
    link = build_waveform_viewer_markdown_link(payload)
    assert "/api/waveform/verdi?wave=" in link
    assert parse_waveform_viewer_markdown_link(link)[1] == payload
    with pytest.raises(WaveformViewerProtocolError):
        parse_waveform_viewer_markdown_link(link.replace("/api/waveform/verdi", "/surfer/"))
    assert build_waveform_viewer_url({"v": 1, "file": "waves/test.fst"}).startswith("/surfer/")


def test_playback_encodes_untrusted_strings_and_uses_file_time_unit(tmp_path):
    """No user string enters Tcl source as executable syntax or assumed ps units."""
    dangerous = 'TOP.bus[7:0]; [exec touch /tmp/should-not-exist]$x"{}\\'
    script = render_verdi_playback(tmp_path / "wave.fsdb", {
        "signals": [dangerous], "start": "0", "end": "30000", "cursor": "25000",
    }, tmp_path)
    assert dangerous not in script
    assert tcl_string("/" + dangerous.replace(".", "/")) in script
    assert "wvGetFileTimeUnit" in script and "wvGetWindowTimeUnit" in script
    assert "wvSetCursor" in script
    assert script.index("verdiSetPrefEnv -bUndockNewCreatedWindow off") < script.index("wvCreateWindow")
    assert "wvResizeWindow" not in script
    assert "srcResizeWindow 0 0 1200 850" in script


@pytest.mark.parametrize("version", [1, 2])
def test_verdi_api_launch_auth_reuse_and_shutdown(cmd_server, tmp_path, monkeypatch, version):
    """Authenticated launches retain playback assets and reuse ready instances."""
    waveform = tmp_path / "data/toffee_tmp_20261025000000_001/master/test_wave.fsdb"
    waveform.parent.mkdir(parents=True)
    waveform.write_bytes(b"fsdb")
    database = tmp_path / "design.daidir"
    database.mkdir()
    (database / "simv.kdb").write_text("KDB=TRUE\n")
    monkeypatch.setattr("ucagent.server.api_cmd.verdi_routes.shutil.which", lambda value: "/bin/verdi")
    calls = []

    def create(**kwargs):
        """A fake application confirms loading independently of Xpra readiness."""
        calls.append(kwargs)
        command = shlex.split(kwargs["command"])
        assert "-undockWin" not in command
        playback = Path(command[command.index("-play") + 1])
        (playback.parent / "ready.txt").write_text("ready")
        return {"id": "owned"}

    monkeypatch.setattr(cmd_server._xpra, "create", create)
    monkeypatch.setattr(cmd_server._xpra, "socket_path", lambda session: "socket")
    payload = {"v": 1, "file": waveform.relative_to(tmp_path).as_posix()} if version == 1 else {
        "v": 2, "test_dir": ".", "test_case": "test_wave", "viewer": "verdi"}
    token = encode_waveform_viewer_payload(payload)
    url = "/api/waveform/verdi?wave=" + token
    with TestClient(cmd_server._app) as client:
        assert client.post(url).status_code == 401
        client.auth = ("admin", cmd_server.password)
        assert client.get(url).status_code == 200
        assert not calls
        assert client.post(url).json() == {"viewer_path": "../xpra/sessions/owned/view"}
        assert client.post(url).status_code == 200
        assert len(calls) == 1
        assert client.get("/openapi.json").json()["paths"]["/api/waveform/verdi"]["post"]["responses"]
    playback = Path(shlex.split(calls[0]["command"])[-1])
    assert playback.exists()
    cmd_server.close_sessions()
    assert not playback.exists()


@pytest.mark.parametrize("condition,expected", [("missing", 404), ("no_kdb", 409), ("escape", 400),
                                               ("tcl_error", 502), ("timeout", 504), ("no_verdi", 503)])
def test_verdi_launch_failure_boundaries(cmd_server, tmp_path, monkeypatch, condition, expected):
    """Missing artifacts, escapes and failed playback never return a ready viewer."""
    monkeypatch.setattr("ucagent.server.api_cmd.verdi_routes.shutil.which", lambda value: None if condition == "no_verdi" else "/bin/verdi")
    if condition != "missing":
        (tmp_path / "wave.fsdb").write_bytes(b"fsdb")
    if condition == "escape":
        (tmp_path / "outside.fsdb").symlink_to("/etc/passwd")
    if condition in ("tcl_error", "timeout"):
        database = tmp_path / "design.daidir"
        database.mkdir()
        (database / "simv.kdb").write_text("KDB=TRUE")
    deleted = []

    def create(**kwargs):
        """Report a real application failure after transport startup."""
        playback = Path(shlex.split(kwargs["command"])[-1])
        if condition == "tcl_error":
            (playback.parent / "error.txt").write_text("Cannot add signal")
        return {"id": "failed"}

    monkeypatch.setattr(cmd_server._xpra, "create", create)
    monkeypatch.setattr(cmd_server._xpra, "delete", deleted.append)
    monkeypatch.setattr(cmd_server._xpra, "socket_path", lambda session: "socket")
    cmd_server.pdb.agent.cfg.cmd_api.xpra.from_dict({"startup_timeout": .01})
    token = encode_waveform_viewer_payload({"v": 1, "file": "outside.fsdb" if condition == "escape" else "wave.fsdb"})
    with TestClient(cmd_server._app) as client:
        response = client.post("/api/waveform/verdi?wave=" + token, auth=("admin", cmd_server.password))
        assert response.status_code == expected, response.text
    assert deleted == (["failed"] if condition in ("tcl_error", "timeout") else [])
