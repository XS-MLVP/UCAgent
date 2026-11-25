"""Audit and delivery contracts using explicit typed evidence fixtures, not RTL simulation."""

from copy import deepcopy

import pytest

from toffee_ut.audit import audit_project, delivery_data, read_spec, summarize
from toffee_ut.paths import digest, source_identity, write_json
from toffee_ut.project import inspect_inputs


@pytest.fixture
def synthetic_report_evidence(project, contract_writer, monkeypatch):
    """Inject unsigned projection input without Toffee, a native library or any test execution."""
    root = project / "ut_project"
    write_json(root / "results/input_inventory.json", inspect_inputs(
        project, "Block", documents=[], rtl_dirs=["inputs/Block.sv"], mode="derive"))
    contract_writer(root / "docs/reviews/Block-static-review.md", {
        "kind": "static_review", "dut": "Block", "candidates": [],
        "sources": [{"path": "inputs/Block.sv", "sha256": digest(project / "inputs/Block.sv"),
                     "review": "Inventory-only synthetic fixture; no hardware analysis performed"}]})
    source = root / "dut/Block/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('"""Text identity fixture, never imported as a DUT."""\n')
    native = root / "results/report-fixture/native/coverage.dat"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"# SystemC::Coverage-3\n")
    node = "testbenches/block/tests/test_contract.py::test_value"
    case = {"phases": {phase: {"outcome": "passed", "duration": 0.01, "wasxfail": None}
                       for phase in ("setup", "call", "teardown")},
            "status": "PASS", "selftest": False, "roles": ["api"], "declared_native_seed": 17,
            "scenarios": ["S1"], "native_duts": [{"class": "DUTBlock", "source": str(source)}],
            "waveforms": [], "waveform_errors": []}
    data = {"record": {"dut": "Block", "run": "results/report-fixture", "full_selection": True,
                       "seed": 17, "signature": "unsigned-synthetic-projection-input", "line_coverage_required": False,
                       "runtime": {"python": "/synthetic/python", "toffee_version": "synthetic"},
                       "selection": {"targets": ["testbenches/block/tests"], "keyword": "", "markers": ""},
                       "returncode": 0, "source_after": source_identity(root, project)},
            "cases": {"cases": {node: case}},
            "manifest": {"artifacts": [{"kind": "native", "path": str(native), "build": {
                "name": "DUTBlock", "build_id": "synthetic-build", "files": {str(source): digest(source)}}}]}}
    # No functional coverage is invented: delivery stays INCOMPLETE in this fixture.
    for name, content in (("cases.json", data["cases"]), ("manifest.json", data["manifest"]),
                          ("receipt.json", data["record"])):
        write_json(root / "results/report-fixture" / name, content)
    monkeypatch.setattr("toffee_ut.audit.current_run", lambda workspace, project: data)
    return data


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "no_source", "rtl_as_oracle", "unconfirmed_no_action"])
def test_invalid_design_contracts_are_rejected(project, contract_writer, mutation):
    """Neither missing sources nor implementation guesses can silently become confirmed requirements."""
    path = project / "ut_project/docs/spec/design/Block.md"
    data = read_spec(path, "design", "Block")
    if mutation == "empty":
        data["requirements"] = []
    elif mutation == "duplicate":
        data["requirements"].append(deepcopy(data["requirements"][0]))
    elif mutation == "no_source":
        data["requirements"][0]["source"] = "missing.md"
    elif mutation == "rtl_as_oracle":
        data["requirements"][0]["source"] = "inputs/Block.sv"
    else:
        data["requirements"][0]["basis"] = "inferred"
    contract_writer(path, data)
    result = audit_project(project, "Block", phase="design")
    assert not result["ok"] and result["error_code"] and result["next_action"]


@pytest.mark.parametrize("basis,accepted", [("confirmed", False), ("inferred", True)])
def test_systemverilog_header_is_not_an_independent_confirmed_source(project, contract_writer, basis, accepted):
    """RTL headers may support candidate requirements, never independent confirmation."""
    source = project / "inputs/contract.svh"
    source.write_text("// Synthetic header source; never compiled.\n")
    path = project / "ut_project/docs/spec/design/Block.md"
    data = read_spec(path, "design", "Block")
    data["requirements"][0].update(source="inputs/contract.svh", basis=basis)
    if basis == "inferred":
        data["requirements"][0]["next_action"] = "Confirm with independent source"
    contract_writer(path, data)
    result = audit_project(project, "Block", phase="design")
    assert result["ok"] is accepted
    if not accepted:
        assert "independent source" in result["error"]


@pytest.mark.parametrize("suffix", [".v", ".sv", ".vh", ".svh", ".SVH", ".scala"])
def test_rtl_source_alias_is_not_independent_confirmation(project, contract_writer, suffix):
    """A Markdown-named symlink cannot turn its actual RTL target into an oracle."""
    source = project / "inputs" / ("implementation" + suffix)
    source.write_text("// Synthetic source identity fixture; never compiled.\n")
    alias = project / "inputs/independent.md"
    alias.symlink_to(source)
    path = project / "ut_project/docs/spec/design/Block.md"
    data = read_spec(path, "design", "Block")
    data["requirements"][0]["source"] = "inputs/independent.md"
    contract_writer(path, data)
    result = audit_project(project, "Block", phase="design")
    assert not result["ok"] and "independent source" in result["error"]


@pytest.mark.parametrize("mutation", ["empty", "unknown_requirement", "duplicate", "unexplained_exclusion", "no_active"])
def test_invalid_scenario_obligations_are_rejected(project, contract_writer, mutation):
    """Every real requirement needs a scenario or explicit disposition and at least one active obligation."""
    path = project / "ut_project/docs/spec/verification/Block.md"
    data = read_spec(path, "verification", "Block")
    if mutation == "empty":
        data["scenarios"] = []
    elif mutation == "unknown_requirement":
        data["scenarios"][0]["requirement"] = "absent"
    elif mutation == "duplicate":
        data["scenarios"].append(deepcopy(data["scenarios"][0]))
    else:
        data["scenarios"][0]["status"] = "deferred"
        if mutation == "no_active":
            data["scenarios"][0]["reason"] = "Deferred to another owner"
    contract_writer(path, data)
    assert not audit_project(project, "Block", phase="plan")["ok"]


def test_duplicate_yaml_keys_and_wrong_dut_are_not_ambiguous_contracts(project):
    """The parser rejects duplicate YAML keys instead of accepting the last spelling."""
    path = project / "ut_project/docs/spec/design/Block.md"
    path.write_text(path.read_text().replace("dut: Block", "dut: Other\ndut: Block"))
    assert not audit_project(project, "Block", phase="design")["ok"]


def test_two_dut_blocks_can_share_one_existing_markdown_document(project):
    """Adoption can preserve other DUTs' contract blocks in a shared specification."""
    path = project / "ut_project/docs/spec/design/Block.md"
    path.write_text(path.read_text() + '\n```yaml\nkind: design\ndut: AnotherDUT\nrequirements: []\n```\n')
    assert audit_project(project, "Block", phase="design")["ok"]


