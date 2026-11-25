"""Coverage-stage feedback directs work without changing acceptance."""

import pytest

from toffee_ut.stage_checks import line_coverage


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError("missing latest"), "run_required"),
    (line_coverage.RunSourceStale("changed inputs"), "run_required"),
    (ValueError("Run receipt is missing or changed"), "run_invalid"),
])
def test_missing_or_invalid_run_feedback(monkeypatch, error, expected):
    def read(*args):
        raise error

    monkeypatch.setattr(line_coverage, "current_run", read)
    result = line_coverage.check(None, "Block", "ut_project")
    assert not result["ok"] and result["issue_kind"] == expected
    assert ("with RunToffee once" in result["next_action"]) is (expected == "run_required")


@pytest.mark.parametrize("kind", ["review_stale", "selector_mismatch", "review_incomplete", "coverage_gaps"])
def test_review_feedback_reuses_verified_run(monkeypatch, kind):
    monkeypatch.setattr(line_coverage, "current_run", lambda *_: {"record": {"run": "results/current"}})
    monkeypatch.setattr("toffee_ut.coverage.coverage_data", lambda *_: {"review": {
        "state": "invalid", "issue_kind": kind, "error": "example", "location": "line:test.sv:10",
        "unreviewed_by_metric": {"line": 1},
    }})
    result = line_coverage.check(None, "Block", "ut_project")
    assert not result["ok"] and result["issue_kind"] == kind
    assert result["location"] == "line:test.sv:10"
    assert result["observed"]["run"] == "results/current"
    assert "with RunToffee once" not in result["next_action"]


def test_stale_source_diagnostic_separates_signed_specs_from_review_notes(monkeypatch):
    def read(*_):
        raise line_coverage.RunSourceStale("changed inputs", ("docs/spec/verification/Block.md",))

    monkeypatch.setattr(line_coverage, "current_run", read)
    result = line_coverage.check(None, "Block", "ut_project")
    assert not result["ok"] and result["observed"] == {
        "changed_inputs": ["docs/spec/verification/Block.md"], "changed_total": 1}
    assert "docs/reviews" in result["next_action"] and "then update the review only" in result["next_action"]
