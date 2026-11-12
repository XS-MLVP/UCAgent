"""Author-only expression corrections refresh safely through file and Skill preparation paths."""

import copy

import pytest
import yaml

from formal.checkers.formal import EnvironmentAnalysisChecker
from formal.skills.lib.formal_tools import refresh_analysis_references, validate_analysis_evidence
from test_formal_analysis_reuse import reviewed_records
from test_formal_review_contract import review_task


def test_author_expression_change_and_removal_validate_old_results_first():
    """Changing or deleting valid requests needs neither proof reruns nor clearing machine fields."""
    records = reviewed_records()
    refresh_analysis_references(records)
    entry = records.analysis.fa_entries[0]
    entry.reference_calculations[0]["expression"] = "request + 2"
    assert refresh_analysis_references(records)
    assert entry.reference_results[0]["value"] == 3
    validate_analysis_evidence(records)
    entry.reference_calculations = []
    assert refresh_analysis_references(records)
    assert entry.reference_results == []
    validate_analysis_evidence(records)


@pytest.mark.parametrize("field,value", [("value", 999), ("decimal", "999"), ("evidence_ref", {"property": "other"})])
def test_changed_expression_cannot_launder_a_tampered_previous_result(field, value):
    """A valid new request must not conceal forged answers or provenance in its predecessor."""
    records = reviewed_records()
    refresh_analysis_references(records)
    entry = records.analysis.fa_entries[0]
    entry.reference_calculations[0]["expression"] = "request + 2"
    entry.reference_results[0][field] = value
    before = copy.deepcopy(records.model_dump())
    with pytest.raises(ValueError, match="reference calculation changed"):
        refresh_analysis_references(records)
    assert records.model_dump() == before


def test_refresh_is_atomic_across_valid_author_changes_and_later_errors():
    """A failed later record cannot leave earlier machine results partially refreshed."""
    records = reviewed_records()
    refresh_analysis_references(records)
    records.analysis.fa_entries[0].reference_calculations[0]["expression"] = "request + 2"
    records.analysis.fa_entries[1].reference_calculations[0]["expression"] = "request // 0"
    before = copy.deepcopy(records.model_dump())
    with pytest.raises(ValueError, match="zero"):
        refresh_analysis_references(records)
    assert records.model_dump() == before


def prepared_task(review_task):
    """Create one fully reviewed generic property using original synthetic proof receipts."""
    store, path = review_task([("branch.A_REQUIRED", "assert", "Fail (1)")])
    inventory = path.parent / "formal_runs" / ("b" * 32) / "inventory"
    inventory.mkdir()
    (inventory / "console.log").write_text("UCAGENT_ASSERT_BEGIN\n 1 branch.A_REQUIRED : Fail (1)\tpdrx\t0.01\t(-)\nUCAGENT_ASSERT_END\n")
    prepared = store.prepare("analysis")
    entry = prepared["ready_update"]["data"]["fa_entries"][0]
    entry.update(analysis="Reviewed current evidence against the specification relation.", resolution="RTL_BUG",
                 expected_requirement="Output must satisfy the declared interface relation.",
                 reference_calculations=[{"id": "constant_width", "expression": "1 + 1", "bindings": {}}])
    store.update("analysis", {"fa_entries": [entry]}, None, prepared["sha256"])
    assert not (store.workspace / ".ucagent/skills").exists()
    return store, path


def test_prepare_refreshes_author_change_before_reporting_queue_complete(review_task):
    """Prepare returns a genuinely reconciled queue without hidden stale machine projections."""
    store, path = prepared_task(review_task)
    records = yaml.safe_load(path.read_text())
    original_fingerprint = records["run_results"]["input_fingerprint"]
    records["analysis"]["fa_entries"][0]["reference_calculations"][0]["expression"] = "1 + 2"
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    prepared = store.prepare("analysis")
    refreshed = yaml.safe_load(path.read_text())
    assert prepared["review_progress"]["pending"] == 0
    assert prepared["ready_update"] is None
    assert refreshed["analysis"]["fa_entries"][0]["reference_results"][0]["value"] == 3
    assert refreshed["run_results"]["input_fingerprint"] == original_fingerprint


def test_skill_disabled_check_refreshes_author_change_without_machine_cleanup(review_task):
    """The ordinary-file path accepts the same corrected author request as data Skill update."""
    store, path = prepared_task(review_task)
    records = yaml.safe_load(path.read_text())
    records["analysis"]["fa_entries"][0]["reference_calculations"][0]["expression"] = "2 + 2"
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    checker = EnvironmentAnalysisChecker(dut_name=store.dut, cfg=store.cfg)
    checker.set_workspace(str(store.workspace))
    checker.on_init()
    passed, detail = checker.do_check()
    assert passed, detail
    assert yaml.safe_load(path.read_text())["analysis"]["fa_entries"][0]["reference_results"][0]["value"] == 4


def test_raw_answer_tampering_fails_check_and_prepare_instead_of_empty_queue(review_task):
    """Final validation and preparation agree that an edited answer is not finished work."""
    store, path = prepared_task(review_task)
    records = yaml.safe_load(path.read_text())
    records["analysis"]["fa_entries"][0]["reference_results"][0]["value"] = 999
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    checker = EnvironmentAnalysisChecker(dut_name=store.dut, cfg=store.cfg)
    checker.set_workspace(str(store.workspace))
    checker.on_init()
    passed, detail = checker.do_check()
    assert not passed
    assert detail["error_code"] == "formal_analysis_evidence_invalid"
    with pytest.raises(ValueError, match="reference calculation changed"):
        store.prepare("analysis")
    assert yaml.safe_load(path.read_text())["analysis"]["fa_entries"][0]["reference_results"][0]["value"] == 999
