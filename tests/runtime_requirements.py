"""Preflight optional external runtimes without masking application test failures."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def require_commands(*names):
    """Resolve required executables, skipping before setup when any are absent."""
    commands = {name: shutil.which(name) for name in names}
    missing = [name for name, executable in commands.items() if executable is None]
    if missing:
        pytest.skip("Missing external tools: " + ", ".join(missing))
    return commands


def require_xpra_runtime(*extra_commands, tk=False):
    """Require Linux Xpra, its virtual display and HTML5 assets before live tests."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Real Xpra integration requires Linux/X11")
    commands = require_commands("xpra", "Xvfb", *extra_commands)
    try:
        probe = subprocess.run(
            [commands["xpra"], "--version"], capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("The installed Xpra executable cannot run")
    if probe.returncode:
        pytest.skip("The installed Xpra executable cannot report its version")
    if tk:
        pytest.importorskip("tkinter", reason="The graphical waveform fixture requires Tk")

    resources = os.environ.get("XPRA_RESOURCES_DIR")
    roots = [Path(resources)] if resources else [
        Path(commands["xpra"]).resolve().parent.parent / "share/xpra",
        Path(sys.prefix) / "share/xpra",
        Path("/usr/local/share/xpra"),
        Path("/usr/share/xpra"),
    ]
    if not any((root / "www/index.html").is_file() for root in roots):
        pytest.skip("Xpra HTML5 assets are unavailable; install xpra-html5 or set XPRA_RESOURCES_DIR")


def launch_browser(playwright, browser_kind, **options):
    """Skip absent browser installations or native libraries; propagate other failures."""
    browser_type = getattr(playwright, browser_kind)
    executable = options.get("executable_path")
    if executable and not shutil.which(str(executable)):
        pytest.skip(f"The Playwright {browser_kind} executable is unavailable")
    try:
        return browser_type.launch(headless=True, **options)
    except Exception as exc:
        # Playwright chooses its own binary for headless-only installations;
        # executable_path can point at a different, uninstalled full browser.
        # Only installation diagnostics qualify for a skip, never other crashes.
        if any(message in str(exc) for message in (
            "Executable doesn't exist at",
            "Host system is missing dependencies",
            "error while loading shared libraries",
            "Library not loaded:",
        )):
            pytest.skip(f"The Playwright {browser_kind} runtime dependencies are unavailable")
        raise
