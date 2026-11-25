"""Exercise functional FAIL acceptance with synthetic evidence, never a DUT run."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from toffee_ut.audit import delivery_data, read_spec
from toffee_ut.checkers import ToffeeUTChecker
from toffee_ut.paths import digest, write_json
from toffee_ut.runner import _signature
from toffee_ut.waveform import validate_waveform_evidence as validate_production_waveform


@pytest.fixture
def functional_evidence(project, checked_evidence, contract_writer, monkeypatch):
    """Provide a directed raw FAIL and an explicit controlled WaveInfo validation boundary."""
    root = project / "ut_project"
    checked = checked_evidence
    node, case = next(iter(checked["cases"]["cases"].items()))
    case.update(status="FAIL", roles=["api", "random"], declared_native_seed=checked["record"]["seed"])
    case["phases"]["call"]["outcome"] = "failed"
    checked["record"].update(full_selection=False, line_coverage_required=True)
    checked["manifest"]["artifacts"] = checked["manifest"]["artifacts"][:1]
    monkeypatch.setattr("toffee_ut.stage_audit.current_run", lambda workspace, project: checked)
    issue_path = root / "docs/bugs/open/functional.md"
    issue = {"kind": "issue", "run": checked["record"]["run"], "nodeids": [node],
             "classification": "rtl", "requirement": "R1", "evidence": "Controlled call-phase mismatch",
             "next_action": "Keep the assertion and request a design fix",
             "waveform_evidence": [{"nodeid": node, "receipt": "controlled-waveinfo-boundary",
                                    "at_time": 5, "analysis": "Synthetic event-level analysis"}]}
    contract_writer(issue_path, issue)
    source = project / "inputs/interface.md"
    review_path = root / "docs/reviews/Block-stage-evidence.md"
    contract_writer(review_path, {"kind": "stage_evidence", "dut": "Block", "reviews": {"random": {
        "source": "inputs/interface.md", "sha256": digest(source), "observation": "Directed random mismatch",
        "next_action": "Preserve the failing result", "strategies": [
            {"scenario": "S1", "status": "tested", "nodeid": node}]}}})

    def validate_receipts(workspace, project_name, dut, actual, nodes, entries):
        """Model accepted receipts explicitly, rejecting missing per-node observations or analysis."""
        assert Path(workspace) == project
        assert (project_name, dut, actual) == ("ut_project", "Block", checked)
        if not isinstance(entries, list) or {row.get("nodeid") for row in entries} != set(nodes):
            raise ValueError("RTL classification needs waveform_evidence for every exact failing node; call WaveInfo")
        if any(row.get("receipt") != "controlled-waveinfo-boundary" or not row.get("analysis")
               or row.get("at_time") != 5 for row in entries):
            raise ValueError("WaveInfo receipt or event-level analysis is invalid")

    validator = Mock(side_effect=validate_receipts)
    monkeypatch.setattr("toffee_ut.waveform.validate_waveform_evidence", validator)
    return SimpleNamespace(workspace=project, root=root, checked=checked, node=node, case=case,
                           issue_path=issue_path, issue=issue, review_path=review_path,
                           writer=contract_writer, validator=validator)


def check_gate(evidence, phase):
    """Exercise the public checker delegation without constructing or advancing a Mission."""
    checker = ToffeeUTChecker(phase=phase, dut="Block")
    checker.set_workspace(str(evidence.workspace))
    return checker.do_check()


@pytest.mark.parametrize("phase", ["api_tests", "random"])
def test_confirmed_rtl_fail_is_executed_without_changing_raw_verdict(functional_evidence, phase):
    """Valid directed failures need no complete selection, coverage goal or residual closure."""
    evidence = functional_evidence
    design_path = evidence.root / "docs/spec/design/Block.md"
    design = read_spec(design_path, "design", "Block")
    design["requirements"].append({**design["requirements"][0], "id": "R2", "basis": "open",
                                   "next_action": "Clarify this separate requirement"})
    evidence.writer(design_path, design)
    plan_path = evidence.root / "docs/spec/verification/Block.md"
    plan = read_spec(plan_path, "verification", "Block")
    plan["scenarios"].append({**plan["scenarios"][0], "id": "S2", "requirement": "R2",
                              "status": "deferred", "reason": "Not part of this directed selection"})
    evidence.writer(plan_path, plan)
    if phase == "random":
        review = read_spec(evidence.review_path, "stage_evidence", "Block")
        review["reviews"]["random"]["strategies"].append(
            {"scenario": "S2", "status": "not-applicable", "reason": "Await a confirmed input domain"})
        evidence.writer(evidence.review_path, review)
    original = deepcopy(evidence.checked)
    passed, result = check_gate(evidence, phase)
    assert passed, result
    evidence.validator.assert_called_once_with(str(evidence.workspace), "ut_project", "Block", evidence.checked,
                                               [evidence.node], evidence.issue["waveform_evidence"])
    assert evidence.checked == original and evidence.case["status"] == "FAIL"


@pytest.mark.parametrize("phase", ["api_tests", "random"])
@pytest.mark.parametrize("invalid", [
    "unconfirmed", "verification", "missing_issue", "closed_issue", "historical_issue", "other_issue_node",
    "inferred_requirement", "missing_waveform", "missing_analysis", "ERROR", "INCOMPLETE", "UNCERTAIN",
    "missing_native", "other_native_class", "unmanifested_source", "other_manifest_class", "missing_manifest",
    "wrong_role", "wrong_scenario", "missing_scenario", "selftest", "other_dut",
])
def test_unproved_or_infrastructure_failures_are_not_functional_credit(functional_evidence, phase, invalid):
    """A raw FAIL or an issue's rtl label alone must never waive the established prerequisites."""
    evidence = functional_evidence
    if invalid in {"unconfirmed", "verification"}:
        evidence.issue["classification"] = invalid
    elif invalid == "missing_issue":
        evidence.issue_path.unlink()
    elif invalid == "closed_issue":
        destination = evidence.root / "docs/bugs/closed/functional.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        evidence.issue_path.rename(destination)
    elif invalid == "historical_issue":
        evidence.issue["run"] = "results/another-run"
    elif invalid == "other_issue_node":
        evidence.issue["nodeids"] = ["tests/other.py::test_other"]
    elif invalid == "inferred_requirement":
        path = evidence.root / "docs/spec/design/Block.md"
        design = read_spec(path, "design", "Block")
        design["requirements"][0].update(basis="inferred", next_action="Find an independent source")
        evidence.writer(path, design)
    elif invalid == "missing_waveform":
        evidence.issue.pop("waveform_evidence")
    elif invalid == "missing_analysis":
        evidence.issue["waveform_evidence"][0]["analysis"] = ""
    elif invalid in {"ERROR", "INCOMPLETE", "UNCERTAIN"}:
        evidence.case["status"] = invalid
    elif invalid == "missing_native":
        evidence.case["native_duts"] = []
    elif invalid == "other_native_class":
        evidence.case["native_duts"][0]["class"] = "DUTOther"
    elif invalid == "unmanifested_source":
        evidence.case["native_duts"][0]["source"] = str(evidence.root / "dut/Other/__init__.py")
    elif invalid == "other_manifest_class":
        evidence.checked["manifest"]["artifacts"][0]["build"]["name"] = "DUTOther"
    elif invalid == "missing_manifest":
        evidence.checked["manifest"]["artifacts"] = []
    elif invalid == "wrong_role":
        evidence.case["roles"] = []
    elif invalid == "wrong_scenario":
        evidence.case["scenarios"] = ["unknown"]
    elif invalid == "missing_scenario":
        evidence.case["scenarios"] = []
    elif invalid == "selftest":
        evidence.case["selftest"] = True
    elif invalid == "other_dut":
        evidence.checked["record"]["dut"] = "Other"
    if invalid not in {"missing_issue", "closed_issue"}:
        evidence.writer(evidence.issue_path, evidence.issue)
    passed, result = check_gate(evidence, phase)
    assert not passed, (invalid, result)
    assert result["error_code"] == "UT_STAGE_EVIDENCE_MISSING"
    if invalid in {"missing_waveform", "missing_analysis"}:
        evidence.validator.assert_called_once()


