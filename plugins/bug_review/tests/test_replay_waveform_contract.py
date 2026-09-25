"""Regression tests for mandatory replay and waveform review contracts."""

import json
from pathlib import Path

import pytest

from bug_review.case_analysis import validate_response


def test_waveform_requires_signed_evidence_or_explicit_tool_error(tmp_path):
    """An exploratory or missing waveform result cannot complete review."""
    evidence = {"case": {"original_executions": [{"nodeid": "test_demo"}]}, "replay": {}}
    task_dir = tmp_path / "task"
    (task_dir / "waveforms").mkdir(parents=True)
    observation = {"task_id": task_dir.name, "result": {"success": True, "status": "inventory"}}
    identity = "wave-" + __import__("bug_review.analysis_core.task_manifest", fromlist=["stable_hash"]).stable_hash(observation)
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
