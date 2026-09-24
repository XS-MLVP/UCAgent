"""Regression tests for mandatory replay and waveform review contracts."""

import json
from pathlib import Path

import pytest

from bug_review import input_preparation
from bug_review.case_analysis import validate_response


def _workspace(root: Path) -> Path:
    workspace = root / "workspace_demo"
    (workspace / ".ucagent").mkdir(parents=True)
    (workspace / "unity_test/tests").mkdir(parents=True)
    (workspace / "demo").mkdir()
    (workspace / ".ucagent/runtime_config.json").write_text("{}", encoding="utf-8")
    (workspace / "unity_test/tests/test_demo.py").write_text("def test_demo(): pass\n", encoding="utf-8")
    return workspace


def test_preparation_reruns_even_when_previous_report_matches(tmp_path, monkeypatch):
    """A current analysis run must not adopt a historical report."""
    source = _workspace(tmp_path)
    destination = tmp_path / "staged"
    calls = []

    def fake_run(workspace, timeout):
        calls.append(workspace)
        report = workspace / "uc_test_report/toffee_report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"tests": [{"nodeid": "test_demo", "outcome": "passed"}]}), encoding="utf-8")
        return {"execution": {"invocation_success": True, "report_has_tests": True}, "report_path": str(report)}

    monkeypatch.setattr(input_preparation, "_run_tests", fake_run)
    input_preparation.stage_analysis_inputs(source, destination, run_tests=True)
    input_preparation.stage_analysis_inputs(source, destination, run_tests=True)

    assert len(calls) == 2


def test_waveform_requires_signed_evidence_or_explicit_tool_error(tmp_path):
    """An exploratory or missing waveform result cannot complete review."""
    evidence = {"case": {"original_executions": [{"nodeid": "test_demo"}]}, "replay": {}}
    task_dir = tmp_path / "task"
    (task_dir / "waveforms").mkdir(parents=True)
    observation = {"task_id": task_dir.name, "result": {"success": True, "status": "inventory"}}
    identity = "wave-" + __import__("bug_review.benchmark_workflow.task_manifest", fromlist=["stable_hash"]).stable_hash(observation)
    (task_dir / "waveforms" / f"{identity}.json").write_text(json.dumps(observation), encoding="utf-8")

    with pytest.raises(ValueError, match="final signed evidence"):
        validate_response(
            "waveform",
            evidence,
            {"conclusion": "inconclusive", "evidence_id": identity,
             "alignment_evidence": "a", "observed_behavior": "b", "source_correlation": "c",
             "rationale": "r", "evidence_refs": ["/case/original_executions/0"]},
            task_dir,
        )


def test_environment_issue_requires_collection_or_fixture_diagnostic(tmp_path):
    """Environment classification is reserved for explicit infrastructure failures."""
    evidence = {"case": {"original_executions": [{"nodeid": "test_demo", "phases": []}]}, "replay": {}}
    with pytest.raises(ValueError, match="setup/teardown/collection"):
        validate_response(
            "replay",
            evidence,
            {"classification": "environment_issue", "correctness_confirmed": False,
             "exact_input": "input", "specification_expected": "expected", "test_expected": "expected",
             "dut_actual": "unknown", "driver_timing_review": "unknown", "rationale": "r",
             "evidence_refs": ["/case/original_executions/0"]},
            tmp_path,
        )
