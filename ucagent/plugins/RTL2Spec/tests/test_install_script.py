"""Check one-command installation orchestration without pip/network/native provisioning."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.sh"


@pytest.fixture
def recorder(tmp_path):
    """Supply a Python-command recorder that cannot install or fetch anything."""
    log = tmp_path / "commands.jsonl"
    python = tmp_path / "record python"
    python.write_text(f'''#!{sys.executable}
"""Record install-script subprocess arguments without performing their actions."""
import json, os, shlex, subprocess, sys
from pathlib import Path
with Path({str(log)!r}).open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
arguments = sys.argv[1:]
step = arguments[3] if len(arguments) > 3 and arguments[2] == "rtl2spec.fmagent" else "pip" if "pip" in arguments else "preflight"
if os.environ.get("FAIL_STEP") == step:
    sys.exit(7)
if step == "preflight":
    if os.environ.get("REAL_PREFLIGHT"):
        sys.exit(subprocess.run([sys.executable, *arguments], input=sys.stdin.read(), text=True).returncode)
    root = arguments[3] or "/fixture/root"
    python = (arguments[4] or "/fixture/python") if arguments[6] == "1" else root + "/.venv/bin/python"
    print("fmagent_root=" + shlex.quote(root))
    print("fmagent_python=" + shlex.quote(python))
''')
    python.chmod(0o755)
    return python, log


@pytest.mark.parametrize("skipped", [[], ["fetch"], ["install"], ["bind"], ["fetch", "install"], ["fetch", "bind"], ["install", "bind"], ["fetch", "install", "bind"]])
def test_install_script_orders_all_skip_combinations(tmp_path, recorder, skipped):
    """The selected interpreter performs pip and exactly the unskipped CLI actions in order."""
    python, log = recorder
    result = subprocess.run(["bash", str(SCRIPT), "--python", str(python), "--fmagent-root", str(tmp_path / "FM Agent"),
                             "--repo", "https://example.invalid/source", "--branch", "feature",
                             *[f"--skip-{item}" for item in skipped]], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert commands[0][:2] == ["-I", "-"]
    assert commands[1] == ["-I", "-m", "pip", "install", str(SCRIPT.parent.parent)]
    assert [command[3] for command in commands[2:]] == [item for item in ("fetch", "install", "bind") if item not in skipped]
    for command in commands[2:]:
        assert command[:3] == ["-I", "-m", "rtl2spec.fmagent"]
        assert command[command.index("--fmagent-root") + 1] == str(tmp_path / "FM Agent")
        if command[3] == "fetch":
            assert command[-4:] == ["--repo", "https://example.invalid/source", "--branch", "feature"]


def test_install_script_existing_interpreter_bind_only(recorder):
    """An explicit external interpreter only reaches bind and requires skipping install."""
    python, log = recorder
    result = subprocess.run(["bash", str(SCRIPT), "--python", str(python), "--skip-fetch", "--skip-install", "--fmagent-python", "/existing/python"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert commands[-1] == ["-I", "-m", "rtl2spec.fmagent", "bind", "--fmagent-root", "/fixture/root", "--fmagent-python", "/existing/python"]


@pytest.mark.parametrize("arguments", [["--fmagent-python", "/existing/python"], ["--branch"], ["--wrong"], ["--python", "/missing/python"]])
def test_install_script_parameter_errors_before_any_install(recorder, arguments):
    """Known syntax/conflict errors cannot partly install the package."""
    python, log = recorder
    result = subprocess.run(["bash", str(SCRIPT), "--python", str(python), *arguments], capture_output=True, text=True)
    assert result.returncode == 2
    assert not log.exists()


@pytest.mark.parametrize("step", ["pip", "fetch", "install", "bind"])
def test_install_script_stops_at_first_failure(recorder, step):
    """A failed pip/fetch/install never reaches later actions or retries; bind is last."""
    python, log = recorder
    result = subprocess.run(["bash", str(SCRIPT), "--python", str(python)], env={**os.environ, "FAIL_STEP": step}, capture_output=True, text=True)
    assert result.returncode == 7, result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert step in commands[-1]
    assert len(commands) == {"pip": 2, "fetch": 3, "install": 4, "bind": 5}[step]
    assert "no rollback or retry" in result.stderr


def test_install_script_checks_missing_preexisting_source_before_pip(tmp_path):
    """The real preflight can reject a skipped fetch without invoking package installation."""
    result = subprocess.run(["bash", str(SCRIPT), "--python", sys.executable, "--fmagent-root", str(tmp_path / "missing"), "--skip-fetch"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "FM-Agent source missing" in result.stderr
    assert "Stopped during preflight" in result.stderr


@pytest.mark.parametrize("skip_install", [False, True])
@pytest.mark.parametrize("explicit_root", [False, True])
def test_install_script_snapshots_root_and_actual_python(tmp_path, recorder, skip_install, explicit_root):
    """Real path selection is frozen and passed explicitly to every stubbed action."""
    python, log = recorder
    root = tmp_path / "selected 'root; $sentinel"
    arguments = ["--fmagent-root", str(root)] if explicit_root else []
    if skip_install:
        arguments.append("--skip-install")
    result = subprocess.run(
        ["bash", str(SCRIPT), "--python", str(python), *arguments],
        env={**os.environ, "REAL_PREFLIGHT": "1", "RTL2SPEC_FMAGENT_ROOT": str(root),
             "RTL2SPEC_FMAGENT_PYTHON": "/temporary/sentinel/python"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    for command in commands[2:]:
        assert command[command.index("--fmagent-root") + 1] == str(root)
    bind = commands[-1]
    expected_python = "/temporary/sentinel/python" if skip_install and not explicit_root else str(root / ".venv/bin/python")
    assert bind[3] == "bind"
    assert bind[bind.index("--fmagent-python") + 1] == expected_python
    assert "Selected root:" in result.stderr and "Selected python:" in result.stderr
    assert "will save these paths" in result.stderr
    assert "[argument]" in result.stderr if explicit_root else "[environment]" in result.stderr


@pytest.mark.parametrize("flag", ["-y", "--yes"])
def test_install_script_forwards_confirmation(recorder, flag):
    python, log = recorder
    result = subprocess.run(["bash", str(SCRIPT), "--python", str(python), flag], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    for command in commands[2:]:
        assert ("--yes" in command) == (command[3] in {"fetch", "install"})
