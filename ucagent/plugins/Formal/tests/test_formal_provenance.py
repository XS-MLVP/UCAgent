"""Regression boundaries for machine provenance independent of task update interfaces."""

import pytest

from formal.checkers.formal import EnvironmentAnalysisChecker
from formal.skills.lib.formal_tools import validate_analysis_evidence
from formal.skills.lib.models import AnalysisData, AnalysisEntry, FormalRecords, RunResults


@pytest.mark.parametrize("resolution", ["RTL_BUG", "rtl_bug"])
def test_cover_failure_cannot_be_classified_as_rtl_defect(resolution):
    """File/script paths cannot bypass the assertion-only classification boundary."""
    name = "pipeline.reach_state"
    reference = {"run_id": "run-current", "input_fingerprint": "current-inputs", "property": name,
                 "report_sha256": "original-tool-report", "witness_sha256": None}
    records = FormalRecords(dut="ControlUnit", run_results=RunResults(
        timestamp="now", log_hash="hash", stats={}, run_id="run-current", input_fingerprint="current-inputs",
        failing_properties=[name], tt_properties=[], assert_failing_properties=[], cover_failing_properties=[name],
        property_kinds={name: "cover"}, property_evidence={name: {"evidence_ref": reference}}),
        analysis=AnalysisData(source_fingerprint="current-inputs", fa_entries=[AnalysisEntry(
            id="FA-001", prop_name=name, prop_type="cover", analysis="Reviewed tool output",
            resolution=resolution, evidence_ref=reference)]))
    with pytest.raises(ValueError, match="failed assertion|Noncanonical"):
        validate_analysis_evidence(records)
    checker = EnvironmentAnalysisChecker("ControlUnit")
    errors, _ = checker._validate_entry_quality({}, {name: records.analysis.fa_entries[0].model_dump()})
    assert errors


def test_lowercase_acceptance_cannot_skip_provenance_validation():
    """Canonical enum validation and provenance cannot disagree on case handling."""
    checker = EnvironmentAnalysisChecker("ArbitraryUnit")
    errors, _ = checker._validate_entry_quality({"unit.tautology": {
        "root_cause": "design_expected", "action": "accepted", "analysis": "No current receipt supplied"}}, {})
    assert errors