def test_random_fail_still_requires_the_declared_native_seed(functional_evidence):
    """Validated root-cause evidence cannot compensate for a wrong random seed."""
    evidence = functional_evidence
    evidence.case["declared_native_seed"] += 1
    assert not check_gate(evidence, "random")[0]
    evidence.validator.assert_not_called()


@pytest.mark.parametrize("phase", ["api_tests", "random"])
def test_existing_pass_path_needs_no_issue_or_waveform_exception(functional_evidence, phase):
    """Ordinary functional PASS keeps the existing stage conditions without new evidence fields."""
    evidence = functional_evidence
    evidence.case["status"] = "PASS"
    evidence.case["phases"]["call"]["outcome"] = "passed"
    evidence.issue_path.unlink()
    passed, result = check_gate(evidence, phase)
    assert passed, result
    evidence.validator.assert_not_called()


@pytest.mark.parametrize("phase,role", [("env_selftest", "envcheck"), ("model_fixture", "modelcheck"),
                                       ("mock_tests", "mockcheck"), ("mock_batch", "mockcheck")])
def test_infrastructure_selftests_still_require_pass(functional_evidence, phase, role):
    """An rtl issue must not provide a FAIL exception for environment, model or Mock facilities."""
    evidence = functional_evidence
    evidence.case.update(selftest=True, roles=[role])
    assert not check_gate(evidence, phase)[0]
    evidence.case["status"] = "PASS"
    evidence.case["phases"]["call"]["outcome"] = "passed"
    assert check_gate(evidence, phase)[0]
    evidence.validator.assert_not_called()


