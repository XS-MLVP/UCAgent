"""Exercise task switches, native subprocess cleanup, preservation and raw export."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from pydantic import ValidationError

from rtl2spec import fmagent_workflow as workflow
from rtl2spec.fmagent_config import FMAgentPaths


@pytest.fixture
def project(tmp_path):
    """Create a non-Git generic input with independent outputs."""
    source = tmp_path / "inputs/Top"
    source.mkdir(parents=True)
    return source


def run_reuse(project):
    """Prepare existing artifacts without resolving a native environment."""
    return workflow.prepare(project.parents[1], "Top", "outputs", "generic",
                            workflow.FMAgentSettings(enabled=True, mode="reuse"))


@pytest.mark.parametrize("value", [{"enabled": "false"}, {"resume": 1}, {"isolate": 0},
                                   {"root": "/old"}, {"python": "/old"}, {"mode": "other"},
                                   {"mode": "reuse", "resume": True}, {"mode": "reuse", "isolate": True},
                                   {"submodule": "../escape"}, {"submodule": "/absolute"}, {"submodule": ""}])
def test_strict_settings(value):
    """Reject every unsupported or ambiguously typed option before any writes."""
    with pytest.raises(ValidationError):
        workflow.FMAgentSettings.model_validate(value)


@pytest.mark.parametrize("files", [{}, {"a_info.md": b"info"}, {"a_spec.md": b""},
                                   {"a_spec.md": b" \n\t"}, {"a/a_spec.md": b"arbitrary\x00\xff", "b/a_spec.md": b"other", "a_info.md": b"info", "source.scala": b"source"}])
def test_reuse_raw_export(project, monkeypatch, files):
    """Allow zero/blank/arbitrary specs and preserve bytes, nesting and optional info."""
    monkeypatch.setattr(workflow.fmagent_config, "resolve_paths", lambda: pytest.fail("reuse cannot resolve bindings"))
    monkeypatch.setattr(workflow.fmagent, "local_status", lambda *args: pytest.fail("reuse cannot probe environment"))
    extracted = project / "fm_agent/extracted_functions"
    extracted.mkdir(parents=True)
    for name, value in files.items():
        path = extracted / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    (project / ".codegraph").mkdir()
    history = project.parent / "Top.fm_agent_runs/old"
    history.mkdir(parents=True)
    prepared = run_reuse(project)
    assert not (project / "fm_agent").exists() and not (project / ".codegraph").exists()
    assert history.is_dir()
    assert not prepared["output"].exists()
    result = workflow.export_specs(prepared)
    expected = {name: value for name, value in files.items() if name.endswith("_spec.md")}
    assert result["spec_count"] == len(expected)
    exported = prepared["output"] / "specs"
    assert exported.is_dir()
    assert {path.relative_to(exported).as_posix(): path.read_bytes() for path in exported.rglob("*") if path.is_file()} == expected
    assert all("outputs-fmagent/" in name for name in prepared["references"])
    with pytest.raises(FileExistsError):
        workflow.export_specs(prepared)
    assert (prepared["native"] / "fm_agent").is_dir()


def test_reuse_missing_never_runs(project, monkeypatch):
    """Missing reuse artifacts fail without falling back to native execution."""
    monkeypatch.setattr(workflow.fmagent_config, "resolve_paths", lambda: pytest.fail("no run fallback"))
    with pytest.raises(ValueError, match="reuse requires"):
        run_reuse(project)
    assert not (project.parents[1] / "outputs-fmagent").exists()


@pytest.mark.parametrize("bad", ["outputs", "outputs-fmagent", "inputs/Top/nested"])
def test_output_protection(project, bad):
    """Reject stale outputs or project overlap while preserving all user data."""
    path = project.parents[1] / bad
    path.mkdir(parents=True, exist_ok=True)
    (path / "keep").write_text("keep")
    output = bad if bad != "outputs-fmagent" else "outputs"
    with pytest.raises((ValueError, FileExistsError)):
        workflow.workflow_paths(project.parents[1], "Top", output, "generic")
    assert (path / "keep").read_text() == "keep"


@pytest.mark.parametrize("name", ["fm_agent", ".codegraph"])
@pytest.mark.parametrize("shape", ["file", "symlink", "tracked"])
def test_runtime_path_protection(project, name, shape):
    """Never move redirected, non-directory or tracked runtime content."""
    source = project / name
    if shape == "file":
        source.write_text("keep")
    elif shape == "symlink":
        target = project / "target"
        target.mkdir()
        source.symlink_to(target, target_is_directory=True)
    else:
        source.mkdir()
        (source / "keep").write_text("tracked")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "add", name], check=True)
    with pytest.raises(ValueError):
        workflow.validate_runtime_dirs(project)
    assert source.exists()


def test_actual_git_root_overlap(project):
    """An input nested under a larger repository still requires outputs outside it."""
    subprocess.run(["git", "init", "-q", str(project.parents[1])], check=True)
    with pytest.raises(ValueError, match="overlaps"):
        workflow.workflow_paths(project.parents[1], "Top", "outputs", "generic")


def test_partial_move_and_no_replace(project, tmp_path):
    """An occupied destination preserves both it and its source, without rolling back another move."""
    native = tmp_path / "native"
    native.mkdir()
    for name in ("fm_agent", ".codegraph"):
        (project / name).mkdir()
        (project / name / "keep").write_text(name)
    (native / "fm_agent").mkdir()
    with pytest.raises(OSError, match="preserved locations"):
        workflow.move_runtime_dirs(project, native)
    assert (project / "fm_agent/keep").read_text() == "fm_agent"
    assert (native / "fm_agent").is_dir()
    assert not (project / ".codegraph").exists()
    assert (native / ".codegraph/keep").read_text() == ".codegraph"


@pytest.fixture
def native_stub(tmp_path, monkeypatch):
    """Provide a local executable main.py instead of any native model work."""
    root = tmp_path / "native source"
    root.mkdir()
    paths = FMAgentPaths(root=root, python=Path(sys.executable), root_source="test", python_source="test", local_config=tmp_path / "local.toml")
    monkeypatch.setattr(workflow.fmagent_config, "resolve_paths", lambda: paths)
    monkeypatch.setattr(workflow.fmagent, "local_status", lambda paths: ("ready", "stub"))
    return root


@pytest.mark.parametrize("exit_code", [0, 7])
def test_native_command_and_failure_preservation(project, native_stub, exit_code):
    """Forward every native option with isolated environment and preserve even failed output."""
    (project / "scope").mkdir()
    (native_stub / "main.py").write_text('''import json, os, pathlib, sys
project = pathlib.Path(sys.argv[1])
(project / 'fm_agent').mkdir()
(project / '.codegraph').mkdir()
(project / 'fm_agent/args.json').write_text(json.dumps({'args': sys.argv[2:], 'cwd': os.getcwd(), 'pythonpath': os.environ.get('PYTHONPATH')}))
print('stub pipeline')
sys.exit(''' + str(exit_code) + ''')
''')
    settings = workflow.FMAgentSettings(enabled=True, resume=True, isolate=True, submodule="scope")
    if exit_code:
        with pytest.raises(RuntimeError, match="status 7"):
            workflow.prepare(project.parents[1], "Top", "outputs", "generic", settings)
    else:
        workflow.prepare(project.parents[1], "Top", "outputs", "generic", settings)
    import json
    native = project.parents[1] / "outputs-fmagent"
    record = json.loads((native / "fm_agent/args.json").read_text())
    assert record == {"args": ["--plugin", "chip", "--only-spec", "--submodule", "scope", "--resume", "--isolate"],
                      "cwd": str(native_stub), "pythonpath": None}
    assert (native / ".codegraph").is_dir() and not (project / "fm_agent").exists()
    assert "stub pipeline" in (native / "pipeline.log").read_text()


def test_popen_failure_moves_existing_data(project, native_stub, monkeypatch):
    """A launch failure still preserves existing runtime directories."""
    (project / "fm_agent").mkdir()
    actual = subprocess.Popen

    def fail_native(args, **kwargs):
        """Fail only the native launch, allowing local Git inspection."""
        if str(native_stub / "main.py") in args:
            raise OSError("launch denied")
        return actual(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fail_native)
    with pytest.raises(OSError, match="launch denied"):
        workflow.prepare(project.parents[1], "Top", "outputs", "generic", workflow.FMAgentSettings(enabled=True))
    assert (project.parents[1] / "outputs-fmagent/fm_agent").is_dir()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cancel_stops_actual_descendant_writers(project, native_stub, tmp_path, signum):
    """Catch real signals, kill same-group writers, preserve data and restore handlers."""
    (native_stub / "main.py").write_text('''import pathlib, subprocess, sys, time
project = pathlib.Path(sys.argv[1])
(project / 'fm_agent').mkdir()
subprocess.Popen([sys.executable, '-c', "import pathlib,time; p=pathlib.Path(" + repr(str(project / 'fm_agent/writer')) + ");\\nwhile True: p.write_text(str(time.time())); time.sleep(.02)"])
(project / 'started').touch()
time.sleep(60)
''')
    driver = tmp_path / "driver.py"
    driver.write_text(f'''from pathlib import Path
import signal
from rtl2spec import fmagent_workflow as w
from rtl2spec.fmagent_config import FMAgentPaths
w.fmagent_config.resolve_paths = lambda: FMAgentPaths(root=Path({str(native_stub)!r}), python=Path({sys.executable!r}), root_source='test', python_source='test', local_config=Path('/unused'))
w.fmagent.local_status = lambda paths: ('ready', 'stub')
original = {{sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}}
try:
    w.prepare(Path({str(project.parents[1])!r}), 'Top', 'outputs', 'generic', w.FMAgentSettings(enabled=True))
except KeyboardInterrupt:
    assert all(signal.getsignal(sig) == handler for sig, handler in original.items())
    Path({str(tmp_path / 'cancelled')!r}).touch()
''')
    process = subprocess.Popen([sys.executable, str(driver)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (project / "started").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        assert (project / "started").exists()
        process.send_signal(signum)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, (stdout, stderr)
        assert (tmp_path / "cancelled").exists()
        writer = project.parents[1] / "outputs-fmagent/fm_agent/writer"
        assert not (project / "fm_agent").exists()
        previous = writer.read_bytes() if writer.exists() else None
        time.sleep(.1)
        assert (writer.read_bytes() if writer.exists() else None) == previous
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_export_partial_copy_failure(project, monkeypatch):
    """A copy error keeps the original set and partial export, refusing implicit retry."""
    extracted = project / "fm_agent/extracted_functions"
    extracted.mkdir(parents=True)
    for name in ("a_spec.md", "b_spec.md"):
        (extracted / name).write_text(name)
    prepared = run_reuse(project)
    original = workflow.shutil.copyfileobj
    calls = []

    def fail_second(reader, writer):
        """Simulate a disk failure after one successful spec copy."""
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk failure")
        return original(reader, writer)

    monkeypatch.setattr(workflow.shutil, "copyfileobj", fail_second)
    with pytest.raises(OSError, match="disk failure"):
        workflow.export_specs(prepared)
    assert (prepared["output"] / "specs/a_spec.md").read_text() == "a_spec.md"
    assert all(path.read_text() == path.name for path in prepared["specs"])
    with pytest.raises(FileExistsError):
        workflow.export_specs(prepared)


def test_unconfirmed_writers_prevent_migration(project, native_stub, monkeypatch):
    """Never rename data when writer shutdown cannot be confirmed."""
    (native_stub / "main.py").write_text("import pathlib,sys\n(pathlib.Path(sys.argv[1]) / 'fm_agent').mkdir()\n")

    def unconfirmed(process):
        """Simulate unavailable process inspection after the harmless stub has exited."""
        raise RuntimeError("writers unconfirmed")

    monkeypatch.setattr(workflow, "stop_writers", unconfirmed)
    with pytest.raises(RuntimeError, match="writers unconfirmed"):
        workflow.prepare(project.parents[1], "Top", "outputs", "generic", workflow.FMAgentSettings(enabled=True))
    assert (project / "fm_agent").is_dir()
    assert not (project.parents[1] / "outputs-fmagent/fm_agent").exists()


@pytest.mark.parametrize("name", ["outputs", "outputs-fmagent"])
def test_output_root_symlink_preserved(project, tmp_path, name):
    """Reject even workspace-local root redirection before touching runtime data."""
    target = tmp_path / "elsewhere"
    target.mkdir()
    alias = project.parents[1] / name
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        workflow.workflow_paths(project.parents[1], "Top", "outputs", "generic")
    assert alias.is_symlink() and list(target.iterdir()) == []
