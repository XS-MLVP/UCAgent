"""Verify optional test runtimes skip on missing dependencies and preserve failures."""

import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import pytest

import runtime_requirements as requirements


def test_missing_commands_skip_before_setup(monkeypatch):
    """Report every missing command without attempting to start any runtime."""
    monkeypatch.setattr(requirements.shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception, match="xpra, Xvfb"):
        requirements.require_commands("xpra", "Xvfb")


def test_available_commands_return_resolved_paths(monkeypatch):
    """A present tool continues into its tests instead of being skipped."""
    monkeypatch.setattr(requirements.shutil, "which", lambda name: "/tools/" + name)
    assert requirements.require_commands("make", "node") == {
        "make": "/tools/make", "node": "/tools/node",
    }


@pytest.fixture
def xpra_installation(tmp_path, monkeypatch):
    """Represent a complete optional installation without running an X11 server."""
    monkeypatch.setattr(requirements.sys, "platform", "linux")
    monkeypatch.setattr(requirements.shutil, "which", lambda name: str(tmp_path / "bin" / name))
    monkeypatch.setenv("XPRA_RESOURCES_DIR", str(tmp_path))
    (tmp_path / "www").mkdir()
    (tmp_path / "www/index.html").write_text("<html></html>", encoding="utf-8")
    run = Mock(return_value=subprocess.CompletedProcess(["xpra", "--version"], 0))
    monkeypatch.setattr(requirements.subprocess, "run", run)
    return tmp_path, run


def test_xpra_skips_unsupported_platform_before_probing(monkeypatch):
    """Opting in on macOS must not try to start the Linux acceptance runtime."""
    monkeypatch.setattr(requirements.sys, "platform", "darwin")
    run = Mock()
    monkeypatch.setattr(requirements.subprocess, "run", run)
    with pytest.raises(pytest.skip.Exception, match="requires Linux"):
        requirements.require_xpra_runtime()
    run.assert_not_called()


def test_xpra_skips_missing_tools_before_probing(xpra_installation, monkeypatch):
    """A partial Xpra installation skips without starting any subprocess."""
    monkeypatch.setattr(requirements.shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception, match="xpra, Xvfb, xterm"):
        requirements.require_xpra_runtime("xterm")
    xpra_installation[1].assert_not_called()


@pytest.mark.parametrize("failure", [OSError("missing loader"), subprocess.TimeoutExpired("xpra", 5)])
def test_xpra_skips_unusable_binary(xpra_installation, failure):
    """An executable that cannot run is an absent optional runtime."""
    xpra_installation[1].side_effect = failure
    with pytest.raises(pytest.skip.Exception, match="cannot run"):
        requirements.require_xpra_runtime()


def test_xpra_skips_unsuccessful_version_probe(xpra_installation):
    """A broken Xpra installation must skip before workspace setup."""
    xpra_installation[1].return_value.returncode = 1
    with pytest.raises(pytest.skip.Exception, match="cannot report its version"):
        requirements.require_xpra_runtime()


def test_xpra_skips_missing_html5_assets(xpra_installation):
    """The Xpra binary alone cannot satisfy a graphical integration test."""
    (xpra_installation[0] / "www/index.html").unlink()
    with pytest.raises(pytest.skip.Exception, match="HTML5 assets are unavailable"):
        requirements.require_xpra_runtime()


def test_xpra_skips_missing_tk(xpra_installation, monkeypatch):
    """The waveform fixture needs Tk in the same Python interpreter as its app."""
    monkeypatch.setitem(sys.modules, "tkinter", None)
    with pytest.raises(pytest.skip.Exception, match="requires Tk"):
        requirements.require_xpra_runtime(tk=True)


def test_complete_xpra_installation_continues(xpra_installation):
    """A successful preflight leaves all application assertions enabled."""
    requirements.require_xpra_runtime("xterm")
    assert xpra_installation[1].call_args.kwargs["timeout"] == 5


