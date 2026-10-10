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
        (report / "toffee_report.json").write_text(json.dumps({'coverages': {'functional': {'groups': [{'name': 'FG-A', 'points': [{'name': 'FC-A', 'bins': [{'name': 'CK-A', 'hints': 1}]}]}]}}}), encoding="utf-8")


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
    assert line.source_ref.endswith("line.json:1-9")
    assert line.run_scope == "review_full_run"
    assert (line.numerator, line.denominator, line.value) == (75, 100, "75.0%")
    functional = coverage.metrics["functional"]
    assert functional.status == "available"
    assert functional.source_ref.endswith("functional.json:1-9")
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


def test_coverage_is_immutable_after_targeted_report_replacement(tmp_path):
    """Later reports never replace the evidence referenced by the full baseline."""
    output, _, _ = _prepare_output(tmp_path)
    _prepare_reports(tmp_path)
    capture_baseline_coverage(tmp_path, output)
    coverage = _load_coverage(output)
    path = tmp_path / coverage.metrics["line"].source_ref.rsplit(":", 1)[0]
    frozen = path.read_bytes()
    live = tmp_path / "verification_review/run/test_report/coverage_data/code_coverage.json"
    live.write_text(json.dumps({"overview": {"total": {"line": 100}, "miss": {"line": 99}}}))
    assert path.read_bytes() == frozen
    assert _load_coverage(output).metrics["line"].value == "75.0%"


def test_multibatch_coverage_requires_matching_input_identity(tmp_path):
    """A final batch cannot impersonate full-set coverage from different sources."""
    output, _, _ = _prepare_output(tmp_path)
    roots = []
    for number, missed in enumerate([25, 20]):
        root = tmp_path / "verification_review/run/test_report/invocations" / str(number)
        (root / "coverage_data").mkdir(parents=True)
        (root / "invocation.json").write_text(json.dumps({"context": {"source_sha256": str(number)}}))
        (root / "coverage_data/code_coverage.json").write_text(json.dumps({"overview": {"total": {"line": 100}, "miss": {"line": missed}}}))
        roots.append(root)
    capture_baseline_coverage(tmp_path, output, roots)
    assert _load_coverage(output).metrics["line"].status == "unavailable"


def test_multibatch_union_counts_unique_lines_and_checkpoints(tmp_path):
    """Full-set coverage unions sampled CKs and intersects genuinely missed lines."""
    output, _, _ = _prepare_output(tmp_path)
    roots = []
    for number, missed in enumerate(["1-2", "2-3"]):
        root = tmp_path / "verification_review/run/test_report/invocations" / str(number)
        (root / "coverage_data").mkdir(parents=True)
        (root / "invocation.json").write_text(json.dumps({"context": {"source_sha256": "same-build"}}))
        (root / "coverage_data/code_coverage.json").write_text(json.dumps({
            "overview": {"total": {"line": 4}, "miss": {"line": 2}},
            "uncovered": {"data": {"top.sv": {"modules": {"top": {"total": {"line": 4}, "line": [missed]}}}}}}))
        bins = [{"name": "CK-A", "hints": 1-number}, {"name": "CK-B", "hints": number}]
        (root / "toffee_report.json").write_text(json.dumps({"coverages": {"functional": {"groups": [{"name": "FG-A", "points": [{"name": "FC-A", "bins": bins}]}]}}}))
        roots.append(root)
    capture_baseline_coverage(tmp_path, output, roots)
    coverage = _load_coverage(output)
    assert coverage.metrics["line"].value == "75.0%"
    assert coverage.metrics["functional"].value == "100.0%"
