"""Pure rendering regressions: synthetic receipts only, with no Toffee runtime or DUT."""

from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import unquote

import pytest

from toffee_ut.reports import SUMMARY_END, SUMMARY_START, render_summary, report_link


@pytest.fixture
def report_data():
    """Provide the report projection without running an adapter, stage or simulator."""
    node = "testbenches/block/tests/test_contract.py::test_value[param]"
    identity = {"class": "DUTBlock", "source": "/work/ut_project/dut/Block/__init__.py"}
    phases = {phase: {"outcome": "passed", "duration": 0.01, "wasxfail": None}
              for phase in ("setup", "call", "teardown")}
    return {
        "status": "INCOMPLETE", "run": "results/synthetic", "tests": {"PASS": 1}, "full_selection": True,
        "problems": [], "missing_scenarios": [], "unconfirmed_requirements": ["R1"], "scope_exclusions": [],
        "static_candidates": [], "unregistered_cases": [], "unclassified_failures": [], "failing_nodes": [],
        "issues": [], "scenarios": {"S1": {"scope": "active", "nodeids": [node], "outcomes": {"PASS": 1}}},
        "functional_coverage": {"covered": True, "groups": []},
        "native_coverage": {"required": False, "review": {"state": "missing"},
                            **{metric: {"state": "not_collected", "coverage": None}
                               for metric in ("line", "branch", "toggle")}},
        "requested_seed": 17, "coverage_artifacts": [], "receipt_signature": "synthetic-not-a-real-receipt",
        "case_counts": {"all": {"total": 1, "outcomes": {"PASS": 1}},
                        "functional": {"total": 1, "outcomes": {"PASS": 1}},
                        "selftest": {"total": 0, "outcomes": {}}},
        "case_details": {node: {"status": "PASS", "phases": phases, "selftest": False, "roles": ["api"],
                                 "scenarios": ["S1"], "native_duts": [identity], "declared_native_seed": 17,
                                 "waveforms": [], "waveform_errors": []}},
        "contracts": {"design_path": "docs/spec/design/Block.md",
                      "verification_path": "docs/spec/verification/Block.md",
                      "requirements": {"R1": {"id": "R1", "statement": "Identity is preserved",
                          "precondition": "Legal input", "observation": "Returned value", "timing": "On response",
                          "source": "inputs/interface.md#identity", "basis": "inferred", "next_action": "Confirm source"}},
                      "scenarios": {"S1": {"id": "S1", "requirement": "R1", "stimulus": "Offer one legal input",
                          "expected": "Same value", "oracle": "Candidate interface contract",
                          "completion": "Compare returned value", "status": "active"}}},
        "provenance": {"project_root": "/work/ut_project", "workspace_root": "/work",
                       "runtime": {"python": "/runtime/bin/python", "toffee_version": "synthetic"},
                       "selection": {"targets": ["testbenches/block/tests"], "keyword": "", "markers": ""},
                       "returncode": 0, "source_identity": {"files": 3, "sha256": "synthetic-source-map-digest"},
                       "native_builds": [{"name": "DUTBlock", "build_id": "synthetic-build", "file_count": 1,
                                          "native_duts": [identity]}],
                       "raw_artifacts": ["results/synthetic/cases.json", "results/synthetic/manifest.json",
                                         "results/synthetic/receipt.json", "results/synthetic/stdout.log"]},
    }


def test_complete_view_is_deterministic_literal_and_does_not_mutate_evidence(report_data):
    """Human and machine views share evidence, preserve raw data and state proof limits."""
    before = deepcopy(report_data)
    text = render_summary(report_data)
    assert text == render_summary(report_data)
    assert report_data == before
    structured = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1])
    assert structured == report_data
    assert text.count("<details>") == 1
    for phrase in ("Full selection: true", "Delivery status: INCOMPLETE", "| functional | 1 |",
                   "| selftest | 0 |", "Independent root-cause count: not established",
                   "planned contract", "not established by this run receipt", "per-UID",
                   "declared_native_seed: 17", "effective native seed: not proved",
                   "synthetic-build", "not a hardware verdict"):
        assert phrase in text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6} ", line):
            assert lines[index - 1] == "" and lines[index + 1] == ""