def test_skeleton_assertions_and_parallel_role_layout_are_rejected(project):
    """Structural checks reject remaining placeholders and simultaneous env.py/env packages."""
    root = project / "ut_project"
    test = root / "testbenches/block/tests/test_contract.py"
    test.write_text('def test_unfinished():\n    assert False, "Not implemented"\n')
    assert "placeholder" in audit_project(project, "Block")["error"]
    (root / "testbenches/block/env").mkdir()
    assert "not both" in audit_project(project, "Block", phase="environment")["error"]


@pytest.mark.parametrize("before,after", [
    ('"status": "INCOMPLETE"', '"status": "PASS"'),
    ("Delivery status: INCOMPLETE", "Delivery status: FAIL"),
    ("Full selection: true", "Full selection: false"),
    ("| functional | 1 |", "| functional | 9 |"),
    ("not established by this run receipt", "proved by this run receipt"),
    ("On response", "Before request"),
])
def test_current_summary_is_machine_derived_and_manual_status_changes_fail(project, synthetic_report_evidence, before, after):
    """The final gate verifies the entire generated block, not just its structured totals."""
    path = project / "ut_project/docs/README.md"
    path.write_text("\n# User notes\n\nKeep this paragraph.\n")
    result = summarize(project, "Block", "ut_project")
    assert result["status"] == "INCOMPLETE"  # No functional coverage in this synthetic fixture.
    assert audit_project(project, "Block", phase="final")["ok"]
    assert "Keep this paragraph." in path.read_text()
    assert summarize(project, "Block", "ut_project") == result
    text = path.read_text()
    assert before in text
    path.write_text(text.replace(before, after, 1))
    assert not audit_project(project, "Block", phase="final")["ok"]


