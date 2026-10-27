"""Opt-in browser acceptance against the bundled Surfer WASM and real CMD service.

Run with UCAGENT_RUN_SURFER_BROWSER_TESTS=1 and installed Playwright browsers.
UCAGENT_SURFER_CHROMIUM_EXECUTABLE may select an installed Chrome executable.
"""

import io
import os
import re
import socket
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from ucagent.server.api_cmd import PdbCmdApiServer
from ucagent.util import waveform_viewer


pytestmark = pytest.mark.skipif(
    os.environ.get("UCAGENT_RUN_SURFER_BROWSER_TESTS") != "1",
    reason="Requires opt-in Playwright browsers with WebGL support",
)


@pytest.mark.parametrize("browser_kind", ["chromium", "webkit"])
@pytest.mark.parametrize("extension,analysis_window", [("vcd", True), ("fst", False)])
def test_metadata_populates_variables_and_uses_full_names(
    browser_kind, extension, analysis_window, tmp_path, monkeypatch,
):
    """Render real bus bits, default collapse, independent expansion and Variables rows."""
    playwright_api = pytest.importorskip("playwright.sync_api")
    image_api = pytest.importorskip("PIL.Image")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(waveform_viewer, "_METADATA_KEY_DIRECTORY", tmp_path / "keys")
    wave = workspace / ("wave 空格." + extension)
    changes = [(0, ("0", "0000", "0001")), (10, ("1", "0101", "0001")),
               (20, ("0", "0101", "1111")), (30, ("1", "1010", "1111")),
               (40, ("0", "1010", "1111"))]
    if wave.suffix == ".vcd":
        header = ("$timescale 1ns $end\n$scope module TOP $end\n$scope module Adder $end\n"
                  '$var wire 1 ! clk $end\n$var wire 4 " sum [3:0] $end\n'
                  '$var wire 4 $ zbus [7:4] $end\n$upscope $end\n'
                  "$scope module Other $end\n$var wire 4 # sum [3:0] $end\n"
                  "$upscope $end\n$upscope $end\n$enddefinitions $end\n")
        wave.write_text(header + "".join(
            f'#{stamp}\n{clock}!\nb{left} "\nb0101 $\nb{right} #\n'
            for stamp, (clock, left, right) in changes), encoding="ascii")
    else:
        pylibfst = pytest.importorskip("pylibfst")
        ffi, lib = pylibfst.ffi, pylibfst.lib
        writer = lib.fstWriterCreate(os.fsencode(wave), 1)
        assert writer != ffi.NULL
        try:
            lib.fstWriterSetTimescale(writer, -9)
            lib.fstWriterSetScope(writer, lib.FST_ST_VCD_MODULE, b"TOP", ffi.NULL)
            lib.fstWriterSetScope(writer, lib.FST_ST_VCD_MODULE, b"Adder", ffi.NULL)
            handles = [lib.fstWriterCreateVar(writer, lib.FST_VT_VCD_WIRE, lib.FST_VD_IMPLICIT,
                                            width, name, 0)
                       for width, name in [(1, b"clk"), (4, b"sum [3:0]")]]
            extra_bus = lib.fstWriterCreateVar(writer, lib.FST_VT_VCD_WIRE,
                                               lib.FST_VD_IMPLICIT, 4, b"zbus [7:4]", 0)
            lib.fstWriterSetUpscope(writer)
            lib.fstWriterSetScope(writer, lib.FST_ST_VCD_MODULE, b"Other", ffi.NULL)
            handles.append(lib.fstWriterCreateVar(writer, lib.FST_VT_VCD_WIRE,
                                                  lib.FST_VD_IMPLICIT, 4, b"sum [3:0]", 0))
            lib.fstWriterSetUpscope(writer)
            lib.fstWriterSetUpscope(writer)
            for stamp, values in changes:
                lib.fstWriterEmitTimeChange(writer, stamp)
                lib.fstWriterEmitValueChange(writer, extra_bus, ffi.new("char[]", b"0101"))
                for handle, value in zip(handles, values):
                    lib.fstWriterEmitValueChange(writer, handle, ffi.new("char[]", value.encode()))
        finally:
            lib.fstWriterClose(writer)
    meta, payload, _ = waveform_viewer.build_waveform_metadata(workspace, wave.name)
    payload["signals"] = ["TOP.Adder.clk", "TOP.Adder.sum[3:0]", "TOP.Other.sum[3:0]"]
    if analysis_window:
        payload.update(start="10", end="30", cursor="20")
    waveform_viewer.write_waveform_metadata(workspace, meta, payload)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = PdbCmdApiServer(SimpleNamespace(
        agent=SimpleNamespace(workspace=str(workspace)), stdout=None,
    ), host="127.0.0.1", port=port, sock="")
    try:
        ok, message = server.start()
        assert ok, message
        deadline = time.monotonic() + 10
        while not server._tcp_server.started:
            assert time.monotonic() < deadline, message
            time.sleep(0.05)
        with playwright_api.sync_playwright() as playwright:
            options = {}
            if browser_kind == "chromium":
                options["args"] = ["--enable-unsafe-swiftshader"]
                executable = os.environ.get("UCAGENT_SURFER_CHROMIUM_EXECUTABLE")
                if executable:
                    options["executable_path"] = executable
            browser = getattr(playwright, browser_kind).launch(headless=True, **options)
            context = browser.new_context(viewport={"width": 1440, "height": 950}, service_workers="block")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(f"http://127.0.0.1:{port}/wave/?" + urlencode({"meta": meta}))
                page.wait_for_function("typeof window.id_of_name === 'function'", timeout=45000)
                deadline = time.monotonic() + 45
                while True:
                    state = page.evaluate("async () => await (await import('./surfer.js')).get_state()")
                    if state and state.count("display_name_type: Global") == 3 and (
                        not analysis_window or "cursor: Some" in state
                    ):
                        break
                    assert time.monotonic() < deadline, state
                    page.wait_for_timeout(50)
                (tmp_path / "surfer-state.ron").write_text(state, encoding="utf-8")
                assert re.search(r'active_scope: Some\(WaveScope\(\(\s*strs: \[\s*"TOP",\s*"Adder",', state)
                assert state.count("display_name_type: Global") == 3
                assert 'display_name: "TOP.Adder.clk"' in state
                assert 'display_name: "TOP.Adder.sum [3:0]"' in state
                assert 'display_name: "TOP.Other.sum [3:0]"' in state
                assert "default_variable_name_type: Global" in state
                assert "…" not in state
                if analysis_window:
                    assert re.search(r"cursor: Some\(\(1, \[\s*20,", state)
                    assert "curr_left: (0.25)" in state
                    assert "curr_right: (0.75)" in state
                else:
                    assert "cursor: None" in state
                page.locator("#ucagent_wave_progress").wait_for(state="hidden")
                loaded = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-loaded.png")))).convert("RGB")
                # A closed bus leaves no child traces below the three root signals.
                assert loaded.getpixel((750, 138)) == (11, 21, 29)
                page.mouse.click(316, 96, delay=100)
                page.wait_for_timeout(300)
                expanded = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-expanded.png")))).convert("RGB")
                # The four actual digital waveforms show 0101 at both tested time windows.
                assert [expanded.getpixel((750, y)) for y in (117, 138, 159, 180)] == [
                    (11, 21, 29), (39, 69, 44), (27, 37, 45), (39, 69, 44),
                ]
                # The second bus is still closed until its own arrow is clicked.
                assert expanded.getpixel((750, 222)) == (11, 21, 29)
                page.mouse.click(316, 201, delay=100)
                page.wait_for_timeout(300)
                both = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-both-buses.png")))).convert("RGB")
                assert both.getpixel((750, 285)) == (39, 69, 44)
                page.mouse.click(316, 201, delay=100)
                page.mouse.click(316, 96, delay=100)
                page.wait_for_timeout(300)
                collapsed = image_api.open(io.BytesIO(page.screenshot())).convert("RGB")
                assert collapsed.getpixel((750, 138)) == (11, 21, 29)
                # Surfer is canvas-rendered. Clicking a real Variables row proves it is present.
                # The fixed viewport places the first row below the Variables header and filter.
                page.mouse.click(40, 570, delay=100)
                deadline = time.monotonic() + 10
                while True:
                    state = page.evaluate("async () => await (await import('./surfer.js')).get_state()")
                    if state.count("display_name_type: Global") == 4:
                        break
                    assert time.monotonic() < deadline, state
                    page.wait_for_timeout(50)
                assert state.count('display_name: "TOP.Adder.clk"') == 2
                # A bus added through Variables also starts closed and exposes native bit rows.
                page.mouse.click(40, 611, delay=100)
                deadline = time.monotonic() + 10
                while True:
                    state = page.evaluate("async () => await (await import('./surfer.js')).get_state()")
                    if state.count("display_name_type: Global") == 5:
                        break
                    assert time.monotonic() < deadline, state
                    page.wait_for_timeout(50)
                manual = image_api.open(io.BytesIO(page.screenshot())).convert("RGB")
                assert manual.getpixel((750, 180)) == (11, 21, 29)
                page.mouse.click(316, 159, delay=100)
                page.wait_for_timeout(300)
                manual = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-manual-bus.png")))).convert("RGB")
                assert [manual.getpixel((750, y))[1] - manual.getpixel((750, y))[0] > 10
                        for y in (180, 201, 222, 243)] == [False, True, False, True]
                # Changing the parent format must keep the native bit values available.
                page.evaluate("""async () => {
                    const surfer = await import('./surfer.js');
                    const item = await surfer.id_of_name('TOP.Adder.sum');
                    surfer.inject_message(JSON.stringify({VariableFormatChange: [
                        {Explicit: {item, field: []}}, 'Binary',
                    ]}));
                }""")
                page.wait_for_timeout(300)
                state = page.evaluate("async () => await (await import('./surfer.js')).get_state()")
                assert 'format: Some("Binary")' in state
                page.mouse.click(316, 96, delay=100)
                page.wait_for_timeout(300)
                binary = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-binary-bus.png")))).convert("RGB")
                assert [binary.getpixel((750, y))[1] - binary.getpixel((750, y))[0] > 10
                        for y in (117, 138, 159, 180)] == [False, True, False, True]
                page.mouse.click(316, 96, delay=100)
                page.wait_for_timeout(300)
                page.mouse.click(316, 159, delay=100)
                page.wait_for_timeout(300)
                # Repeated instances of the same signal must not share the widget identity.
                page.mouse.click(40, 590, delay=100)
                deadline = time.monotonic() + 10
                while True:
                    state = page.evaluate("async () => await (await import('./surfer.js')).get_state()")
                    if state.count("display_name_type: Global") == 6:
                        break
                    assert time.monotonic() < deadline, state
                    page.wait_for_timeout(50)
                page.mouse.click(316, 180, delay=100)
                page.wait_for_timeout(300)
                duplicate = image_api.open(io.BytesIO(page.screenshot(
                    path=str(tmp_path / f"{browser_kind}-{extension}-duplicate-bus.png")))).convert("RGB")
                assert [duplicate.getpixel((750, y))[1] - duplicate.getpixel((750, y))[0] > 10
                        for y in (201, 222, 243, 264)] == [False, True, False, True]
                assert duplicate.getpixel((750, 138)) == (39, 69, 44)
                # The waveform name column remains natively resizable for long full paths.
                page.mouse.move(399, 250)
                page.mouse.down()
                page.mouse.move(650, 250, steps=10)
                page.mouse.up()
                page.screenshot(path=str(tmp_path / f"{browser_kind}-{extension}-signals.png"))
                assert page.locator("#error_message").inner_text() == ""
                assert errors == []
            finally:
                context.close()
                browser.close()
    finally:
        thread = server._tcp_thread
        server.stop()
        if thread is not None:
            thread.join(timeout=5)
