"""Exercise independent FM-Agent actions with local Git and native-command fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys

import tomllib
import pytest

from rtl2spec import fmagent, fmagent_config
from rtl2spec.fmagent_config import FMAgentPaths, resolve_paths
from rtl2spec.launch import main as launch


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Resolve into temporary source and plugin directories, never real installations."""
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    monkeypatch.setattr(fmagent_config, "plugin_source_root", lambda: plugin)
    monkeypatch.setattr(fmagent, "plugin_source_root", lambda: plugin)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_ROOT", raising=False)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_PYTHON", raising=False)
    return resolve_paths(str(tmp_path / "FM Agent"))


def source(root):
    """Create the native source shape without dependencies or model configuration."""
    root.mkdir(parents=True, exist_ok=True)
    for name in fmagent.SOURCE_FILES:
        (root / name).write_text("# fixture\n")


def git(root, *arguments):
    """Run local-only Git fixture operations without parent Git environment selection."""
    return subprocess.run(["git", "-C", str(root), *arguments], env=fmagent.isolated_environment(),
                          text=True, capture_output=True, check=True).stdout.strip()


def checkout(root):
    """Build a local committed FM-Agent-shaped checkout with no remote network calls."""
    source(root)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


def test_fetch_clones_only_and_reuses_without_touching_changes(paths, tmp_path):
    """Fetching local Git neither installs, binds, updates commits nor resets user edits."""
    upstream = tmp_path / "local remote"
    commit = checkout(upstream)
    fmagent.fetch(paths, str(upstream), "main")
    assert git(paths.root, "rev-parse", "HEAD") == commit
    assert not paths.python.exists()
    assert not paths.local_config.exists()
    (paths.root / "main.py").write_text("# user edits\n")
    (upstream / "main.py").write_text("# remote change\n")
    git(upstream, "add", ".")
    git(upstream, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "remote change")
    fmagent.fetch(paths, str(upstream), "main")
    assert git(paths.root, "rev-parse", "HEAD") == commit
    assert (paths.root / "main.py").read_text() == "# user edits\n"
    assert not paths.local_config.exists()


@pytest.mark.parametrize("default,explicit,warning", [(False, False, False), (False, True, True), (True, False, True)])
def test_checkout_difference_warning_is_local_nonblocking(paths, monkeypatch, capsys, default, explicit, warning):
    """Default directories warn by default; custom directories compare only explicit choices."""
    checkout(paths.root)
    git(paths.root, "checkout", "--detach", "-q")
    if default:
        source_base = paths.root.parent
        monkeypatch.setattr(fmagent, "plugin_source_root", lambda: source_base)
        root = paths.root.parent / "third_party/FM-Agent"
        root.parent.mkdir()
        paths.root.rename(root)
        paths = FMAgentPaths(root, root / ".venv/bin/python", "default", "root default", paths.local_config)
    fmagent.fetch(paths, "https://example.invalid/other" if explicit else None, "other" if explicit else None)
    assert ("Warning:" in capsys.readouterr().err) == warning
    assert not paths.local_config.exists()


@pytest.mark.parametrize("kind", ["file", "nonempty", "nongit", "parent-git"])
def test_fetch_protects_existing_noncheckout_data(paths, kind):
    """Nonempty directories and a parent's Git tree are never overwritten or accepted."""
    if kind == "file":
        paths.root.write_text("user content")
    elif kind == "nonempty":
        paths.root.mkdir()
        (paths.root / "keep").write_text("user content")
    else:
        source(paths.root)
        if kind == "parent-git":
            git(paths.root.parent, "init", "-q")
    before = {str(item): item.read_bytes() for item in paths.root.rglob("*") if item.is_file()} if paths.root.is_dir() else paths.root.read_bytes()
    with pytest.raises(ValueError, match="Refusing"):
        fmagent.fetch(paths)
    after = {str(item): item.read_bytes() for item in paths.root.rglob("*") if item.is_file()} if paths.root.is_dir() else paths.root.read_bytes()
    assert before == after


def test_failed_fetch_does_not_retry_or_install(paths, monkeypatch):
    """A Git failure is a single isolated command and leaves no binding."""
    calls = []

    def run(command, **kwargs):
        """Record a failed clone without accessing any remote."""
        calls.append(command)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(fmagent.subprocess, "run", run)
    with pytest.raises(ValueError, match="no retry"):
        fmagent.fetch(paths)
    assert len(calls) == 1 and calls[0][:2] == ["git", "clone"]
    assert not paths.local_config.exists()