def test_summary_preserves_user_bytes_and_raw_evidence_and_is_idempotent(project, synthetic_report_evidence):
    """Replacing or appending the block never normalizes user newlines or trailing bytes."""
    from toffee_ut.reports import SUMMARY_END, SUMMARY_START

    path = project / "ut_project/docs/README.md"
    prefix, suffix = b"\r\n# User notes\r\n\r\nPreserve spaces.  \r\n", b"\r\nTail.  \t"
    path.write_bytes(prefix + SUMMARY_START.encode() + b"old block" + SUMMARY_END.encode() + suffix)
    raw = deepcopy(synthetic_report_evidence)
    run = project / "ut_project/results/report-fixture"
    raw_files = {path.name: path.read_bytes() for path in run.glob("*.json")}
    data = summarize(project, "Block", "ut_project")
    first = path.read_bytes()
    assert first.startswith(prefix) and first.endswith(suffix)
    assert summarize(project, "Block", "ut_project") == data and path.read_bytes() == first
    assert synthetic_report_evidence == raw
    assert {path.name: path.read_bytes() for path in run.glob("*.json")} == raw_files
    path.write_bytes(prefix)
    summarize(project, "Block", "ut_project")
    assert path.read_bytes().startswith(prefix)


def test_summary_binds_phases_and_multiple_issues_without_changing_verdicts(project, synthetic_report_evidence, contract_writer):
    """Current issue links and captured diagnostics stay separate from planned obligations."""
    node, case = next(iter(synthetic_report_evidence["cases"]["cases"].items()))
    case.update(status="FAIL", roles=["random"], declared_native_seed=19)
    case["phases"]["call"].update(outcome="failed", failure="Actual captured failure | </details>")
    for name in ("first", "second"):
        contract_writer(project / f"ut_project/docs/bugs/open/{name}.md", {
            "kind": "issue", "run": synthetic_report_evidence["record"]["run"], "nodeids": [node],
            "classification": "unconfirmed", "evidence": "Review claim, not captured diagnostic",
            "next_action": "Review original capture"})
    data = summarize(project, "Block", "ut_project")
    assert data["status"] == "FAIL" and len(data["issues"]) == 2
    assert data["case_counts"]["functional"] == {"total": 1, "outcomes": {"FAIL": 1}}
    path = project / "ut_project/docs/README.md"
    assert "Actual captured failure | &lt;/details&gt;" in path.read_text()
    assert audit_project(project, "Block", phase="final")["ok"]
    path.write_text(path.read_text().replace("Actual captured failure | &lt;/details&gt;", "Invented failure", 1))
    assert not audit_project(project, "Block", phase="final")["ok"]