def test_all_issue_links_and_unattributed_failures_survive_without_root_grouping(report_data):
    """One case can link several issues while unclassified failures remain visible."""
    node, case = next(iter(report_data["case_details"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"].update(outcome="failed", failure="identical assertion text")
    other = node + "-other"
    report_data["case_details"][other] = deepcopy(case)
    report_data["failing_nodes"] = [node, other]
    report_data["unclassified_failures"] = [other]
    report_data["issues"] = [{"path": f"docs/bugs/open/{name}.md", "classification": "unconfirmed",
                              "state": "open", "run": "results/synthetic", "nodeids": [node],
                              "requirement": "R1", "evidence": "Not a phase diagnostic"}
                             for name in ("first", "second")]
    text = render_summary(report_data)
    human = text.split("### Structured evidence summary")[0]
    assert "Failed case count: 2. Current-run issue record count: 2." in human
    assert "(bugs/open/first.md)" in human and "(bugs/open/second.md)" in human
    assert human.count("identical assertion text") == 2
    assert "Not a phase diagnostic" not in human
    assert "Unattributed failing cases" in human and "-other" in human
    assert "Independent root-cause count: not established" in human
    assert "inferred" in human and "../../inputs/interface.md#identity" in human


def test_diagnostics_and_contracts_cannot_inject_markdown_html_or_markers(report_data):
    """Untrusted evidence is literal in human views and round-trips through the JSON view."""
    payload = '\n</details><script>alert("x")</script>\n```\n# injected\n| a | b |\n' + SUMMARY_START
    node, case = report_data["case_details"].popitem()
    report_data["case_details"][node + payload] = case
    case["phases"]["call"].update(outcome="failed", failure=payload)
    report_data["contracts"]["scenarios"]["S1"]["expected"] = payload
    text = render_summary(report_data)
    human = text.split("### Structured evidence summary")[0]
    assert "<script>" not in human and "\n# injected" not in human
    assert "&lt;script&gt;" in human and "&#96;&#96;&#96;" in human
    assert "&#124;" in human
    assert text.count(SUMMARY_START) == text.count(SUMMARY_END) == 1
    assert json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1]) == report_data


@pytest.mark.parametrize("path,workspace,expected", [
    ("results/run x/a(1)|`#.json", False, "../results/run%20x/a%281%29%7C%60%23.json"),
    ("/work/ut_project/results/run/file.json", False, "../results/run/file.json"),
    ("inputs/spec x.md#section(1)", True, "../../inputs/spec%20x.md#section%281%29"),
    ("docs/bugs/open/a.md", False, "bugs/open/a.md"),
    ('https://example.org/spec?q="x"&n=(1)#a', True, 'https://example.org/spec?q=%22x%22&n=%281%29#a'),
    ("javascript:alert(1)", False, "../javascript%3Aalert%281%29"),
])
def test_links_are_relative_to_report_and_special_characters_are_encoded(report_data, path, workspace, expected):
    """Local results, absolute artifacts, sources and URLs use safe report-relative targets."""
    link = report_link(report_data, path, workspace=workspace)
    assert link.endswith("(" + expected + ")")
    if path.startswith("results/"):
        assert unquote(expected) == "../" + path


def test_missing_metadata_and_blocking_text_do_not_create_proof_claims(report_data):
    """No test-name or error-string heuristic upgrades templates, oracles or completion."""
    case = next(iter(report_data["case_details"].values()))
    case.pop("declared_native_seed")
    case["phases"] = {"setup": {"outcome": "failed", "failure": 'pytest.fail("blocked template")'}}
    case["native_duts"] = []
    text = render_summary(report_data).split("### Structured evidence summary")[0]
    assert "| call | not recorded |" in text and "| teardown | not recorded |" in text
    assert "declared_native_seed: not recorded" in text
    assert "blocked template" in text
    assert "no native execution credit inferred" in text
    assert "Implementation status" in text and "not established by this run receipt" in text


def test_waveforms_and_setup_teardown_failures_retain_case_identity(report_data):
    """Each real phase failure and waveform path stays attached to its exact case and DUT."""
    case = next(iter(report_data["case_details"].values()))
    identity = case["native_duts"][0]
    case["phases"]["setup"].update(outcome="failed", failure="original setup mismatch")
    case["phases"]["teardown"].update(outcome="failed", failure="original teardown mismatch")
    case["waveforms"] = [{"path": "results/synthetic/waves/a (b)|#.fst", "native_dut": identity}]
    case["waveform_errors"] = ["capture warning <unsafe>"]
    human = render_summary(report_data).split("### Structured evidence summary")[0]
    assert "original setup mismatch" in human and "original teardown mismatch" in human
    assert "(../results/synthetic/waves/a%20%28b%29%7C%23.fst)" in human
    assert "capture warning &lt;unsafe&gt;" in human
    assert "links do not prove analysis or continued file availability" in human


def test_selftest_without_scenario_does_not_acquire_planned_obligations(report_data):
    """Infrastructure selftests or unknown tags cannot borrow another case's planned oracle."""
    case = next(iter(report_data["case_details"].values()))
    case.update(selftest=True, scenarios=[])
    human = render_summary(report_data).split("### Structured evidence summary")[0]
    assert "selftest: true" in human and "No scenario tags recorded" in human
    assert "Candidate interface contract" not in human
    case["scenarios"] = ["selftest-only"]
    human = render_summary(report_data).split("### Structured evidence summary")[0]
    assert "No maintained scenario contract; no obligation inferred" in human


def test_traceability_keeps_unexecuted_and_excluded_scenarios_visible(report_data):
    """A missing call and excluded scope stay visible without inferred checking credit."""
    before = deepcopy(report_data)
    for scenario, scope in (("S-missing", "active"), ("S-deferred", "deferred"), ("S-outside", "out-of-domain")):
        contract = deepcopy(report_data["contracts"]["scenarios"]["S1"])
        contract.update(id=scenario, status=scope, reason="Unresolved boundary | no run <yet>")
        report_data["contracts"]["scenarios"][scenario] = contract
        report_data["scenarios"][scenario] = {"scope": scope, "nodeids": [], "outcomes": {}}
    source = deepcopy(report_data)
    text = render_summary(report_data)
    human = text.split("### Scenario-to-case traceability\n", 1)[1].split("### Bug / issue records", 1)[0]
    for scenario in ("S1", "S-missing", "S-deferred", "S-outside"):
        assert "| " + scenario + " | R1 / inferred |" in human
    assert human.count("No matching call-phase candidates recorded") == 3
    assert "Unresolved boundary &#124; no run &lt;yet&gt;" in human
    assert "not requirement verdicts" in human and "not proof of native execution" in human
    assert report_data == source
    assert json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1]) == source
    assert before["status"] == report_data["status"] == "INCOMPLETE"


