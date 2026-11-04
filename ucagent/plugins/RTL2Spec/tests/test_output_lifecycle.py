"""Protect previous generation output at workflow startup and command entry points."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from rtl2spec.plugin import get_plugin
from rtl2spec.tools import RTL2SpecCommandArgs


@pytest.mark.parametrize("workflow_index", [0, 1])
@pytest.mark.parametrize(
    "relative",
    [
        "outputs/Sbuffer_design_document_zh.md",
        "outputs/Sbuffer_design_document_zh_v1.0.0.md",
        "outputs/nested/unfinished.md",
        "outputs/.hidden",
        "outputs/old-report.md",
        "outputs/evidence/v1.0.0/manifest.json",
        "outputs/old.md",
        "outputs",
    ],
)
def test_startup_rejects_old_output_before_workspace_initialization(tmp_path, relative, workflow_index):
    """Abort before copying resources or exposing editing tools, preserving all old files."""
    from ucagent.verify_agent import VerifyAgent

    old = tmp_path / relative
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"Previous user output\n")
    workflow = get_plugin().workflows[workflow_index]
    with pytest.raises(FileExistsError, match="package/archive.*clear") as caught:
        VerifyAgent(
            workspace=str(tmp_path),
            dut_name="Sbuffer",
            output="outputs",
            cfg_override=[{"backend.key_name": "blank"}, {"langfuse.enable": False}],
            workflow_config_file=str(workflow.config_file),
            template_context_factory=workflow.template_context_factory,
            no_history=True,
            no_embed_tools=True,
        )
    assert "outputs" in str(caught.value)
    assert old.read_bytes() == b"Previous user output\n"
    assert not (tmp_path / "Guide_Doc").exists()
    assert not (tmp_path / ".ucagent/runtime_config.json").exists()


def test_empty_run_directory_and_other_runs_are_allowed(tmp_path):
    """A fresh selected run does not inspect or alter a previous run directory."""
    (tmp_path / "selected-output").mkdir()
    other = tmp_path / "outputs/previous-run/old.md"
    other.parent.mkdir(parents=True)
    other.write_text("Other module\n")
    workflow = get_plugin().workflows[0]
    assert workflow.template_context_factory(
        None, {"WORKSPACE": str(tmp_path), "DUT": "Sbuffer", "OUT": "selected-output"}
    ) == {}
    assert other.read_text() == "Other module\n"


@pytest.mark.parametrize("action", ["preflight", "evidence", "generic_preflight", "generic_evidence"])
@pytest.mark.parametrize("directory", ["", "evidence", "nested"])
@pytest.mark.parametrize("output_dir", ["outputs", "runs/custom output"])
def test_commands_stop_before_subprocess_for_old_output(command, workspace, monkeypatch, action, directory, output_dir):
    """Both generation entry points diagnose old or partial output without launching tools."""
    command.output_dir = output_dir
    command.write_dirs.append(output_dir)
    old = workspace / output_dir / directory / "partial.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("Preserve this draft\n")

    def unexpected_launch(*args, **kwargs):
        """Fail if a blocked generation attempts to run a child process."""
        pytest.fail("Generation must stop before launching a subprocess")

    monkeypatch.setattr(subprocess, "Popen", unexpected_launch)
    result = command._run(action, "Sbuffer")
    assert not result["ok"]
    assert result["error_code"] == "OUTPUT_DIRECTORY_NOT_CLEAN"
    assert output_dir in result["error"]
    assert "user" in result["next_action"] and "archive" in result["next_action"]
    assert old.read_text() == "Preserve this draft\n"
    assert not (workspace / ".cache/compiler-calls").exists()


@pytest.mark.parametrize("action", ["preflight", "evidence", "generic_preflight", "generic_evidence"])
@pytest.mark.parametrize("output_dir", ["outputs", "runs/custom output"])
def test_runtime_entry_point_cannot_bypass_output_guard(workspace, action, output_dir):
    """Direct runtime invocation also refuses existing documents before compilation."""
    old = workspace / output_dir / "old.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("Preserve this document\n")
    result = subprocess.run(
        [sys.executable, "-m", "rtl2spec.runtime", action, "--module", "Sbuffer", "--output", output_dir],
        cwd=workspace, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "package/archive" in result.stdout
    assert old.read_text() == "Preserve this document\n"
    assert not (workspace / ".cache/compiler-calls").exists()


def test_output_arriving_during_compilation_is_preserved(workspace, monkeypatch):
    """Recheck output after elaboration, before publishing the generated evidence."""
    from rtl2spec.runtime import generate

    for key, value in {
        "RTL2SPEC_WORKSPACE": workspace,
        "XIANGSHAN_ROOT": workspace / "third_party/XiangShan",
        "RTL2SPEC_CACHE": workspace / ".cache",
        "RTL2SPEC_PYTHON": sys.executable,
    }.items():
        monkeypatch.setenv(key, str(value))
    old = workspace / "outputs/arrived.md"
    run = subprocess.run

    def compile_then_add_output(args, **kwargs):
        """Run the real fixture compiler, then simulate an external document arriving."""
        result = run(args, **kwargs)
        if args[0] == "bash" and args[1].endswith("/generate_rtl.sh"):
            old.parent.mkdir(parents=True, exist_ok=True)
            old.write_text("External document\n")
        return result

    monkeypatch.setattr(subprocess, "run", compile_then_add_output)
    with pytest.raises(FileExistsError, match="outputs"):
        generate(workspace, "Sbuffer", "DefaultConfig")
    assert old.read_text() == "External document\n"
    assert not (workspace / "outputs/evidence").exists()
    assert not (workspace / ".ucagent/.rtl2spec_receipt_key").exists()


@pytest.mark.parametrize("field,value", [("version", "v1.0.0"), ("change_type", "Patch"), ("summary", "Update")])
def test_removed_version_arguments_are_rejected(field, value):
    """Removed document history inputs cannot silently enter the current tool contract."""
    with pytest.raises(ValidationError, match="Extra inputs"):
        RTL2SpecCommandArgs(action="metadata", module="Sbuffer", **{field: value})


@pytest.mark.parametrize("output_dir", ["", ".", "../outside", "/tmp/outside"])
def test_invalid_output_directory_is_rejected(command, workspace, output_dir):
    """Reject workspace roots and escaping output names before any artifacts are written."""
    from rtl2spec.documents import require_clean_output

    with pytest.raises(ValueError, match="output_dir"):
        require_clean_output(workspace, output_dir)
    command.output_dir = output_dir
    result = command._run("evidence", "Sbuffer")
    assert result["error_code"] == "PATH_OUTSIDE_WORKSPACE"
    assert not (workspace / ".cache/compiler-calls").exists()


def test_custom_output_rejects_external_symlink(command, workspace, tmp_path):
    """An apparently local output path cannot redirect publication outside the workspace."""
    from rtl2spec.documents import require_clean_output

    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "selected").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes workspace"):
        require_clean_output(workspace, "selected/run")
    command.output_dir = "selected/run"
    result = command._run("evidence", "Sbuffer")
    assert result["error_code"] == "PATH_OUTSIDE_WORKSPACE"
    assert list(outside.iterdir()) == []