def test_report_population_and_provenance_are_projected_without_copying_source_maps(project, synthetic_report_evidence):
    """Only selftest metadata separates populations; receipt links retain full source identities."""
    cases = synthetic_report_evidence["cases"]["cases"]
    original = next(iter(cases.values()))
    cases["testbenches/shared/tests/test_self.py::test_monitor"] = {**deepcopy(original), "selftest": True}
    data = delivery_data(project, "Block", "ut_project")
    assert data["case_counts"]["all"] == {"total": 2, "outcomes": {"PASS": 2}}
    assert data["case_counts"]["functional"] == data["case_counts"]["selftest"] == {"total": 1, "outcomes": {"PASS": 1}}
    assert len(data["provenance"]["native_builds"][0]["native_duts"]) == 1
    assert data["provenance"]["runtime"] == synthetic_report_evidence["record"]["runtime"]
    assert "source_after" not in data["provenance"] and data["provenance"]["source_identity"]["sha256"]
    assert data["provenance"]["raw_artifacts"] == ["results/report-fixture/cases.json",
        "results/report-fixture/manifest.json", "results/report-fixture/receipt.json"]
    first = data["provenance"]["source_identity"]
    synthetic_report_evidence["record"]["source_after"]["new synthetic input"] = "changed"
    assert delivery_data(project, "Block", "ut_project")["provenance"]["source_identity"] != first


@pytest.mark.parametrize("change", ["requested_seed", "runtime", "phase", "contract", "issue"])
def test_final_rejects_a_summary_of_previous_projection_inputs(project, synthetic_report_evidence, contract_writer, change):
    """Current evidence or maintained-contract changes require regeneration, not stale human views."""
    summarize(project, "Block", "ut_project")
    if change == "requested_seed":
        synthetic_report_evidence["record"]["seed"] = 23
    elif change == "runtime":
        synthetic_report_evidence["record"]["runtime"]["toffee_version"] = "changed synthetic runtime"
    elif change == "phase":
        next(iter(synthetic_report_evidence["cases"]["cases"].values()))["phases"]["call"]["duration"] = 0.02
    elif change == "contract":
        path = project / "ut_project/docs/spec/verification/Block.md"
        plan = read_spec(path, "verification", "Block")
        plan["scenarios"][0]["completion"] = "Changed planned obligation, not actual completion"
        contract_writer(path, plan)
    else:
        contract_writer(project / "ut_project/docs/bugs/open/review.md", {
            "kind": "issue", "run": synthetic_report_evidence["record"]["run"],
            "nodeids": list(synthetic_report_evidence["cases"]["cases"]), "classification": "unconfirmed",
            "evidence": "New synthetic review claim", "next_action": "Review source"})
    result = audit_project(project, "Block", phase="final")
    assert not result["ok"] and "summary" in result["error"]
    summarize(project, "Block", "ut_project")
    assert audit_project(project, "Block", phase="final")["ok"]


@pytest.mark.parametrize("markers", ["missing_end", "duplicate_start", "reversed"])
def test_malformed_owned_boundaries_are_rejected_without_rewriting_user_content(project, synthetic_report_evidence, markers):
    """Byte preservation does not allow missing, duplicated or inverted ownership markers."""
    from toffee_ut.reports import SUMMARY_END, SUMMARY_START

    path = project / "ut_project/docs/README.md"
    text = {"missing_end": SUMMARY_START, "duplicate_start": SUMMARY_START * 2 + SUMMARY_END,
            "reversed": SUMMARY_END + SUMMARY_START}[markers]
    path.write_bytes(text.encode())
    assert not audit_project(project, "Block", phase="final")["ok"]
    with pytest.raises(ValueError, match="markers are malformed"):
        summarize(project, "Block", "ut_project")
    assert path.read_bytes() == text.encode()