def test_traceability_preserves_many_to_many_case_links_without_adding_credit(report_data):
    """Several tags and cases remain literal links rather than independent requirement passes."""
    node = next(iter(report_data["case_details"]))
    other = node + "[other::parameter]"
    second = deepcopy(report_data["case_details"][node])
    second.update(status="FAIL", scenarios=["S1", "S2"])
    second["phases"]["call"].update(outcome="failed", failure="recorded mismatch")
    report_data["case_details"][other] = second
    report_data["tests"] = {"PASS": 1, "FAIL": 1}
    report_data["failing_nodes"] = report_data["unclassified_failures"] = [other]
    report_data["status"] = "FAIL"
    for population in ("all", "functional"):
        report_data["case_counts"][population] = {"total": 2, "outcomes": {"PASS": 1, "FAIL": 1}}
    report_data["contracts"]["scenarios"]["S2"] = {
        **report_data["contracts"]["scenarios"]["S1"], "id": "S2"}
    report_data["scenarios"]["S1"].update(nodeids=[node, other], outcomes={"PASS": 1, "FAIL": 1})
    report_data["scenarios"]["S2"] = {"scope": "active", "nodeids": [other], "outcomes": {"FAIL": 1}}
    text = render_summary(report_data)
    human = text.split("### Scenario-to-case traceability\n", 1)[1].split("### Bug / issue records", 1)[0]
    assert "| S1 |" in human and "| S2 |" in human
    assert human.count("other::parameter") == 2
    assert "&quot;FAIL&quot;: 1" in human and "rows can share nodeids" in human
    assert report_data["case_counts"]["functional"]["total"] == 2
    assert report_data["status"] == "FAIL"


def test_guide_contains_the_complete_current_generated_example():
    """The normative example includes all human views and exactly the canonical JSON block."""
    guide = Path(__file__).parents[2] / "src/toffee_ut/Guide_Doc/ut-results.md"
    example = guide.read_text().split(SUMMARY_START, 1)[1].split(SUMMARY_END, 1)[0]
    data = json.loads(re.search(r"```json\n(.*?)\n```", example, re.S)[1])
    assert SUMMARY_START + example + SUMMARY_END == render_summary(data)


def test_runtime_captured_diagnostics_remain_literal_text_not_comparison_proof(report_data):
    """Captured messages are labeled evidence-limited text, not parsed checker or seed results."""
    payload = '</pre></details><script>unsafe</script>\n```\n# not a heading\n| expected | actual |\n' + SUMMARY_START
    capture = {"unit": "unicode_characters", "retention": "head",
               "limits": {"section_chars": 6000, "phase_chars": 12000, "sections": 12},
               "sections": [{"name": "Captured stdout call", "text": payload,
                             "original_chars": len(payload) + 10, "retained_chars": len(payload), "truncated": True}],
               "omitted_sections": 2, "omitted_chars": 30}
    next(iter(report_data["case_details"].values()))["phases"]["call"]["captured_diagnostics"] = capture
    before = deepcopy(report_data)
    text = render_summary(report_data)
    human = text.split("### Structured evidence summary")[0]
    assert "runtime captured diagnostics, not independent proof" in human
    assert "Captured stdout call" in human and "&lt;script&gt;" in human and "&#96;&#96;&#96;" in human
    assert "<script>" not in human and text.count(SUMMARY_START) == text.count(SUMMARY_END) == 1
    assert "\n# not a heading" not in human and "&#35; not a heading" in human
    assert "original_chars" in human and "retained_chars" in human and "truncated" in human
    assert "omitted_sections" in human and "omitted_chars" in human
    assert "not parsed into comparisons, completion or effective seed evidence" in human
    assert report_data == before and render_summary(report_data) == text
    assert json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1]) == before


def test_case_without_capture_does_not_gain_runtime_diagnostic_claims(report_data):
    """Optional absence neither breaks older cases nor implies empty output or functional checking."""
    human = render_summary(report_data).split("### Structured evidence summary")[0]
    assert "**call — runtime captured diagnostics" not in human
    assert "effective native seed: not proved" in human and "Implementation status" in human
