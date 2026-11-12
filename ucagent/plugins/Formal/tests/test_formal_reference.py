"""Bounded evidence-backed integer calculations never claim to prove a spec."""

import copy

import pytest

from formal.reference import calculate_references, derive_expected


@pytest.fixture

def evidence():
    """Provide unrelated wide inputs and an independently sampled output."""
    return {
        "result": "FALSIFIED",
        "evidence_ref": {"run_id": "run-17", "property": "pipe.A_DATA", "trace_sha256": "trace-digest"},
        "initial_values": [
            {"signal": "request.data", "width": 80, "value": "0x10000000000000000001", "has_unknown": False},
            {"signal": "request.carry", "width": 1, "value": "0x0", "has_unknown": False},
        ],
        "trace_observations": {
            "status": "available", "sampled_time": 25, "time_unit": "ps", "time_magnitude": "10",
            "sample_kind": "last_recorded_sample_not_failure_cycle", "truncated": False,
            "signals": [
                {"name": "Shell.output[79:0]", "width": 80, "available": True, "value": "0x10000000000000000000", "unknown_mask": "0x0", "z_mask": "0x0"},
                {"name": "Shell.flag", "width": 1, "available": True, "value": "0x1", "unknown_mask": "0x0", "z_mask": "0x0"},
            ],
        },
    }


def test_wide_values_and_expression_bind_exact_sources(evidence):
    """Named arithmetic binds full-width original input and separately timed sample."""
    requests = [{"id": "sum-check", "expression": "payload + 3 * carry", "bindings": {
        "payload": {"source": "initial", "signal": "request.data"},
        "carry": {"source": "initial", "signal": "request.carry"},
    }}, {"id": "output-view", "expression": "observed >> 1", "bindings": {
        "observed": {"source": "sample", "signal": "Shell.output[79:0]"},
    }}]
    result = calculate_references(requests, evidence)
    assert result[0]["value"] == int("10000000000000000001", 16)
    assert result[1]["value"] == int("10000000000000000000", 16) >> 1
    assert result[0]["evidence_ref"] == evidence["evidence_ref"]
    assert result[1]["bindings"]["observed"]["sampled_time"] == 25


def test_requirement_and_arithmetic_are_separately_labelled(evidence):
    """Computed integers are explicitly limited to the caller-supplied expression."""
    text, results = derive_expected("output must preserve the lower payload bits", [{
        "id": "payload", "expression": "data & 255", "bindings": {"data": {"source": "initial", "signal": "request.data"}}
    }], evidence)
    assert "author-provided; not machine-proven" in text
    assert "not machine-proven" in text
    assert "checks only the supplied expression" in text
    assert results[0]["value"] == 1
    pending, empty = derive_expected("[LLM-TODO]", [], evidence)
    assert "requirement pending" in pending
    assert empty == []


@pytest.mark.parametrize("expression", [
    "__import__('os').system('true')", "data[0]", "data ** 1000", "1 / 2", "1.5 + data",
    "missing + 1", "1 << 4097", "1 // 0", "(lambda: 1)()",
])
def test_unsupported_or_unbounded_expressions_rejected(evidence, expression):
    """Calls, indexing, floats, implicit names, and resource-heavy forms are unavailable."""
    request = {"id": "unsafe", "expression": expression,
               "bindings": {"data": {"source": "initial", "signal": "request.data"}}}
    with pytest.raises(ValueError):
        calculate_references([request], evidence)


def test_xz_missing_truncated_and_ambiguous_signals_rejected(evidence):
    """No unknown, unavailable, partial or leaf-name-guessed signal becomes an integer."""
    unknown = copy.deepcopy(evidence)
    unknown["initial_values"].append({"signal": "request.x", "width": 1, "value": "1x", "has_unknown": True})
    for signal, source, modified in [
        ("request.x", "initial", unknown), ("missing", "sample", evidence),
        ("output", "sample", evidence),
    ]:
        request = {"id": "binding", "expression": "value + 1", "bindings": {"value": {"source": source, "signal": signal}}}
        with pytest.raises(ValueError):
            calculate_references([request], modified)
    truncated = copy.deepcopy(evidence)
    truncated["trace_observations"]["truncated"] = True
    request = {"id": "binding", "expression": "value", "bindings": {"value": {"source": "sample", "signal": "Shell.flag"}}}
    with pytest.raises(ValueError, match="truncated"):
        calculate_references([request], truncated)


