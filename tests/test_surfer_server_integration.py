#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import pytest

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
from ucagent.util.waveform_viewer import build_waveform_metadata, load_waveform_metadata, write_waveform_metadata
from ucagent.tools.waveform import WaveInfo


def _server(tmp_path: Path) -> PdbCmdApiServer:
    pdb = SimpleNamespace(
        agent=SimpleNamespace(workspace=str(tmp_path)),
        stdout=None,
    )
    return PdbCmdApiServer(pdb, sock="", tcp=True)


def test_surfer_adapter_and_readiness_command_are_served_before_wasm(tmp_path):
    server = _server(tmp_path)
    try:
        client = TestClient(server._app)
        page = client.get("/surfer/")
        adapter = client.get("/surfer/deep-link.js")
        fallback = client.get("/surfer/fst-fallback.js")
        worker = client.get("/surfer/fst-fallback-worker.js")
        converter = client.get("/surfer/fst-converter.wasm")
        readiness = client.get("/surfer/ucagent-wave-ready.sucl")

        assert page.status_code == 200
        assert adapter.status_code == 200
        assert fallback.status_code == 200
        assert worker.status_code == 200
        assert converter.status_code == 200
        assert converter.headers["content-type"] == "application/wasm"
        assert len(converter.content) > 100_000
        assert readiness.status_code == 200
        assert readiness.text.strip() == "divider_add __UCAGENT_WAVE_READY_V1__"
        for response in (page, adapter, fallback, worker, converter, readiness):
            assert response.headers["cross-origin-embedder-policy"] == "require-corp"
            assert response.headers["cross-origin-opener-policy"] == "same-origin"
            assert response.headers["cache-control"] == "no-store"
        surfer_wasm = client.get("/surfer/surfer_bg.wasm")
        assert surfer_wasm.status_code == 200
        assert "cache-control" not in surfer_wasm.headers
        assert page.text.index('src="deep-link.js"') < page.text.index(
            "await surfer.default"
        )
        assert page.text.index('src="fst-fallback.js"') < page.text.index(
            "UCAgentSurferFstFallback.prepareWaveform"
        )
        assert page.text.index("UCAgentSurferFstFallback.prepareWaveform") < page.text.index(
            "await import('./surfer.js')"
        )
        assert "prepareLocation(window.location, window.history)" in page.text
        assert 'id="ucagent_wave_progress_bar"' in page.text
        assert 'id="ucagent_wave_progress_percent"' in page.text

        head = client.head("/surfer/")
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["cross-origin-embedder-policy"] == "require-corp"
        assert head.headers["cross-origin-opener-policy"] == "same-origin"
    finally:
        server._running = True
        server.stop()



def test_dashboard_uses_metadata_and_configured_formats(tmp_path):
    """Browser actions and Markdown links share the canonical dispatch entry."""
    server = _server(tmp_path)
    try:
        page = TestClient(server._app).get("/")
        assert page.status_code == 200
        assert "/api/waveform/metadata" in page.text
        assert "/api/waveform/viewers" in page.text
        assert "_decorateWaveformViewerLinks(el);" in page.text
        assert 'anchor.target="_blank"' in page.text
        assert "encodePayload" not in page.text
    finally:
        server._running = True
        server.stop()


@pytest.mark.parametrize("extension", ["fst", "vcd", "fsdb"])
def test_metadata_dispatch_pins_the_selected_file(tmp_path, extension):
    """Ordinary opening preserves final configuration and selects the actual suffix."""
    wave = tmp_path / ("wave 空格." + extension)
    wave.write_bytes(b"exact waveform")
    server = _server(tmp_path)
    try:
        client = TestClient(server._app)
        response = client.post("/api/waveform/metadata", json={"waveform_file": wave.name})
        assert response.status_code == 200, response.text
        meta = response.json()["meta"]
        path = tmp_path / meta
        payload = load_waveform_metadata(tmp_path, meta)[1]
        payload.update(signals=["TOP.clk"], start="0", end="20", cursor="10")
        write_waveform_metadata(tmp_path, meta, payload)
        assert client.post("/api/waveform/metadata", json={"waveform_file": wave.name}).status_code == 200
        assert client.get("/api/waveform/metadata", params={"meta":meta}).json() == payload
        dispatch = client.get("/wave/", params={"meta":meta}, follow_redirects=False)
        if extension == "fsdb":
            assert dispatch.status_code == 200
            assert "../api/xpra/sessions" in dispatch.text
            assert server._waveform_launch.sessions == {}
        else:
            assert dispatch.status_code == 303
            assert dispatch.headers["location"].startswith("../surfer/?meta=")
        wave.unlink()
        missing = client.get("/wave/", params={"meta":meta})
        assert missing.status_code == 404
        assert missing.json()["detail"]["next_action"]
        assert client.get("/api/waveform/latest").status_code == 404
    finally:
        server._running = True
        server.stop()


def test_metadata_uses_selected_subworkspace(tmp_path):
    """Subworkspace files resolve against their own root and propagate to the viewer."""
    child = tmp_path / "child"
    (child / ".ucagent").mkdir(parents=True)
    (child / ".ucagent/ucagent_info.json").write_text("{}")
    (child / "a.fst").write_bytes(b"child")
    meta, payload, _ = build_waveform_metadata(child, "a.fst")
    write_waveform_metadata(child, meta, payload)
    server = _server(tmp_path)
    try:
        client = TestClient(server._app)
        response = client.get("/wave/", params={"meta":meta,"sub_worspace":"child"}, follow_redirects=False)
        assert response.status_code == 303
        assert "sub_worspace=child" in response.headers["location"]
        assert client.get("/api/waveform/metadata", params={"meta":meta}).status_code == 404
    finally:
        server._running = True
        server.stop()