def test_install_missing_source_never_clones(paths, monkeypatch):
    """Install is not an implicit fetch action."""
    monkeypatch.setattr(fmagent.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected command"))
    with pytest.raises(ValueError, match="source missing"):
        fmagent.install(paths, [])


@pytest.mark.parametrize("returncode", [0, 9])
def test_native_install_isolated_once_with_explicit_flags(paths, monkeypatch, returncode):
    """The native Bash installer owns provisioning; parent env selection cannot redirect it."""
    source(paths.root)
    marker = paths.root / "calls.jsonl"
    (paths.root / "install.sh").write_text(f'''#!/bin/bash
"{sys.executable}" - "$@" <<'PY'
import json, os, sys
from pathlib import Path
with Path({str(marker)!r}).open("a") as stream:
    stream.write(json.dumps({{"args":sys.argv[1:], "env":dict(os.environ), "cwd":os.getcwd()}}) + "\\n")
PY
exit {returncode}
''')
    poisoned = {"PYTHONPATH": "/wrong", "PYTHONHOME": "/wrong", "PYTHONSAFEPATH": "1",
                "VIRTUAL_ENV": "/wrong", "CONDA_PREFIX": "/conda", "UV_PROJECT_ENVIRONMENT": "/wrong",
                "UV_PYTHON": "/wrong", "UV_NO_SYNC": "1", "GIT_DIR": "/wrong", "FM_AGENT_MODEL_BACKEND": "codex"}
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/wrong/bin:/conda/bin:" + os.environ["PATH"])
    if returncode:
        with pytest.raises(ValueError, match="no retry or binding"):
            fmagent.install(paths, ["--with-chisel"])
    else:
        fmagent.install(paths, ["--with-chisel"])
    records = [json.loads(line) for line in marker.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["args"] == ["--with-chisel"] and record["cwd"] == str(paths.root)
    assert record["env"]["FM_AGENT_MODEL_BACKEND"] == "codex"
    assert not any(key in record["env"] for key in poisoned if key != "FM_AGENT_MODEL_BACKEND")
    assert "/wrong/bin" not in record["env"]["PATH"] and "/conda/bin" not in record["env"]["PATH"]
    assert not paths.local_config.exists()


@pytest.mark.parametrize("code,state", [(0, "ready"), (10, "dependencies-missing"), (11, "dependencies-missing"), (12, "configuration-invalid"), (1, "check-failed")])
def test_status_is_local_bounded_and_read_only(paths, monkeypatch, code, state):
    """Status runs exactly one bounded import/config probe, never models/installers or writes."""
    source(paths.root)
    paths = resolve_paths(str(paths.root), sys.executable)
    calls = []

    def run(command, **kwargs):
        """Inspect the sole local subprocess and hide any native diagnostic secrets."""
        calls.append(command)
        assert kwargs["timeout"] == 15 and kwargs["cwd"] == paths.root
        assert "PYTHONSAFEPATH" not in kwargs["env"]
        assert kwargs["env"]["PYTHONPATH"] == str(paths.root)
        return subprocess.CompletedProcess(command, code, b"secret", b"secret")

    monkeypatch.setattr(fmagent.subprocess, "run", run)
    assert fmagent.local_status(paths)[0] == state
    assert len(calls) == 1 and calls[0][:3] == [str(paths.python), "-B", "-c"]
    assert not paths.local_config.exists()


def test_status_missing_source_interpreter_and_timeout(paths, monkeypatch):
    """Common incomplete environments have distinct, non-provisioning diagnostics."""
    assert fmagent.local_status(paths)[0] == "source-missing"
    source(paths.root)
    assert fmagent.local_status(paths)[0] == "python-missing"
    paths = resolve_paths(str(paths.root), sys.executable)

    def timeout(command, **kwargs):
        """Simulate a hung config import without waiting for it."""
        raise subprocess.TimeoutExpired(command, 15)

    monkeypatch.setattr(fmagent.subprocess, "run", timeout)
    assert fmagent.local_status(paths)[0] == "check-failed"


def test_real_probe_without_credentials_or_writes(paths, monkeypatch):
    """The actual short probe imports local config without requiring credentials or writing pyc."""
    source(paths.root)
    paths = resolve_paths(str(paths.root), sys.executable)
    for key in list(os.environ):
        if "API_KEY" in key or "TOKEN" in key:
            monkeypatch.delenv(key)
    for name in ("openai", "dotenv", "pydantic_settings", "rich", "zstandard", "tree_sitter"):
        (paths.root / f"{name}.py").write_text("# local dependency fixture\n")
    assert fmagent.local_status(paths)[0] == "ready"
    assert not (paths.root / "__pycache__").exists()
    (paths.root / "config.py").write_text('raise ValueError("secret must not be reported")\n')
    state, message = fmagent.local_status(paths)
    assert state == "configuration-invalid" and "secret" not in message


def test_bind_cli_saves_paths_only_and_warns_about_overrides(paths, monkeypatch, capsys):
    """Binding missing deps is allowed, and neither task YAML nor shell/env is changed."""
    source(paths.root)
    task = paths.root.parent / "task.yaml"
    task.write_text("keep task\n")
    paths.local_config.write_text('[fmagent]\nroot=' + json.dumps(str(paths.root)) + '\n')
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", str(paths.root.parent / "temporary sentinel"))
    monkeypatch.setenv("RTL2SPEC_FMAGENT_PYTHON", "/temporary/sentinel/python")
    before = dict(os.environ)
    assert launch(["fmagent", "bind"]) == 0
    assert task.read_text() == "keep task\n" and dict(os.environ) == before
    assert tomllib.loads(paths.local_config.read_text())["fmagent"] == {
        "root": str(paths.root), "python": str(paths.python),
    }
    output = capsys.readouterr()
    assert "python-missing" in output.err and "override" in output.err
    assert str(paths.local_config) in output.out


def test_cli_status_exit_codes_and_install_flags(paths, monkeypatch, capsys):
    """CLI delegates the independent action with only explicitly requested native flags."""
    assert launch(["fmagent", "status", "--fmagent-root", str(paths.root)]) == 1
    assert "[argument]" in capsys.readouterr().out
    source(paths.root)
    calls = []
    monkeypatch.setattr(fmagent, "install", lambda selected, flags: calls.append((selected.root, flags)))
    assert launch(["fmagent", "install", "--yes", "--fmagent-root", str(paths.root), "--with-erlang", "--with-dsh"]) == 0
    assert calls == [(paths.root, ["--with-dsh", "--with-erlang"])]
    monkeypatch.setattr(fmagent, "local_status", lambda selected: ("ready", "fixture ready"))
    assert launch(["fmagent", "status", "--fmagent-root", str(paths.root)]) == 0


def test_bind_rejects_missing_source_and_install_rejects_python(paths):
    """Invalid combinations fail before invoking native installation or writing TOML."""
    for arguments in (["bind"], ["install", "--fmagent-python", "/existing/python"]):
        with pytest.raises(SystemExit) as error:
            launch(["fmagent", *arguments])
        assert error.value.code == 2
    assert not paths.local_config.exists()


@pytest.mark.parametrize("explicit_root", [False, True])
def test_bind_ignores_process_paths_with_default_or_explicit_root(paths, monkeypatch, explicit_root):
    """A temporary export never becomes a standalone binding, even without local TOML."""
    root = paths.root if explicit_root else paths.local_config.parent / "third_party/FM-Agent"
    source(root)
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", "/temporary/sentinel/root")
    monkeypatch.setenv("RTL2SPEC_FMAGENT_PYTHON", "/temporary/sentinel/python")
    arguments = ["--fmagent-root", str(root)] if explicit_root else []
    assert launch(["fmagent", "bind", *arguments]) == 0
    assert tomllib.loads(paths.local_config.read_text())["fmagent"] == {
        "root": str(root), "python": str(root / ".venv/bin/python"),
    }


@pytest.mark.parametrize("text", ['[broken', 'fmagent="wrong"', 'fmagent=123', 'fmagent=[]', 'fmagent=true'])
def test_bind_invalid_table_has_stable_diagnostic(paths, capsys, text):
    """Full explicit overrides cannot overwrite malformed or non-table TOML."""
    source(paths.root)
    paths.local_config.write_text(text)
    with pytest.raises(SystemExit) as error:
        launch(["fmagent", "bind", "--fmagent-root", str(paths.root), "--fmagent-python", str(paths.python)])
    assert error.value.code == 2
    assert "repair its fmagent table" in capsys.readouterr().err
    assert paths.local_config.read_text() == text


@pytest.mark.parametrize("action", ["fetch", "install"])
@pytest.mark.parametrize("mode", ["accept", "decline", "eof", "noninteractive", "-y", "--yes"])
def test_action_confirmation(paths, monkeypatch, action, mode):
    calls = []
    monkeypatch.setattr(fmagent.sys.stdin, "isatty", lambda: mode != "noninteractive")

    def answer(prompt):
        if mode == "eof":
            raise EOFError
        if mode in {"-y", "--yes", "noninteractive"}:
            pytest.fail("Unexpected prompt")
        return "yes" if mode == "accept" else "no"

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(fmagent, action, lambda *args: calls.append(args))
    arguments = ["fmagent", action, "--fmagent-root", str(paths.root)]
    if mode in {"-y", "--yes"}:
        arguments.append(mode)
        monkeypatch.setattr(fmagent.sys.stdin, "isatty", lambda: False)
    if mode in {"accept", "-y", "--yes"}:
        assert launch(arguments) == 0
        assert len(calls) == 1
    else:
        with pytest.raises(SystemExit) as error:
            launch(arguments)
        assert error.value.code == 2
        assert not calls