@pytest.mark.parametrize("phase", ["api_tests", "random"])
def test_production_waveinfo_validator_rejects_missing_receipts(functional_evidence, phase, monkeypatch):
    """Exercise the actual WaveInfo validator's missing-evidence branch, not a permissive stub."""
    evidence = functional_evidence
    evidence.issue.pop("waveform_evidence")
    evidence.writer(evidence.issue_path, evidence.issue)
    validator = Mock(wraps=validate_production_waveform)
    monkeypatch.setattr("toffee_ut.waveform.validate_waveform_evidence", validator)
    passed, result = check_gate(evidence, phase)
    assert not passed and "waveform_evidence" in result["error"]
    validator.assert_called_once()


@pytest.mark.parametrize("phase", ["api_tests", "random"])
@pytest.mark.parametrize("fault", [None, "tampered_receipt", "missing_analysis"])
def test_signed_synthetic_receipt_uses_production_waveinfo_validation(functional_evidence, phase, fault, monkeypatch):
    """Check real receipt signatures and analysis with synthetic protocol data, not hardware observations."""
    evidence = functional_evidence
    payload = {"dut": "Block", "project": "ut_project", "nodeid": evidence.node,
               "run_signature": evidence.checked["record"]["signature"], "timeline": [{"time": 5}]}
    signature = _signature(evidence.workspace, payload, create=True)
    if fault == "tampered_receipt":
        payload["timeline"][0]["time"] = 6
    reference = "results/waveform-evidence/synthetic.json"
    write_json(evidence.root / reference, {**payload, "signature": signature})
    evidence.issue["waveform_evidence"][0]["receipt"] = reference
    if fault == "missing_analysis":
        evidence.issue["waveform_evidence"][0]["analysis"] = ""
    evidence.writer(evidence.issue_path, evidence.issue)
    validator = Mock(wraps=validate_production_waveform)
    monkeypatch.setattr("toffee_ut.waveform.validate_waveform_evidence", validator)
    passed, result = check_gate(evidence, phase)
    assert passed == (fault is None), result
    assert evidence.case["status"] == "FAIL"
    validator.assert_called_once()


@pytest.mark.parametrize("phase", ["api_tests", "random"])
@pytest.mark.parametrize("complete", [False, True])
def test_every_issue_node_requires_its_own_waveinfo_evidence(functional_evidence, phase, complete):
    """One node's receipt cannot stand in for another failing node associated with the same issue."""
    evidence = functional_evidence
    other = evidence.node + "[second]"
    evidence.checked["cases"]["cases"][other] = deepcopy(evidence.case)
    evidence.issue["nodeids"].append(other)
    if complete:
        evidence.issue["waveform_evidence"].append({**evidence.issue["waveform_evidence"][0], "nodeid": other})
    evidence.writer(evidence.issue_path, evidence.issue)
    passed, result = check_gate(evidence, phase)
    assert passed == complete, result
    evidence.validator.assert_called_once()
    assert all(case["status"] == "FAIL" for case in evidence.checked["cases"]["cases"].values())


