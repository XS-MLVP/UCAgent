"""Deterministic lazy projection and bounded invalid-review diagnostics, with no native DUT."""

import builtins
import json

import pytest

from test_native_review_groups import coverage_tool, inspect_review, native_review, point_bytes, save_review
from toffee_ut import coverage
from toffee_ut.audit import audit_project, delivery_data


def test_default_points_does_not_sort_or_build_location_directory(native_review, monkeypatch):
    """Default reads retain all audit indexes but never sort or allocate the unused directory."""
    original = builtins.sorted

    def no_directory_sort(values, *args, **kwargs):
        """Permit physical LCOV ordering but reject sorting any native position directory."""
        values = list(values)
        for value in values:
            assert not (isinstance(value, tuple) and (len(value) == 4 or
                len(value) == 2 and isinstance(value[0], tuple) and len(value[0]) == 4)), "Unused position directory sorted"
        return original(values, *args, **kwargs)

    monkeypatch.setattr(coverage, "sorted", no_directory_sort, raising=False)
    for state in ("missing", "complete"):
        if state == "complete":
            save_review(native_review)
        parsed = inspect_review(native_review)
        assert all(not parsed[metric].get("groups") for metric in ("line", "branch", "toggle"))
        page = coverage_tool(native_review)._run(metric="toggle", limit=1)
        assert page["ok"] and page["view"] == "points" and len(page["uncovered"]) == 1
        assert page["metrics"]["toggle"]["found"] == 7 and page["review"]["state"] == state


def test_groups_sort_only_requested_metric_and_filter_and_build_only_page(native_review, monkeypatch):
    """The directory sorts selected positions, not unrelated locations, and materializes one page."""
    original = builtins.sorted
    positions = []

    def selected_directory(values, *args, **kwargs):
        """Record directory positions separately from physical LCOV line ordering."""
        values = list(values)
        for value in values:
            if isinstance(value, tuple) and len(value) == 4:
                assert value == ("toggle", "unit-only", "inputs/Block.sv", 10)
                positions.append(value)
            elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], tuple):
                assert len(value[0]) != 4, "All-metric directory sorted before filtering"
        return original(values, *args, **kwargs)

    monkeypatch.setattr(coverage, "sorted", selected_directory, raising=False)
    page = coverage_tool(native_review)._run(metric="toggle", view="groups", build="unit-only",
        source="inputs/Block.sv", line=10, limit=1)
    assert page["ok"] and len(positions) == 1
    assert page["groups_total"] == 1 and page["uncovered_total"] == 4
    assert len(page["groups"]) == 1 and page["groups"][0]["zero_points"] == 4
    assert page["next_offset"] is None


@pytest.mark.parametrize("metric,total,zeros", [("line", 1, 1), ("branch", 1, 3), ("toggle", 2, 6)])
def test_directory_page_never_changes_metrics_review_or_other_metric_projection(native_review, metric, total, zeros):
    """Both views retain the same real counters and review, with bounded group rows only on request."""
    save_review(native_review)
    plain = coverage_tool(native_review)._run(metric=metric, limit=1)
    directory = coverage_tool(native_review)._run(metric=metric, view="groups", offset=1, limit=1)
    assert directory["metrics"] == plain["metrics"] and directory["review"] == plain["review"]
    assert directory["groups_total"] == total and directory["uncovered_total"] == zeros
    assert len(directory["groups"]) == (1 if total > 1 else 0)
    assert directory["next_offset"] is None


@pytest.mark.parametrize("field,value,category", [
    ("source", "s" * 250_000, "Selector matches no actual zero points"),
    ("build", "b" * 250_000, "Unknown native build"),
    ("metric", "m" * 250_000, "Invalid zero-point location"),
    ("line", "9" * 250_000, "Invalid zero-point location"),
    ("line", ["x" * 250_000], "Invalid zero-point location"),
    ("point", "p" * 250_000, "Group requires branch/toggle"),
    ("status", "s" * 250_000, "Each zero-point disposition needs"),
    ("reason", ["r" * 250_000], "Each zero-point disposition needs"),
    ("group", {"scope": "g" * 250_000}, "Group requires branch/toggle"),
    ("unknown" * 30_000, {}, "Unknown zero-point selector fields"),
], ids=["long-source", "long-build", "long-metric", "long-line", "nested-line", "long-point",
        "long-status", "nested-reason", "nested-group", "long-unknown-key"])
def test_invalid_review_error_has_bounded_identity_without_changing_input(native_review, field, value, category):
    """Malformed long selectors stay invalid, retain their category and missing totals, and do not echo unbounded data."""
    row = native_review["entry"]["uncovered"][1]
    row[field] = value
    save_review(native_review)
    page = coverage_tool(native_review)._run(metric="line", limit=1)
    review = page["review"]
    assert page["ok"] and review["state"] == "invalid"
    assert review["error"].startswith(category), review["error"][:100]
    assert len(review["error"]) <= 1800 and len(json.dumps(page)) < 20_000
    assert "metric=" in review["error"] and "source=" in review["error"] and "line=" in review["error"]
    assert review["unreviewed_total"] == 9
    assert review["unreviewed_by_metric"] == {"line": 0, "branch": 3, "toggle": 6}
    assert row[field] == value
    assert not audit_project(native_review["workspace"], "Block", phase="line_coverage")["ok"]
    assert delivery_data(native_review["workspace"], "Block", "ut_project")["status"] == "INCOMPLETE"


def test_unreviewed_long_native_identity_is_previewed_but_never_used_as_selector(native_review):
    """Diagnostic previews are bounded independently of exact raw counter matching and totals."""
    source = "inputs/" + "x" * 5000 + ".sv"
    raw = point_bytes("branch", 99, "another-point").replace(b"inputs/Block.sv", source.encode())
    with native_review["native"].open("ab") as stream:
        stream.write(raw)
    save_review(native_review)
    review = inspect_review(native_review)["review"]
    assert review["state"] == "invalid" and review["unreviewed_total"] == 1
    assert review["unreviewed_by_metric"] == {"line": 0, "branch": 1, "toggle": 0}
    assert len(review["error"]) <= 1800 and len(json.dumps(review)) < 10_000
    native_review["entry"]["uncovered"].append({"metric": "branch", "build": "unit-only", "source": source[:-1] + "X",
        "line": 99, "group": {"scope": "source-line"}, "status": "justified", "reason": "Synthetic independent restriction"})
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "invalid"
    native_review["entry"]["uncovered"][-1]["source"] = source
    save_review(native_review)
    assert inspect_review(native_review)["review"]["state"] == "complete"