@pytest.mark.parametrize("gap", ["basis", "scope", "uncertain", "coverage", "partial", "missing_native", "wrong_native"])
def test_unproved_scope_never_becomes_a_pass(project, checked_evidence, contract_writer, gap):
    """Each independent incomplete-evidence condition changes the delivery verdict."""
    root = project / "ut_project"
    case = next(iter(checked_evidence["cases"]["cases"].values()))
    if gap == "basis":
        path = root / "docs/spec/design/Block.md"
        data = read_spec(path, "design", "Block")
        data["requirements"][0].update(basis="inferred", next_action="Confirm with independent contract owner")
        contract_writer(path, data)
    elif gap == "scope":
        path = root / "docs/spec/verification/Block.md"
        data = read_spec(path, "verification", "Block")
        data["scenarios"].append({**data["scenarios"][0], "id": "S2", "status": "deferred", "reason": "Need confirmation"})
        contract_writer(path, data)
    elif gap == "uncertain":
        case["status"] = "UNCERTAIN"
        case["phases"]["call"]["uncertain"] = {"reason": "Pending confirmation"}
    elif gap == "coverage":
        checked_evidence["manifest"]["artifacts"] = checked_evidence["manifest"]["artifacts"][:1]
    elif gap == "partial":
        checked_evidence["record"]["full_selection"] = False
    elif gap == "missing_native":
        case["native_duts"] = []
    else:
        checked_evidence["manifest"]["artifacts"][0]["build"]["name"] = "DUTOther"
        case["native_duts"][0]["class"] = "DUTOther"
    assert delivery_data(project, "Block", "ut_project")["status"] == "INCOMPLETE"


def test_real_failures_remain_fail_and_require_current_open_triage(project, checked_evidence, contract_writer):
    """A raw RTL FAIL is preserved but cannot claim verified waveform root cause."""
    node, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    assert not audit_project(project, "Block", phase="triage")["ok"]
    issue = project / "ut_project/docs/bugs/open/mismatch.md"
    contract_writer(issue, {"kind": "issue", "run": checked_evidence["record"]["run"], "nodeids": [node],
                           "classification": "rtl", "requirement": "R1", "evidence": "Original assertion mismatch",
                           "next_action": "Keep the failing check and request a DUT fix"})
    assert "waveform_evidence" in audit_project(project, "Block", phase="triage")["error"]
    assert "waveform_evidence" in audit_project(project, "Block", phase="final")["error"]
    contract_writer(issue, {"kind": "issue", "run": checked_evidence["record"]["run"], "nodeids": [node],
                            "classification": "unconfirmed", "evidence": "Original assertion mismatch; native waveform has not been reviewed",
                            "next_action": "Acquire real waveform evidence and retest the confirmed contract"})
    summarize(project, "Block", "ut_project")
    assert audit_project(project, "Block", phase="final")["ok"]
    closed = issue.parent.parent / "closed/mismatch.md"
    closed.parent.mkdir()
    issue.rename(closed)
    assert not audit_project(project, "Block", phase="triage")["ok"]


def test_verification_error_cannot_be_delivered_as_a_dut_bug(project, checked_evidence, contract_writer):
    """Infrastructure classification is a repair obligation, not a hardware FAIL waiver."""
    node, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    contract_writer(project / "ut_project/docs/bugs/open/fixture.md", {
        "kind": "issue", "run": checked_evidence["record"]["run"], "nodeids": [node],
        "classification": "verification", "evidence": "Checker decoded a field incorrectly",
        "next_action": "Fix decoder and retest both controls"})
    summarize(project, "Block", "ut_project")
    assert not audit_project(project, "Block", phase="final")["ok"]


def test_unknown_phase_and_damaged_contract_return_bounded_diagnostics(project):
    """Malformed data returns actionable error_code/error/next_action rather than a traceback."""
    assert not audit_project(project, "Block", phase="imaginary")["ok"]
    path = project / "ut_project/docs/spec/design/Block.md"
    path.write_text("\n# Damaged\n\n```yaml\nkind: design\nrequirements: [\n```\n")
    result = audit_project(project, "Block", phase="design")
    assert not result["ok"] and len(result["error"]) <= 2000 and result["next_action"]


def test_untyped_historical_issue_notes_are_preserved_but_not_current_triage(project, checked_evidence):
    """Existing Markdown history/indexes need not be rewritten into the new issue schema."""
    path = project / "ut_project/docs/bugs/open/README.md"
    path.parent.mkdir(parents=True)
    text = "\n# Existing historical notes\n\nPreserve the original evidence.\n"
    path.write_text(text)
    assert delivery_data(project, "Block", "ut_project")["status"] == "PASS"
    node, case = next(iter(checked_evidence["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    assert delivery_data(project, "Block", "ut_project")["unclassified_failures"] == [node]
    assert path.read_text() == text