def test_browser_skips_missing_executable():
    """Playwright's Python package alone must not enable a browser test."""
    browser_type = SimpleNamespace(executable_path="/missing-browser-for-ucagent", launch=Mock())
    with pytest.raises(pytest.skip.Exception, match="executable is unavailable"):
        requirements.launch_browser(
            SimpleNamespace(chromium=browser_type), "chromium", executable_path=browser_type.executable_path,
        )
    browser_type.launch.assert_not_called()


@pytest.mark.parametrize("message", [
    "Executable doesn't exist at /cache/playwright/headless_shell",
    "Host system is missing dependencies to run browsers.",
    "error while loading shared libraries: libgtk.so: cannot open shared object file",
    "Library not loaded: optional.dylib",
])
def test_browser_skips_missing_native_libraries(message):
    """Missing browser installations and unavailable native dependencies must skip."""
    browser_type = SimpleNamespace(executable_path=sys.executable, launch=Mock(side_effect=RuntimeError(message)))
    with pytest.raises(pytest.skip.Exception, match="runtime dependencies"):
        requirements.launch_browser(SimpleNamespace(webkit=browser_type), "webkit")


def test_browser_startup_regression_still_fails():
    """An unexpected browser crash is a failure, not an unavailable dependency."""
    browser_type = SimpleNamespace(executable_path=sys.executable, launch=Mock(side_effect=RuntimeError("browser crashed")))
    with pytest.raises(RuntimeError, match="browser crashed"):
        requirements.launch_browser(SimpleNamespace(chromium=browser_type), "chromium")


def test_browser_custom_executable_and_options_are_preserved():
    """Installed custom browsers must receive all test-specific launch options."""
    browser_type = SimpleNamespace(executable_path="/missing-browser-for-ucagent", launch=Mock())
    browser = requirements.launch_browser(
        SimpleNamespace(chromium=browser_type), "chromium", executable_path=sys.executable,
        args=["--enable-unsafe-swiftshader"],
    )
    assert browser is browser_type.launch.return_value
    browser_type.launch.assert_called_once_with(
        headless=True, executable_path=sys.executable, args=["--enable-unsafe-swiftshader"],
    )


def test_headless_shell_does_not_require_full_browser():
    """A working headless installation must not require the full Chromium binary."""
    browser_type = SimpleNamespace(executable_path="/missing-full-browser", launch=Mock())
    assert requirements.launch_browser(SimpleNamespace(chromium=browser_type), "chromium") is browser_type.launch.return_value
    browser_type.launch.assert_called_once_with(headless=True)


def test_docs_skip_partial_optional_installation(monkeypatch):
    """A base MkDocs installation without its site plugins cannot run site tests."""
    import test_docs_i18n as docs

    monkeypatch.setattr(docs.importlib.util, "find_spec", lambda name: None if name == "material" else object())
    with pytest.raises(unittest.SkipTest, match="missing: material"):
        docs.DocumentationLanguagesTest.setUpClass()


def test_usdb_skips_missing_reader_before_compiling(tmp_path, monkeypatch):
    """Configured UVS without UVD must skip before spending time on compilation."""
    import test_read_usdb
    from ucagent.util.waveform_formats import read_usdb

    home = tmp_path / "uvs"
    (home / "bin").mkdir(parents=True)
    simulator = home / "bin/uvs"
    simulator.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    simulator.chmod(0o755)
    monkeypatch.setenv("UVS_HOME", str(home))
    monkeypatch.setattr(read_usdb, "_find_tool", Mock(side_effect=read_usdb.UsdbRuntimeError("missing")))
    run = Mock()
    monkeypatch.setattr(test_read_usdb.subprocess, "run", run)
    with pytest.raises(pytest.skip.Exception, match="working usdbaccess"):
        test_read_usdb._build_usdb(tmp_path, "tb_xz.sv")
    run.assert_not_called()
