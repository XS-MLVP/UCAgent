"""Installer boundary tests use no network and never mutate an existing real environment."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("legacy_present", [False, True])
def test_installer_filters_legacy_and_refuses_an_existing_legacy_venv(tmp_path, monkeypatch, legacy_present):
    """Filtering accepts requirement spelling variants and preflight protects old environments."""
    script_path = Path(__file__).resolve().parents[1] / "scripts/setup_env.py"
    spec = importlib.util.spec_from_file_location("setup_toffee_ut_test", script_path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    source = tmp_path / "source"
    marker = source / "ucagent/core/plugins.py"
    marker.parent.mkdir(parents=True)
    marker.write_text('"""Source-checkout marker, not imported."""\n')
    (source / "requirements.txt").write_text("pytoffee @ git+https://invalid.test/legacy\nTOFFEE_TEST >= 1\nPyYAML>=6,<7\n")
    plugin = source / "ucagent/plugins/ToffeeUT"
    plugin.mkdir(parents=True)
    (plugin / "requirements.txt").write_text("uc-toffee[runner]\n")
    environment = plugin / ".venv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("# Pre-existing controlled test fixture\n")
    purelib = environment / "lib"
    purelib.mkdir()
    installed = []

    def run(command, **kwargs):
        """Capture install input while replacing every external command with a controlled result."""
        if "distributions;" in command[-1]:
            return subprocess.CompletedProcess(command, int(legacy_present))
        if "-r" in command:
            installed.append(Path(command[command.index("-r") + 1]).read_text())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(script, "__file__", str(plugin / "scripts/setup_env.py"))
    monkeypatch.setattr(script.subprocess, "run", run)
    monkeypatch.setattr(script.subprocess, "check_output", lambda *args, **kwargs: str(purelib))
    monkeypatch.setattr(sys, "argv", [str(script_path), "--ucagent", str(source), "--venv", str(environment)])
    if legacy_present:
        with pytest.raises(SystemExit) as raised:
            script.main()
        assert raised.value.code == 2 and not installed
        assert not (purelib / "ucagent-source.pth").exists()
    else:
        script.main()
        assert len(installed) == 1
        assert "pytoffee" not in installed[0].lower() and "toffee_test" not in installed[0].lower()
        assert "uc-toffee[runner]" in installed[0]
        assert (purelib / "ucagent-source.pth").read_text() == str(source) + "\n"
