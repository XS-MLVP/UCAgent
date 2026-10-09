"""Focused checks for tool-recorded full replay coverage evidence."""

import json

from bug_review.core.records import CoverageMetric, CoverageRecord, ReviewIndex
from bug_review.core.replay import capture_baseline_coverage


def _prepare_output(tmp_path):
    """Create one indexed output directory with the default coverage record."""
    output = tmp_path / "verification_review" / "analysis"
    output.mkdir(parents=True)
    index = ReviewIndex(
        workspace={"name": "demo", "dut": "demo", "source_path": str(tmp_path),
                   "execution_workspace": str(tmp_path), "started_at": "now"},
        source_files={}, stage_status={}, bug_order=[], bugs={}, cases={})
    coverage = CoverageRecord(metrics={key: CoverageMetric(
        status="unavailable", reason="No verified metric in prepared inputs")
        for key in ("line", "functional")})
    (output / "review_index.json").write_text(
        json.dumps(index.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    (output / "coverage.json").write_text(
        json.dumps(coverage.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    return output, index, coverage


def _prepare_reports(tmp_path, with_line=True, with_functional=True, empty_line=False):
    """Create the saved full replay report artifacts."""
    report = tmp_path / "verification_review" / "run" / "test_report"
    if with_line:
        data = {"overview": {"total": {"line": 100}, "miss": {"line": 25}}}
        text = "" if empty_line else json.dumps(data)
        (report / "coverage_data").mkdir(parents=True)
        (report / "coverage_data" / "code_coverage.json").write_text(text, encoding="utf-8")
    if with_functional:
        (report / "toffee_report.json").write_text('{"tests": {}}\n', encoding="utf-8")


def _load_coverage(output):
    """Read back the persisted coverage record."""
    return CoverageRecord.model_validate(json.loads((output / "coverage.json").read_text(encoding="utf-8")))


def test_capture_fills_references_and_line_totals(tmp_path):
    """Both saved artifacts become available metrics with computed line totals."""
    output, _, _ = _prepare_output(tmp_path)
    _prepare_reports(tmp_path)
    result = capture_baseline_coverage(tmp_path, output)
    assert result == {"recorded": ["line", "functional"], "missing_evidence": []}
    coverage = _load_coverage(output)
    line = coverage.metrics["line"]
    assert line.status == "available"
    assert line.source_ref.endswith("coverage_data/code_coverage.json:1-1")
    assert line.run_scope == "review_full_run"
    assert (line.numerator, line.denominator, line.value) == (75, 100, "75.0%")
    functional = coverage.metrics["functional"]
    assert functional.status == "available"
    assert functional.source_ref.endswith("toffee_report.json:1-1")
    assert functional.basis


def test_capture_keeps_custom_basis_and_absent_artifacts(tmp_path):
    """A reviewer basis is preserved and missing artifacts stay untouched."""
    output, _, _ = _prepare_output(tmp_path)
    _prepare_reports(tmp_path, with_functional=False)
    capture_baseline_coverage(tmp_path, output)
    coverage = _load_coverage(output)
    assert coverage.metrics["functional"].status == "unavailable"
    coverage.metrics["line"].basis = "verilator merged line coverage"
    (output / "coverage.json").write_text(
        json.dumps(coverage.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    result = capture_baseline_coverage(tmp_path, output)
    assert result == {"recorded": ["line"], "missing_evidence": ["functional"]}
    coverage = _load_coverage(output)
    assert coverage.metrics["line"].basis == "verilator merged line coverage"


def test_capture_rejects_empty_artifact_without_touching_metrics(tmp_path):
    """An empty saved artifact is reported missing instead of a broken reference."""
    output, _, _ = _prepare_output(tmp_path)
    _prepare_reports(tmp_path, with_functional=False, empty_line=True)
    result = capture_baseline_coverage(tmp_path, output)
    assert result == {"recorded": [], "missing_evidence": ["line", "functional"]}
    coverage = _load_coverage(output)
    assert coverage.metrics["line"].status == "unavailable"
