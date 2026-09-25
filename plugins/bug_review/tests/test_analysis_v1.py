"""Focused contracts for the five-stage Bug Review workflow."""

import json
from pathlib import Path

import pytest
import yaml

from bug_review.analysis_core.task_manifest import atomic_write_json
from bug_review.workflow import ANALYSIS, Workflow, prepare


def _source(root: Path, name: str) -> Path:
    """Create one small, immutable-looking UnityTest input workspace."""
    source = root / name
    dut = name.removeprefix("workspace_")
    (source / "unity_test/tests").mkdir(parents=True)
    (source / "dut").mkdir()
    (source / "unity_test/tests/test_dut.py").write_text(
        "def test_dut():\n    assert True\n", encoding="utf-8")
    (source / "unity_test" / f"{dut}_bug_summary.md").write_text(
        "\n# dut Bug Summary\n\nTotal Bugs: 2\n\n"
        "| Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| HOLD-A | high | | FG-A/FC-B/CK-C | A failed | dut/rtl.v:2-2 | 0.9 | |\n"
        "| HOLD-B | high | | FG-A/FC-B/CK-D | B failed | dut/rtl.v:2-2 | 0.8 | |\n",
        encoding="utf-8")
    (source / "dut/SPEC.md").write_text("\n# Specification\n\nOutput holds during stall.\n", encoding="utf-8")
    (source / "dut/rtl.v").write_text("// rtl\nassign y = x;\n", encoding="utf-8")
    return source


