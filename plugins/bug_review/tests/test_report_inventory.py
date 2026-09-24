"""Regression tests for report-first replay inventory validation."""

from bug_review.benchmark_workflow.report_inventory import build_report_inventory, validate_report_inventory


def _report(tmp_path):
    path = tmp_path / "demo_bug_analysis.md"
    path.write_text(
        """# Demo Bug Analysis

## DYNAMIC-BUGS

### Bug <BG-DEMO-1>

- <TC-tests/test_demo.py::test_reported>
- <TC-tests/test_demo.py::test_passed>

**预期：** output is zero

**实际观测：** output is nonzero

**根因：** stale row data

## ROOT-CAUSES

## WAVEFORM-EVIDENCE
""",
        encoding="utf-8",
    )
    return path


def test_inventory_tracks_report_cases_and_clusters(tmp_path):
    """The parse artifact preserves Bug, case, source and root information."""
    inventory = build_report_inventory(
        _report(tmp_path), run_key="run", model="model", dut="demo"
    )
    assert inventory["schema"] == "reported_bug_inventory.v1"
    assert inventory["bugs"][0]["referenced_tests"] == [
        "tests/test_demo.py::test_passed", "tests/test_demo.py::test_reported"
    ]
    assert inventory["root_cause_clusters"]


def test_validation_distinguishes_reproduced_passed_and_unreported(tmp_path):
    """Fresh results never turn missing cases into passes."""
    inventory = build_report_inventory(
        _report(tmp_path), run_key="run", model="model", dut="demo"
    )
    result = validate_report_inventory(inventory, [
        {"nodeid": "tests/test_demo.py::test_reported", "outcome": "failed",
         "exception_message": "stale row data"},
        {"nodeid": "tests/test_demo.py::test_passed", "outcome": "passed"},
        {"nodeid": "tests/test_demo.py::test_new", "outcome": "failed",
         "exception_message": "new failure"},
    ])
    statuses = {row["nodeid"]: row["status"] for row in result["associated_cases"]}
    assert statuses["tests/test_demo.py::test_reported"] == "reproduced_failure"
    assert statuses["tests/test_demo.py::test_passed"] == "passed"
    assert result["unreported_failures"][0]["nodeid"] == "tests/test_demo.py::test_new"


def test_validation_matches_parameterized_descendants(tmp_path):
    """A report naming the base test covers collected parameter children."""
    inventory = build_report_inventory(
        _report(tmp_path), run_key="run", model="model", dut="demo"
    )
    inventory["bugs"][0]["referenced_tests"] = ["tests/test_demo.py::test_reported"]
    result = validate_report_inventory(inventory, [
        {"nodeid": "tests/test_demo.py::test_reported[zero]", "outcome": "passed"},
    ])
    assert result["associated_cases"][0]["status"] == "passed"
