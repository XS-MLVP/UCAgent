"""Protect previous generation output at workflow startup and command entry points."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from rtl2spec.plugin import get_plugin
from rtl2spec.tools import RTL2SpecCommandArgs


@pytest.mark.parametrize(
    "relative",
    [
        "outputs/Sbuffer/Sbuffer_design_document_zh.md",
        "outputs/Sbuffer/Sbuffer_design_document_zh_v1.0.0.md",
        "outputs/Sbuffer/nested/unfinished.md",
        "outputs/Sbuffer/.hidden",
        "reports/Sbuffer/old-report.md",
        "evidence/Sbuffer/v1.0.0/manifest.json",
        "selected-output/old.md",
        "outputs/Sbuffer",
    ],
)
def test_startup_rejects_old_output_before_workspace_initialization(tmp_path, relative):
    """Abort before copying resources or exposing editing tools, preserving all old files."""
    from ucagent.verify_agent import VerifyAgent

    old = tmp_path / relative
    old.parent.mkdir(parents=True)
    old.write_bytes(b"Previous user output\n")
    workflow = get_plugin().workflows[0]
    with pytest.raises(FileExistsError, match="package/archive.*clear") as caught:
        VerifyAgent(
            workspace=str(tmp_path),
            dut_name="Sbuffer",
            output="selected-output",
            cfg_override=[{"backend.key_name": "blank"}, {"langfuse.enable": False}],
            workflow_config_file=str(workflow.config_file),
            template_context_factory=workflow.template_context_factory,
            no_history=True,
            no_embed_tools=True,
        )
    assert str(old.parent.relative_to(tmp_path)).split("/")[0] in str(caught.value)
    assert old.read_bytes() == b"Previous user output\n"
    assert not (tmp_path / "Guide_Doc").exists()
    assert not (tmp_path / ".ucagent/runtime_config.json").exists()


def test_empty_module_directories_and_unrelated_outputs_are_allowed(tmp_path):
    """Empty target directories and another module's documents do not prevent startup."""
    for relative in ("outputs/Sbuffer", "reports/Sbuffer", "evidence/Sbuffer", "selected-output"):
        (tmp_path / relative).mkdir(parents=True)
    other = tmp_path / "outputs/Other/old.md"
    other.parent.mkdir()
    other.write_text("Other module\n")
    workflow = get_plugin().workflows[0]
    assert workflow.template_context_factory(
        None, {"WORKSPACE": str(tmp_path), "DUT": "Sbuffer", "OUT": "selected-output"}
    ) == {}
    assert other.read_text() == "Other module\n"


@pytest.mark.parametrize("action", ["preflight", "evidence"])
@pytest.mark.parametrize("directory", ["outputs", "reports", "evidence"])
def test_commands_stop_before_subprocess_for_old_output(command, workspace, monkeypatch, action, directory):
    """Both generation entry points diagnose old or partial output without launching tools."""
    old = workspace / directory / "Sbuffer/partial.md"
    old.parent.mkdir(parents=True)
    old.write_text("Preserve this draft\n")

    def unexpected_launch(*args, **kwargs):
        """Fail if a blocked generation attempts to run a child process."""
        pytest.fail("Generation must stop before launching a subprocess")

    monkeypatch.setattr(subprocess, "Popen", unexpected_launch)
    result = command._run(action, "Sbuffer")
    assert not result["ok"]
    assert result["error_code"] == "OUTPUT_DIRECTORY_NOT_CLEAN"
    assert f"{directory}/Sbuffer" in result["error"]
    assert "user" in result["next_action"] and "archive" in result["next_action"]
    assert old.read_text() == "Preserve this draft\n"
    assert not (workspace / ".cache/compiler-calls").exists()


@pytest.mark.parametrize("action", ["preflight", "evidence"])
def test_runtime_entry_point_cannot_bypass_output_guard(workspace, action):
    """Direct runtime invocation also refuses existing documents before compilation."""
    old = workspace / "outputs/Sbuffer/old.md"
    old.parent.mkdir(parents=True)
    old.write_text("Preserve this document\n")
    result = subprocess.run(
        [sys.executable, "-m", "rtl2spec.runtime", action, "--module", "Sbuffer"],
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
    old = workspace / "outputs/Sbuffer/arrived.md"
    run = subprocess.run

    def compile_then_add_output(args, **kwargs):
        """Run the real fixture compiler, then simulate an external document arriving."""
        result = run(args, **kwargs)
        if args[0] == "bash" and args[1].endswith("/generate_rtl.sh"):
            old.parent.mkdir(parents=True)
            old.write_text("External document\n")
        return result

    monkeypatch.setattr(subprocess, "run", compile_then_add_output)
    with pytest.raises(FileExistsError, match="outputs/Sbuffer"):
        generate(workspace, "Sbuffer", "DefaultConfig")
    assert old.read_text() == "External document\n"
    assert not (workspace / "evidence/Sbuffer").exists()
    assert not (workspace / ".ucagent/.rtl2spec_receipt_key").exists()


@pytest.mark.parametrize("field,value", [("version", "v1.0.0"), ("change_type", "Patch"), ("summary", "Update")])
def test_removed_version_arguments_are_rejected(field, value):
    """Removed document history inputs cannot silently enter the current tool contract."""
    with pytest.raises(ValidationError, match="Extra inputs"):
        RTL2SpecCommandArgs(action="metadata", module="Sbuffer", **{field: value})