@pytest.mark.parametrize("phase", ["api_tests", "random"])
def test_a_second_rtl_issue_cannot_waive_a_known_facility_failure(functional_evidence, phase):
    """A validated RTL attribution cannot override a current verification repair obligation."""
    evidence = functional_evidence
    evidence.writer(evidence.root / "docs/bugs/open/facility.md", {
        **evidence.issue, "classification": "verification", "evidence": "Known checker decoding error"})
    assert not check_gate(evidence, phase)[0]


def test_delivery_uses_the_same_rtl_waveinfo_validation(functional_evidence):
    """Sharing attribution must preserve the existing delivery verdict and evidence checks."""
    evidence = functional_evidence
    assert delivery_data(evidence.workspace, "Block", "ut_project")["status"] == "FAIL"
    evidence.validator.assert_called_once()
    evidence.issue.pop("waveform_evidence")
    evidence.writer(evidence.issue_path, evidence.issue)
    with pytest.raises(ValueError, match="waveform_evidence"):
        delivery_data(evidence.workspace, "Block", "ut_project")


@pytest.mark.parametrize("phase", ["api_tests", "random"])
@pytest.mark.parametrize("body", [
    'pytest.fail("pending implementation")',
    'assert False, "pending implementation"',
    'raise AssertionError("pending implementation")',
])
def test_rtl_issue_cannot_give_failure_only_templates_functional_execution_credit(functional_evidence, phase, body):
    """The RTL FAIL exception must retain the implemented-test gate's known-empty-body safeguard."""
    evidence = functional_evidence
    path = evidence.root / "testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'def test_value(env):\n    ' + body + '\n')
    passed, result = check_gate(evidence, phase)
    assert not passed, "The new functional FAIL exception credited a known failure-only template"
    assert "failure-only" in result["error"] and "test_value" in result["error"]
    assert evidence.case["status"] == "FAIL"


@pytest.mark.parametrize("phase", ["api_tests", "random"])
def test_directed_functional_failure_does_not_require_unselected_templates_implemented(functional_evidence, phase):
    """An unrelated template must not turn a directed API check into a full implementation gate."""
    evidence = functional_evidence
    path = evidence.root / "testbenches/block/tests/test_contract.py"
    path.write_text('import pytest\n@pytest.mark.scenario("S1")\n'
                    'async def test_value(env):\n    await env.check_transaction()\n'
                    '    pytest.fail("actual mismatch")\n'
                    'def test_pending(env):\n    pytest.fail("pending implementation")\n')
    passed, result = check_gate(evidence, phase)
    assert passed, result
    assert evidence.case["status"] == "FAIL"


@pytest.mark.parametrize("phase", ["api_tests", "random"])
@pytest.mark.parametrize("real_work", [False, True])
def test_functional_failure_identity_handles_class_and_separator_in_parameter_id(functional_evidence, phase, real_work):
    """Class/parameter nodeids use the same narrow template identity as batch implementation checks."""
    evidence = functional_evidence
    path = evidence.root / "testbenches/block/tests/test_contract.py"
    body = '        await env.check_transaction()\n' if real_work else ''
    path.write_text('import pytest\nclass TestQueue:\n    @pytest.mark.scenario("S1")\n'
                    '    async def test_value(self, env):\n' + body +
                    '        pytest.fail("recorded failure")\n')
    old = evidence.node
    evidence.node = old.partition("::")[0] + "::TestQueue::test_value[left::right]"
    evidence.checked["cases"]["cases"] = {evidence.node: evidence.case}
    evidence.issue["nodeids"] = [evidence.node]
    evidence.issue["waveform_evidence"][0]["nodeid"] = evidence.node
    evidence.writer(evidence.issue_path, evidence.issue)
    review = read_spec(evidence.review_path, "stage_evidence", "Block")
    review["reviews"]["random"]["strategies"][0]["nodeid"] = evidence.node
    evidence.writer(evidence.review_path, review)
    passed, result = check_gate(evidence, phase)
    assert passed == real_work, result
    assert evidence.case["status"] == "FAIL"
    if real_work:
        evidence.validator.assert_called_once()
    else:
        evidence.validator.assert_not_called()
