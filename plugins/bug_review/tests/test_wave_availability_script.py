"""Focused checks for the waveform availability inventory script."""

import importlib.util
import json
from pathlib import Path
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "bug_review" / "skills" / \
    "waveform-review" / "scripts" / "check_wave_availability.py"

CASES = (("test_good", "suspected_dut"),
         ("test_datonly", "suspected_dut"),
         ("test_missing", "suspected_dut"),
         ("test_triaged", "test_implementation"))


def _load_script():
    """Load the skill script the same way RunSkillScript executes it."""
    spec = importlib.util.spec_from_file_location("check_wave_availability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_workspace(tmp_path):
    """One indexed output, four failed cases in two categories and one session."""
    workspace = tmp_path
    (workspace / ".ucagent").mkdir(parents=True)
    (workspace / ".ucagent" / "runtime_config.json").write_text(
        json.dumps({"OUT": "verification_review/analysis"}), encoding="utf-8")
    out = workspace / "verification_review" / "analysis"
    out.mkdir(parents=True)
    (out / "cases").mkdir()
    cases = {}
    for name, category in CASES:
        case_id = f"tests/test_mod.py::{name}"
        cases[case_id] = {"replay_target": case_id,
                          "waveform_test_case_name": case_id,
                          "record_path": f"cases/{name}.json"}
        (out / f"cases/{name}.json").write_text(json.dumps(
            {"failure_analysis": {"category": category},
             "replay": {"status": "failed"}}), encoding="utf-8")
    (out / "review_index.json").write_text(
        json.dumps({"cases": cases}), encoding="utf-8")
    session = workspace / "verification_review" / "run" / "unity_test" / "data" / \
        "toffee_tmp_20261008190000_001" / "master"
    session.mkdir(parents=True)
    (session / "test_good.fst").write_bytes(b"fst")
    (session / "test_datonly.dat").write_bytes(b"dat" * 100)
    return workspace


def test_inventory_classifies_and_lists_rerun_targets(tmp_path, monkeypatch, capsys):
    """suspected_dut cases split into usable / dat-only / missing with rerun targets."""
    module = _load_script()
    workspace = _prepare_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["check_wave_availability.py"])
    module.main()
    text = capsys.readouterr().out
    assert "toffee_tmp_20261008190000_001" in text
    assert "test_good" in text and "fst/vcd 可用" in text
    assert "test_datonly" in text and "仅 dat" in text
    assert "test_missing" in text and "缺失" in text
    rerun_section = text.split("需要定向复跑")[1]
    assert "tests/test_mod.py::test_datonly" in rerun_section
    assert "tests/test_mod.py::test_missing" in rerun_section
    assert "test_good" not in rerun_section
    assert "汇总: 可用 1 / 仅dat 1 / 缺失 1" in text
    # Non-suspected cases stay out of the default inventory.
    assert "test_triaged" not in text


def test_inventory_all_failed_flag_expands_scope(tmp_path, monkeypatch, capsys):
    """--all-failed inventories every failed case regardless of category."""
    module = _load_script()
    workspace = _prepare_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["check_wave_availability.py", "--all-failed"])
    module.main()
    text = capsys.readouterr().out
    assert "test_triaged" in text
    assert "汇总: 可用 1 / 仅dat 1 / 缺失 2" in text
