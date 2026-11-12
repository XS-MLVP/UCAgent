"""A reviewed property owns reference expressions reused by every Bug delivery."""

import pytest

from formal.reference import calculate_references
from formal.skills.lib.formal_tools import (
    auto_scaffold_bug_entries,
    bug_observation_description,
    refresh_analysis_references,
    validate_analysis_evidence,
    validate_original_observations,
    generate_summary_doc,
)
from formal.skills.lib.models import (
    AnalysisData, AnalysisEntry, CheckPoint, FormalRecords, FormalSpec,
    FunctionGroup, FunctionPoint, RunResults,
)


def reviewed_records():
    """Build two full property paths sharing a leaf and distinct current witnesses."""
    names = ("left.A_SHARED", "right.A_SHARED")
    evidence = {}
    entries = []
    for index, name in enumerate(names, 1):
        reference = {"run_id": "run-current", "input_fingerprint": "fp-current", "property": name,
                     "report_sha256": f"report-{index}", "witness_sha256": f"witness-{index}"}
        evidence[name] = {"result": "FALSIFIED", "raw_status": "Fail (1)", "evidence_ref": reference,
                          "initial_values": [{"signal": "request", "width": 8, "value": hex(index)}]}
        entries.append(AnalysisEntry(id=f"FA-{index:03d}", prop_name=name,
            evidence_ref=reference, prop_type="assert", resolution="RTL_BUG",
            analysis="Reviewed the original witness against this stated relation.",
            expected_requirement="Output must preserve the current request.",
            reference_calculations=[{"id": "expected_request", "expression": "request + 1", "bindings": {
                "request": {"source": "initial", "signal": "request"}}}]))
    run = RunResults(run_id="run-current", input_fingerprint="fp-current", timestamp="now", log_hash="log",
                     stats={}, failing_properties=list(names), tt_properties=[], assert_failing_properties=list(names),
                     cover_failing_properties=[], property_kinds={name: "assert" for name in names},
                     property_evidence=evidence)
    return FormalRecords(dut="PacketRouter", run_results=run,
                         analysis=AnalysisData(source_fingerprint="fp-current", fa_entries=entries), bugs=[])


def test_current_fa_calculations_reused_by_bugs_without_reauthoring():
    """Scaffolding copies reviewed semantics while recomputing only machine projections."""
    records = reviewed_records()
    assert refresh_analysis_references(records)
    assert not refresh_analysis_references(records)
    validate_analysis_evidence(records)
    assert auto_scaffold_bug_entries(records)
    assert not auto_scaffold_bug_entries(records)
    assert {bug.property for bug in records.bugs} == {"left.A_SHARED", "right.A_SHARED"}
    for bug in records.bugs:
        entry = next(entry for entry in records.analysis.fa_entries if entry.prop_name == bug.property)
        assert bug.expected_requirement == entry.expected_requirement
        assert bug.reference_calculations == entry.reference_calculations
        assert bug.reference_results == entry.reference_results
        assert bug.reference_calculations is not entry.reference_calculations
        assert bug.reference_results is not entry.reference_results
        assert bug.reference_results[0]["value"] == (1 if bug.property.startswith("left") else 2) + 1
        assert "recorded counterexample only" in bug.description
        assert "all inputs" not in bug.description
        assert bug.impact_assessment == ""
    validate_original_observations(records)


def test_raw_bug_semantics_and_machine_description_cannot_fork_from_fa():
    """Changing Bug-authored copies never authorizes a new expected relationship."""
    records = reviewed_records()
    refresh_analysis_references(records)
    auto_scaffold_bug_entries(records)
    current = records.bugs[0]
    current.expected_requirement = "Something else"
    with pytest.raises(ValueError, match="forked"):
        validate_original_observations(records)
    auto_scaffold_bug_entries(records)
    current.description = "Every possible input produces zero"
    with pytest.raises(ValueError, match="description changed"):
        validate_original_observations(records)


def test_fa_reference_tamper_and_changed_inputs_invalidate_review():
    """Verifier recomputes arithmetic and enforces the exact current run receipt."""
    records = reviewed_records()
    refresh_analysis_references(records)
    entry = records.analysis.fa_entries[0]
    entry.reference_results[0]["value"] = 999
    with pytest.raises(ValueError, match="reference calculation changed"):
        validate_analysis_evidence(records)
    with pytest.raises(ValueError, match="reference calculation changed"):
        refresh_analysis_references(records)
    entry.reference_results = calculate_references(entry.reference_calculations, records.run_results.property_evidence[entry.prop_name])
    records.run_results.input_fingerprint = "new-inputs"
    with pytest.raises(ValueError, match="stale"):
        validate_analysis_evidence(records)
    entry.evidence_ref = {"property": "other"}
    with pytest.raises(ValueError, match="matching evidence_ref"):
        auto_scaffold_bug_entries(records)


def test_summary_checkpoint_facts_reuse_exact_current_specification(tmp_path):
    """Summary reports source CK conditions, not an independently retyped boundary claim."""
    records = FormalRecords(dut="PacketRouter", spec=FormalSpec(function_groups=[FunctionGroup(
        id="FG-READY", functions=[FunctionPoint(id="FC-READY", check_points=[CheckPoint(
            id="CK-EXACT", style="Comb", sva_body="output_ready == request_ready;",
            description="ready matches request")])])]), planning={"verification_scope": {"excluded": ["clocked state"]}},
        summary={"core_function": "Combinational ready routing", "overall_result": "No fabricated result",
                 "acceptance_conclusion": "Current target scope only", "completeness": {
                     "safety": "Current target set only", "liveness": "Not applicable", "cover": "Not applicable"}})
    path = tmp_path / "summary.md"
    generate_summary_doc(records, str(path), machine={"proof_complete": True, "counts": {"PROVEN": 1}})
    content = path.read_text()
    assert "CK-EXACT" in content
    assert "output_ready == request_ready;" in content
    assert "clocked state" in content


def test_rtl_bug_requires_specification_statement_even_without_arithmetic():
    """A static contract has no dynamic witness yet still requires a human requirement."""
    records = reviewed_records()
    entry = records.analysis.fa_entries[0]
    entry.expected_requirement = ""
    with pytest.raises(ValueError, match="expected_requirement"):
        validate_analysis_evidence(records)
    entry.expected_requirement = "Declared port width must equal the stated width."
    entry.reference_calculations = []
    assert refresh_analysis_references(records)
    assert entry.reference_results == []
    assert "static contract failure" in bug_observation_description(entry.prop_name, {
        "result": "TRIVIALLY_FALSE", "evidence_ref": {"property": entry.prop_name}})
    with pytest.raises(ValueError, match="current failed assertion"):
        bug_observation_description(entry.prop_name, {"result": "COVER_REACHED",
            "evidence_ref": {"property": entry.prop_name}})