def test_inventory_covers_each_workspace_and_freezes_inputs(tmp_path):
    """All selected workspaces receive separate inventories and outlines."""
    first = _source(tmp_path / "inputs", "workspace_a")
    second = _source(tmp_path / "inputs", "workspace_b")
    root = prepare(tmp_path / "output", runs=[(first.name, first), (second.name, second)])
    workflow = Workflow(root)
    assert workflow.run("inventory")["current_stage"] == "replay"
    assert workflow.check("inventory")[0]
    for name in (first.name, second.name):
        target = root / "results/workspaces" / name
        assert len(json.loads((target / "bug_inventory.json").read_text())["bugs"]) == 2
        assert (target / "bug_outline.md").is_file()
    first.joinpath("dut/rtl.v").write_text("// changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="input changed"):
        workflow._check_sources()


def test_decisions_keep_refuted_claim_and_merge_confirmed_root(tmp_path):
    """Refuted claims remain visible and confirmed claims share one RTL root."""
    source = _source(tmp_path / "inputs", "workspace_dut")
    root = prepare(tmp_path / "output", runs=[(source.name, source)])
    workflow = Workflow(root)
    workflow.run("inventory")
    target = root / "results/workspaces" / source.name
    inventory = json.loads((target / "bug_inventory.json").read_text())
    for bug in inventory["bugs"]:
        bug["tests"] = ["unity_test/tests/test_dut.py::test_dut"]
    atomic_write_json(target / "bug_inventory.json", inventory)
    case = {"nodeid": "unity_test/tests/test_dut.py::test_dut", "case_id": "case-1"}
    review = {"case": case, "review": {"correctness_confirmed": True,
                                       "classification": "suspected_dut_bug"},
              "replay": {"status": "reproduced"},
              "waveform": {"verified_evidence": {"success": True}}}
    atomic_write_json(target / "replay_results.json", {
        "execution": {"invocation_success": True}, "original_report_path": None,
        "suite_test_count": 1, "suite_failed_count": 1,
        "cases": [{"nodeid": case["nodeid"], "status": "reproduced"}]})
    atomic_write_json(target / "case_reviews.json", {"cases": [review]})
    atomic_write_json(target / "waveform_reviews.json", {"cases": [
        {"case": case, "review": {"conclusion": "dut_bug"},
         "waveform": review["waveform"]}]})
    assert workflow._run_correlate() is None
    request_path, responses = workflow._decision_paths(source.name)
    tasks = json.loads(request_path.read_text())["tasks"]
    common = {"rationale": "Evidence reviewed", "spec_ref": "dut/SPEC.md:4",
              "rtl_ref": "dut/rtl.v:2", "first_error": "register advances",
              "causal_chain": "stall is ignored", "evidence_refs": ["/bug/summary"]}
    for task in tasks:
        atomic_write_json(responses / (task["task_id"] + ".json"), {
            **common, "verdict": "confirmed", "review_confidence": 0.9})
    outputs = workflow._run_correlate()
    assert outputs is not None
    groups = json.loads((target / "root_groups.json").read_text())["groups"]
    assert len(groups) == 1
    assert set(groups[0]["member_bug_ids"]) == {"HOLD-A", "HOLD-B"}
    first = tasks[0]
    with pytest.raises(ValueError, match="review_confidence 0"):
        workflow._validate_decision(first, {**common, "verdict": "refuted",
                                             "review_confidence": 0.9}, source.name)
    atomic_write_json(responses / (first["task_id"] + ".json"), {
        **common, "verdict": "refuted", "review_confidence": 0})
    workflow._run_correlate()
    rows = json.loads((target / "bug_reviews.json").read_text())["bugs"]
    assert len(rows) == 2
    assert any(row["review_confidence"] == 0 and row["origin"] == "reported" for row in rows)
    workflow._run_publish()
    assert (root / "results/index.html").is_file()
    assert len(list(target.glob("bug_*.html"))) == 2


def test_stage_config_and_isolated_output_contract(tmp_path):
    """The YAML and prepared workspaces select the same five stages."""
    config = yaml.safe_load((Path(__file__).resolve().parents[1]
                             / "bug_review/workflows/analysis.yaml").read_text())
    assert tuple(stage["name"] for stage in config["stage"]) == ANALYSIS
    assert all(stage["output_files"] and stage["checker"] for stage in config["stage"])
    source = _source(tmp_path / "inputs", "workspace_a")
    with pytest.raises(ValueError, match="separate"):
        prepare(tmp_path / "inputs", runs=[(source.name, source)])
    assert prepare(tmp_path / "custom-output", runs=[(source.name, source)]).name == "custom-output"


def test_replay_runs_once_and_creates_new_failure_review(tmp_path, monkeypatch):
    """A fresh suite failure enters the queue without a reported Bug claim."""
    source = _source(tmp_path / "inputs", "workspace_dut")
    root = prepare(tmp_path / "output", runs=[(source.name, source)])
    workflow = Workflow(root)
    workflow.run("inventory")
    calls = []

    def fake_suite(manifest, directory, timeout):
        """Write one real-shaped parsed failure report for the suite caller."""
        receipt = Path(directory) / "execution.json"
        if receipt.is_file():
            return json.loads(receipt.read_text())
        calls.append(manifest["run_key"])
        report = Path(directory) / "workspace/uc_test_report/toffee_report.json"
        atomic_write_json(report, {"tests": [{
            "nodeid": "tests/test_dut.py::test_dut",
            "status": {"category": "failed"},
            "phases": [{"status": {"category": "failed"},
                        "report": "", "call": "AssertionError: unexpected output"}]}]})
        result = {"execution": {"invocation_success": True, "report_has_tests": True},
                  "report_path": str(report),
                  "replay_workspace": {"replay_workspace_root": str(report.parents[2]),
                                       "replay_tests_root": str(report.parents[2] / "unity_test/tests")}}
        atomic_write_json(receipt, result)
        return result

    monkeypatch.setattr("bug_review.workflow.execute_suite", fake_suite)
    assert workflow.run("replay")["status"] == "awaiting_judgments"
    task = workflow.requests()["requests"][0]
    workflow.submit(task_id=task["task_id"], input_hash=task["input_hash"],
                    round_index=0, request_hash=task["request_hash"],
                    response={"classification": "inconclusive", "correctness_confirmed": False,
                              "exact_input": "unknown", "specification_expected": "hold",
                              "test_expected": "hold", "dut_actual": "unexpected output",
                              "driver_timing_review": "not yet aligned", "rationale": "needs waveform",
                              "evidence_refs": ["/case/nodeid"]})
    assert workflow.run("replay")["current_stage"] == "waveform"
    assert calls == [source.name]
    result = json.loads((root / "results/workspaces" / source.name / "replay_results.json").read_text())
    assert result["cases"][0]["status"] == "reproduced"
    assert result["cases"][0]["nodeid"] == "unity_test/tests/test_dut.py::test_dut"
    assert result["cases"][0]["reported_bug_ids"] == []
    assert workflow.run("waveform")["status"] == "awaiting_judgments"