def test_limits_duplicates_and_forged_evidence_ref_rejected(evidence):
    """Input budgets and evidence provenance are checked before arithmetic."""
    one = {"id": "one", "expression": "x + 1", "bindings": {"x": {"source": "initial", "signal": "request.carry"}}}
    with pytest.raises(ValueError, match="unique"):
        calculate_references([one, one], evidence)
    with pytest.raises(ValueError, match="evidence_ref"):
        calculate_references([one], {**evidence, "evidence_ref": None})
    with pytest.raises(ValueError, match="unsupported expression"):
        calculate_references([{**one, "bindings": {}}], evidence)
    with pytest.raises(ValueError, match="exactly"):
        calculate_references([{**one, "answer": 99}], evidence)


def test_result_is_deterministic_and_carries_exact_receipt(evidence):
    """No caller numeric answer is trusted or accepted as a calculation input."""
    request = {"id": "result", "expression": "value ^ 7", "bindings": {"value": {"source": "sample", "signal": "Shell.flag"}}}
    first = calculate_references([request], evidence)
    assert first == calculate_references([request], evidence)
    assert first[0]["value"] == 6
    assert "expected" not in first[0]


def test_constant_calculation_and_mixed_sources_keep_distinct_context(evidence):
    """Static calculations need no signal binding, while mixed views remain explicitly distinct."""
    constant = calculate_references([{"id": "static-width", "expression": "(1 << 80) - 1", "bindings": {}}], evidence)[0]
    assert constant["value"] == 2**80 - 1
    assert constant["bindings"] == {}
    mixed = calculate_references([{"id": "views", "expression": "initial_value - sampled_value", "bindings": {
        "initial_value": {"source": "initial", "signal": "request.data"},
        "sampled_value": {"source": "sample", "signal": "Shell.output[79:0]"},
    }}], evidence)[0]
    assert mixed["value"] == 1
    initial, sampled = mixed["bindings"]["initial_value"], mixed["bindings"]["sampled_value"]
    assert initial["sampled_time"] is None
    assert initial["sample_kind"] == "original_initialization_not_failure_cycle"
    assert sampled["sampled_time"] == 25 and sampled["time_unit"] == "ps" and sampled["time_magnitude"] == "10"
    assert sampled["sample_kind"] == "last_recorded_sample_not_failure_cycle"


@pytest.mark.parametrize("raw", ["0x100000000000000000000", "-0x1", 1, "unknown"])
def test_invalid_bit_pattern_cannot_be_a_reference_binding(evidence, raw):
    """Malformed or out-of-width evidence values cannot silently become known integers."""
    modified = copy.deepcopy(evidence)
    modified["initial_values"][0]["value"] = raw
    request = {"id": "pattern", "expression": "data", "bindings": {"data": {"source": "initial", "signal": "request.data"}}}
    with pytest.raises(ValueError):
        calculate_references([request], modified)


def test_bug_scaffold_and_delivery_reject_derived_reference_tampering(evidence, tmp_path):
    """Derived text and result lists are regenerated and checked at report delivery."""
    from formal.skills.lib.formal_tools import auto_scaffold_bug_entries, generate_bug_report_doc, validate_original_observations
    from formal.skills.lib.models import AnalysisData, AnalysisEntry, BugEntry, FormalRecords, RunResults
    name = evidence["evidence_ref"]["property"]
    request = {"id": "lower-word", "expression": "data & 255", "bindings": {"data": {"source": "initial", "signal": "request.data"}}}
    records = FormalRecords(dut="QueueRouter", run_results=RunResults(timestamp="now", log_hash="verified", stats={},
        failing_properties=[name], tt_properties=[], property_evidence={name: evidence}),
        analysis=AnalysisData(fa_entries=[AnalysisEntry(id="FA-001", prop_name=name, resolution="RTL_BUG",
            evidence_ref=evidence["evidence_ref"], expected_requirement="The output must preserve the low payload bits.",
            reference_calculations=[request], reference_results=calculate_references([request], evidence))]),
        bugs=[BugEntry(id="BG-001", property=name)])
    assert auto_scaffold_bug_entries(records)
    bug = records.bugs[0]
    assert bug.reference_results[0]["value"] == 1
    assert "author-provided; not machine-proven" in bug.expected
    assert "Checked arithmetic" in bug.expected
    validate_original_observations(records)
    target = tmp_path / "accepted-report.md"
    target.write_text("previous accepted report")
    bug.reference_results[0]["value"] = 999
    with pytest.raises(ValueError, match="Bug review forked"):
        generate_bug_report_doc(records, str(target))
    assert target.read_text() == "previous accepted report"
    assert auto_scaffold_bug_entries(records)
    assert bug.reference_results[0]["value"] == 1
    bug.expected = "Claimed expected numeric answer 999"
    with pytest.raises(ValueError, match="Expected-value calculation changed"):
        validate_original_observations(records)
