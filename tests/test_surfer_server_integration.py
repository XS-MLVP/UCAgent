#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys

from fastapi.testclient import TestClient

repo_root = str(Path(__file__).resolve().parents[1])
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)
loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(
    repo_package_root + os.sep
):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.util.waveform_viewer import encode_waveform_viewer_payload


def _server(tmp_path: Path) -> PdbCmdApiServer:
    pdb = SimpleNamespace(
        agent=SimpleNamespace(workspace=str(tmp_path)),
        stdout=None,
    )
    return PdbCmdApiServer(pdb, sock="", tcp=True)


def _logical_token(test_dir: str = "unity_test/tests", test_case: str = "test_bug") -> str:
    return encode_waveform_viewer_payload(
        {
            "v": 2,
            "test_dir": test_dir,
            "test_case": test_case,
            "start": "0",
            "end": "10",
            "cursor": "5",
            "signals": ["TOP.dut.valid"],
        }
    )


def _waveform(workspace: Path, session: str, name: str, content: bytes) -> Path:
    path = workspace / "unity_test" / "tests" / "data" / session / "master" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_surfer_adapter_and_readiness_command_are_served_before_wasm(tmp_path):
    server = _server(tmp_path)
    try:
        client = TestClient(server._app)
        page = client.get("/surfer/")
        adapter = client.get("/surfer/deep-link.js")
        readiness = client.get("/surfer/ucagent-wave-ready.sucl")

        assert page.status_code == 200
        assert adapter.status_code == 200
        assert readiness.status_code == 200
        assert readiness.text.strip() == "divider_add __UCAGENT_WAVE_READY_V1__"
        assert page.text.index('src="deep-link.js"') < page.text.index(
            "await surfer.default"
        )
        assert "prepareLocation(window.location, window.history)" in page.text
    finally:
        server._running = True
        server.stop()


def test_dashboard_wave_and_markdown_links_use_versioned_protocol(tmp_path):
    server = _server(tmp_path)
    try:
        page = TestClient(server._app).get("/")

        assert page.status_code == 200
        assert '<script src="/surfer/deep-link.js"></script>' in page.text
        assert "UCAgentSurferDeepLink.encodePayload({v:1,file:path})" in page.text
        assert "_decorateWaveformViewerLinks(el);" in page.text
        assert 'anchor.target="_blank"' in page.text
        assert 'anchor.rel="noopener noreferrer"' in page.text
        assert "load_url=" not in page.text
    finally:
        server._running = True
        server.stop()


def test_latest_waveform_api_resolves_newest_session_containing_target(tmp_path):
    old = _waveform(
        tmp_path,
        "toffee_tmp_20260817120000_001",
        "test_bug.fst",
        b"old target",
    )
    expected = _waveform(
        tmp_path,
        "toffee_tmp_20260817130000_001",
        "test_bug010.fst",
        b"new target",
    )
    _waveform(
        tmp_path,
        "toffee_tmp_20260817140000_001",
        "test_other.fst",
        b"newest unrelated",
    )
    server = _server(tmp_path)
    try:
        response = TestClient(server._app).get(
            "/api/waveform/latest",
            params={"wave": _logical_token()},
        )

        assert response.status_code == 200
        assert response.content == expected.read_bytes()
        assert response.content != old.read_bytes()
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-ucagent-waveform-path"].endswith(
            "/toffee_tmp_20260817130000_001/master/test_bug010.fst"
        )
    finally:
        server._running = True
        server.stop()


def test_latest_waveform_api_reports_missing_target(tmp_path):
    _waveform(
        tmp_path,
        "toffee_tmp_20260817140000_001",
        "test_other.fst",
        b"other",
    )
    server = _server(tmp_path)
    try:
        response = TestClient(server._app).get(
            "/api/waveform/latest",
            params={"wave": _logical_token(test_case="test_missing")},
        )

        assert response.status_code == 404
        assert "test_missing" in response.json()["detail"]
        assert "Run that test" in response.json()["detail"]
    finally:
        server._running = True
        server.stop()


def test_latest_waveform_api_uses_selected_sub_workspace(tmp_path):
    child = tmp_path / "child"
    info = child / ".ucagent" / "ucagent_info.json"
    info.parent.mkdir(parents=True)
    info.write_text("{}", encoding="utf-8")
    expected = _waveform(
        child,
        "toffee_tmp_20260817140000_001",
        "test_bug.fst",
        b"child wave",
    )
    _waveform(
        tmp_path,
        "toffee_tmp_20260817150000_001",
        "test_bug.fst",
        b"root wave",
    )
    server = _server(tmp_path)
    try:
        response = TestClient(server._app).get(
            "/api/waveform/latest",
            params={"wave": _logical_token(), "sub_worspace": "child"},
        )

        assert response.status_code == 200
        assert response.content == expected.read_bytes()
    finally:
        server._running = True
        server.stop()
