"""Exercise the Formal data Skill through the unchanged shared script runner."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from formal.runtime import FormalDataRuntimeHook
from ucagent.core.tools.skill import RunSkillScript
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config, save_runtime_config


PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
SCRIPT_SOURCE = PLUGIN_SRC / "formal" / "skills" / "data" / "scripts" / "formal_data.py"


@pytest.fixture
def skill_workspace(tmp_path):
    """Create a copied Skill and safe snapshot in an otherwise empty DUT workspace."""
    skill = tmp_path / ".ucagent" / "skills" / "ext" / "formal" / "data"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: data\ndescription: Inspect and update current Formal task data.\n---\n\n# Data\n\nUse the declared script.\n", encoding="utf-8")
    shutil.copy2(SCRIPT_SOURCE, skill / "scripts" / "formal_data.py")
    output = tmp_path / "verification"
    output.mkdir()
    (tmp_path / "PacketRouter").mkdir()
    (output / ".formal_records.yaml").write_text("dut: PacketRouter\n", encoding="utf-8")
    cfg = Config({"runtime_options": {}, "write_dirs": ["verification"], "un_write_dirs": ["PacketRouter", "Guide_Doc"]})
    cfg._temp_cfg = {"DUT": "PacketRouter", "OUT": "verification"}
    save_runtime_config(str(tmp_path), cfg, plugin_python_paths=[str(PLUGIN_SRC)], snapshot_hooks=[FormalDataRuntimeHook()])
    return tmp_path


def call_skill(workspace, arguments):
    """Use the real public RunSkillScript contract rather than invoking store internals."""
    tool = RunSkillScript(workspace=str(workspace))
    return tool.invoke({"commands": [["ext/formal/data", "formal_data.py", arguments]]})


def request_file(workspace, payload, name="update.json"):
    """Write one explicit request artifact in the allowed output directory."""
    target = workspace / "verification" / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return str(target.relative_to(workspace))


def test_real_skill_inspect_and_structured_update_ignore_environment(skill_workspace, monkeypatch):
    """The resolved snapshot wins over malicious or stale ambient DUT and OUT values."""
    monkeypatch.setenv("DUT", "OtherDesign")
    monkeypatch.setenv("OUT", "../outside")
    inspected = json.loads(call_skill(skill_workspace, "inspect planning"))
    assert inspected["dut"] == "PacketRouter"
    assert inspected["records_artifact"] == "verification/.formal_records.yaml"
    path = request_file(skill_workspace, {"section": "planning", "expected_sha256": inspected["sha256"],
                                         "data": {"project_overview": "Independent routing verification"}})
    updated = json.loads(call_skill(skill_workspace, f"update --request-file {path}"))
    assert updated["status"] == "updated"
    inspected = json.loads(call_skill(skill_workspace, "inspect planning --full --offset 0 --limit 5"))
    assert any(item["field"] == "project_overview" for item in inspected["data"]["items"])
    assert not (skill_workspace.parent / "outside").exists()


def test_skill_mcp_conversion_uses_same_execution_path(skill_workspace):
    """MCP conversion preserves the existing three-string Skill command protocol."""
    converted = to_mcp_tool(RunSkillScript(workspace=str(skill_workspace)))
    result = asyncio.run(converted.run({"commands": [["ext/formal/data", "formal_data.py", "inspect overview"]]}, context=None))
    assert json.loads(result)["dut"] == "PacketRouter"


@pytest.mark.parametrize("argument", ["inspect unknown", "inspect overview --limit 0", "prepare planning", "update", "inspect overview --request-file verification/request.json"])
def test_invalid_cli_is_structured_and_nonzero(skill_workspace, argument):
    """Invalid commands fail rather than claim usage evidence or silently mutate data."""
    before = (skill_workspace / "verification" / ".formal_records.yaml").read_bytes()
    result = call_skill(skill_workspace, argument)
    assert result.startswith("Command failed with exit code 2:")
    error = json.loads(result.split("\n", 1)[1])
    assert error["error_code"] == "formal_data_skill_invalid"
    assert (skill_workspace / "verification" / ".formal_records.yaml").read_bytes() == before


@pytest.mark.parametrize("payload", [[], {"action": "update", "section": "planning", "expected_sha256": "a" * 64, "data": {}},
                                      {"section": "planning", "expected_sha256": "a" * 64, "data": {}, "bodies": {}},
                                      {"section": "planning", "data": {}}])
def test_update_request_has_one_canonical_envelope(skill_workspace, payload):
    """Request files accept no inline aliases, action keys, or ambiguous payload forms."""
    path = request_file(skill_workspace, payload)
    result = call_skill(skill_workspace, f"update --request-file {path}")
    assert "Command failed with exit code 2:" in result
    assert "exactly section, expected_sha256" in result


def test_request_revision_conflict_is_nonzero(skill_workspace):
    """A stale request cannot overwrite task edits from another actor."""
    inspected = json.loads(call_skill(skill_workspace, "inspect planning"))
    path = request_file(skill_workspace, {"section": "planning", "expected_sha256": inspected["sha256"],
                                         "data": {"project_overview": "new"}})
    records = skill_workspace / "verification" / ".formal_records.yaml"
    records.write_text("dut: PacketRouter\nplanning: {project_overview: external}\n")
    result = call_skill(skill_workspace, f"update --request-file {path}")
    assert result.startswith("Command failed with exit code 2:")
    assert json.loads(result.split("\n", 1)[1])["status"] == "conflict"
    assert "external" in records.read_text()


def test_request_must_be_under_allowed_output_and_not_symlink(skill_workspace, tmp_path):
    """A request is task data, never a way to read arbitrary protected paths."""
    secret = skill_workspace / "PacketRouter" / "private.json"
    secret.write_text('{"credential": "not-to-be-read"}')
    for relative in ("../private.json", "PacketRouter/private.json"):
        result = call_skill(skill_workspace, f"update --request-file {relative}")
        assert result.startswith("Command failed with exit code 2:")
        assert "not-to-be-read" not in result
    link = skill_workspace / "verification" / "linked.json"
    link.symlink_to(secret)
    assert "symlink" in call_skill(skill_workspace, "update --request-file verification/linked.json")


def test_request_size_and_json_boundaries(skill_workspace):
    """Oversized and malformed JSON requests fail before any task mutation."""
    path = skill_workspace / "verification" / "too-large.json"
    path.write_bytes(b"x" * 270001)
    assert "270000" in call_skill(skill_workspace, "update --request-file verification/too-large.json")
    path.write_text("not json")
    result = call_skill(skill_workspace, "update --request-file verification/too-large.json")
    assert result.startswith("Command failed with exit code 2:")
    assert "formal_data_skill_invalid" in result


def test_missing_hook_context_requires_restart(skill_workspace):
    """A framework-valid snapshot without Formal policy must not fall back to ambient settings."""
    path = skill_workspace / ".ucagent" / "runtime_config.json"
    data = json.loads(path.read_text())
    del data["formal_data"]
    path.write_text(json.dumps(data))
    result = call_skill(skill_workspace, "inspect overview")
    assert result.startswith("Command failed with exit code 2:")
    assert "restart UCAgent" in result


def test_stale_import_root_is_rejected_by_existing_runner(skill_workspace):
    """The unchanged shared runner rejects stale snapshot roots before starting Python."""
    path = skill_workspace / ".ucagent" / "runtime_config.json"
    data = json.loads(path.read_text())
    data["ucagent_python_path"] = "/does/not/exist"
    path.write_text(json.dumps(data))
    result = call_skill(skill_workspace, "inspect overview")
    assert "Cannot prepare the Skill script runtime" in result
    assert "Restart UCAgent" in result


def test_skill_imports_from_snapshot_with_unrelated_cwd_context(skill_workspace, monkeypatch):
    """No source-root guessing or copied-script sys.path bootstrap is necessary."""
    monkeypatch.setenv("PYTHONPATH", "/unrelated/import/path")
    result = json.loads(call_skill(skill_workspace, "inspect spec"))
    assert result["dut"] == "PacketRouter"
    assert "sys.path" not in SCRIPT_SOURCE.read_text()


@pytest.mark.parametrize("section", [{}, {"write_dirs": "verification", "un_write_dirs": None},
                                     {"write_dirs": ["../escape"], "un_write_dirs": []},
                                     {"write_dirs": ["verification/"], "un_write_dirs": []},
                                     {"write_dirs": [], "un_write_dirs": [], "secret": "not allowed"}])
def test_runtime_hook_rejects_invalid_metadata(section):
    """Only canonical safe path policies enter the plugin runtime section."""
    with pytest.raises(ValueError):
        FormalDataRuntimeHook().validate_runtime_snapshot({"formal_data": section})


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Enable licensed short FormalMC test explicitly")
def test_real_proof_prepare_through_unchanged_skill_runner(skill_workspace):
    """One Skill prepare call builds the verified exact-ID analysis queue with evidence."""
    from formal.execution import ACTIVE_RUNS, FormalExecution

    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    output = skill_workspace / "verification"
    tests = output / "tests"
    tests.mkdir()
    (skill_workspace / "PacketRouter" / "PacketRouter.sv").write_text("module PacketRouter; endmodule\n")
    (tests / "PacketRouter_checker.sv").write_text(
        "module PacketRouter_checker(input logic payload);\n"
        "property CK_BAD; payload == 1'b0; endproperty\n"
        "A_BAD: assert property (CK_BAD);\nendmodule\n"
        "module PacketRouter_wrapper; logic payload; PacketRouter_checker u_checker(payload); endmodule\n")
    (tests / "PacketRouter_wrapper.sv").write_text("// Top is included in checker source.\n")
    (tests / "PacketRouter_formal.tcl").write_text(
        "set SCRIPT_DIR [file dirname [info script]]\n"
        "read_design -top PacketRouter_wrapper -sysv [file join $SCRIPT_DIR PacketRouter_checker.sv]\n"
        "# UCAGENT_PROOF_BEGIN\nprove\nexit\n")
    cfg = Config({"runtime_options": {}, "output": "verification", "write_dirs": ["verification"], "un_write_dirs": ["PacketRouter", "Guide_Doc"]})
    execution = FormalExecution(str(skill_workspace), "verification", "PacketRouter", cfg,
                                write_dirs=["verification"], un_write_dirs=["PacketRouter", "Guide_Doc"])
    try:
        execution.run()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = execution.status(wait_s=1)
            if status["status"] not in ACTIVE_RUNS:
                break
        assert status["status"] == "COMPLETED", status
        result = json.loads(call_skill(skill_workspace, "prepare analysis --offset 0 --limit 5"))
        assert result["prepared"] is True
        assert result["ready_update"]["section"] == "analysis"
        assert "action" not in result["ready_update"]
        assert result["review_items"][0]["prop_name"] == "u_checker.A_BAD"
        assert result["evidence"][0]["evidence_ref"]["property"] == "u_checker.A_BAD"
        assert execution.status()["current_inputs"] is True
    finally:
        execution.cancel()


def test_prepare_requires_current_stopped_results(skill_workspace):
    """Preparation is recognized but cannot manufacture records without proof evidence."""
    result = call_skill(skill_workspace, "prepare analysis")
    assert result.startswith("Command failed with exit code 2:")
    assert "stopped current proof results" in result


def test_runtime_hook_only_publishes_resolved_policy():
    """The runtime hook cannot copy model credentials or arbitrary configuration data."""
    cfg = Config({"write_dirs": ["verification/"], "un_write_dirs": ["PacketRouter/"],
                  "openai": {"api_key": "secret"}})
    result = FormalDataRuntimeHook().snapshot_sections(cfg)
    assert result == {"formal_data": {"write_dirs": ["verification"], "un_write_dirs": ["PacketRouter"]}}
    FormalDataRuntimeHook().validate_runtime_snapshot(result)
    assert "secret" not in json.dumps(result)
