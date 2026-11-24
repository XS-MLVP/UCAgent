"""Bounded pytest diagnostics on synthetic reports and real pure-Python runs, never RTL."""

from copy import deepcopy
import json
import os
import subprocess
import sys
from types import SimpleNamespace

from _pytest.reports import TestReport
import pytest
from toffee.outcomes import case_status, phase_record

from toffee_ut.audit import audit_project, summarize
from toffee_ut.paths import write_json
from toffee_ut.pytest_plugin import CaseEvidence
from toffee_ut.runner import current_run, run_tests, validate_run


def adapted_phase(sections, when="call"):
    """Project one synthetic pytest phase through the real adapter without file writes."""
    report = TestReport("synthetic.py::test_value", ("synthetic.py", 0, "test_value"), {},
                        "passed", None, when, sections=sections, duration=0.01,
                        user_properties=[("custom_expected", "not automatically imported")])
    collector = CaseEvidence(SimpleNamespace(option=SimpleNamespace(numprocesses=0)))
    collector.pytest_runtest_logreport(report)
    row = collector.cases[report.nodeid]["phases"][when]
    assert {key: value for key, value in row.items() if key != "captured_diagnostics"} == phase_record(report)
    return row


def test_current_phase_sections_preserve_order_duplicates_and_standard_text_only():
    """Exact phase names prevent cumulative pytest sections from borrowing earlier output."""
    sections = [("Captured stdout setup", "earlier"), ("Captured stdout call", "first\n"),
                ("Captured log call", "warning\n"), ("Captured stdout call", "first\n"),
                ("Captured stderr call", "error\n"), ("Captured stdout teardown", "later"),
                ("Captured stdout", "unscoped"), ("Captured stdout callback", "wrong suffix"),
                ("custom note call", "not standard"), ("Captured stderr call", {"not": "text"})]
    before = deepcopy(sections)
    row = adapted_phase(sections)
    capture = row["captured_diagnostics"]
    assert [(part["name"], part["text"]) for part in capture["sections"]] == sections[1:5]
    assert capture["unit"] == "unicode_characters" and capture["retention"] == "head"
    assert capture["omitted_sections"] == capture["omitted_chars"] == 0
    assert all(part["original_chars"] == part["retained_chars"] == len(part["text"])
               and not part["truncated"] for part in capture["sections"])
    assert sections == before


def test_unicode_section_and_phase_limits_report_head_truncation_and_omissions():
    """Counts are Unicode code points, with both a per-section and a total phase limit."""
    row = adapted_phase([("Captured stdout call", "\U0001f642" * 7001),
                         ("Captured stderr call", "x" * 6000), ("Captured log call", "end"),
                         ("Captured stdout call", "")])
    capture = row["captured_diagnostics"]
    assert capture["limits"] == {"section_chars": 6000, "phase_chars": 12000, "sections": 12}
    first, second = capture["sections"]
    assert first == {"name": "Captured stdout call", "text": "\U0001f642" * 6000,
                     "original_chars": 7001, "retained_chars": 6000, "truncated": True}
    assert second["retained_chars"] == 6000 and not second["truncated"]
    assert capture["omitted_sections"] == 2 and capture["omitted_chars"] == 3
    partial = adapted_phase([("Captured stdout call", "a" * 6000), ("Captured log call", "b" * 5000),
                             ("Captured stderr call", "c" * 2000)])["captured_diagnostics"]
    assert partial["sections"][-1] == {"name": "Captured stderr call", "text": "c" * 1000,
        "original_chars": 2000, "retained_chars": 1000, "truncated": True}
    assert partial["omitted_sections"] == partial["omitted_chars"] == 0


def test_section_count_is_bounded_even_for_many_empty_sections():
    """Empty sections cannot produce unbounded metadata, and omitted text stays accounted for."""
    capture = adapted_phase([("Captured stdout call", "")] * 1000
                            + [("Captured log call", "end")])["captured_diagnostics"]
    assert len(capture["sections"]) == 12
    assert capture["omitted_sections"] == 989 and capture["omitted_chars"] == 3
    assert all(part["original_chars"] == part["retained_chars"] == 0 for part in capture["sections"])


@pytest.mark.parametrize("sections", [[], [("Captured stdout setup", "not this phase")],
                                     [("custom note call", "not standard")]])
def test_absent_current_capture_does_not_create_diagnostics_or_infer_a_meaning(sections):
    """Missing standard text remains absent, without a fabricated successful observation."""
    assert "captured_diagnostics" not in adapted_phase(sections)


@pytest.mark.parametrize("workers", [1, 2])
def test_real_python_capture_retains_passing_output_and_original_verdicts(project, workers):
    """Real serial/xdist reports retain each phase on PASS/FAIL/ERROR/UNCERTAIN without a DUT."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('''"""Pure Python capture fixture; no native resource or simulator."""
import logging
import sys
import pytest

pytestmark = [pytest.mark.scenario("S1"), pytest.mark.selftest, pytest.mark.api]

def emit(node, phase):
    """Use distinct identities in all standard streams."""
    print(f"{node}:{phase}:stdout")
    print(f"{node}:{phase}:stderr", file=sys.stderr)
    logging.warning("%s:%s:log", node, phase)

@pytest.fixture
def captured(request):
    """Produce setup and teardown output even when the call fails."""
    emit(request.node.name, "setup")
    yield request.node.name
    emit(request.node.name, "teardown")
    if request.node.name == "test_error":
        raise RuntimeError("synthetic teardown failure")

def test_pass(captured):
    """Successful output must not disappear."""
    emit(captured, "call")

def test_fail(captured):
    """Captured text must not hide a real assertion failure."""
    emit(captured, "call")
    assert 1 == 2, "synthetic assertion failure"

def test_error(captured):
    """A passing call cannot hide teardown failure."""
    emit(captured, "call")

@pytest.mark.uncertain(reason="Synthetic evidence remains uncertain")
def test_uncertain(captured):
    """Capturing a message does not upgrade uncertainty."""
    emit(captured, "call")
''')
    result = run_tests(project, "Block", workers=workers, seed=37, waveforms=False,
                       line_coverage_required=False)
    assert result["ok"], result
    assert result["tests"] == {"PASS": 1, "FAIL": 1, "ERROR": 1, "UNCERTAIN": 1}
    checked = current_run(project, "ut_project")
    for node, case in checked["cases"]["cases"].items():
        name = node.rsplit("::", 1)[1]
        assert case["selftest"] and case["roles"] == ["api"] and case["scenarios"] == ["S1"]
        assert not case["native_duts"] and case["declared_native_seed"] is None
        stripped = {}
        for phase, row in case["phases"].items():
            capture = row["captured_diagnostics"]
            assert sorted(part["name"] for part in capture["sections"]) == [
                f"Captured {stream} {phase}" for stream in ("log", "stderr", "stdout")]
            for part in capture["sections"]:
                stream = part["name"].split()[1]
                assert f"{name}:{phase}:{stream}" in part["text"]
                assert all(f"{name}:{other}:" not in part["text"]
                           for other in ("setup", "call", "teardown") if other != phase)
                assert all(f"{other}:" not in part["text"] for other in
                           ("test_pass", "test_fail", "test_error", "test_uncertain") if other != name)
            stripped[phase] = {key: value for key, value in row.items() if key != "captured_diagnostics"}
        assert case_status(stripped) == case["status"]
    path = project / "ut_project" / result["run"] / "cases.json"
    original = path.read_bytes()
    raw = json.loads(original)
    next(iter(raw["cases"].values()))["phases"]["call"]["captured_diagnostics"]["sections"][0]["text"] = "tampered"
    write_json(path, raw)
    with pytest.raises(ValueError, match="Run artifact changed.*cases.json"):
        validate_run(project, "ut_project", checked["record"])
    # Leave the temporary signed run intact for inspection after the negative control.
    path.write_bytes(original)
    assert current_run(project, "ut_project") == checked


@pytest.mark.parametrize("disabled", [False, True])
def test_real_python_no_output_or_disabled_capture_has_no_diagnostic_claim(project, disabled):
    """No output and -s both preserve PASS without inventing captured text or hardware credit."""
    test = project / "ut_project/testbenches/block/tests/test_contract.py"
    test.write_text('"""Pure Python capture absence fixture."""\n'
                    'def test_no_capture():\n    ' + ('print("uncaptured output")' if disabled else 'pass') + '\n')
    root = project / "ut_project"
    destination = root / "cases-capture-fixture.json"
    env = {key: value for key, value in os.environ.items() if key not in {"PYTEST_ADDOPTS", "PYTEST_PLUGINS"}}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run([sys.executable, "-m", "pytest", "-p", "toffee_ut.pytest_plugin",
                             "-p", "no:cacheprovider", f"--toffee-ut-cases={destination}",
                             "--capture=no" if disabled else "--capture=fd", str(test)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(destination.read_text())
    assert data["counts"] == {"PASS": 1}
    case = next(iter(data["cases"].values()))
    assert all("captured_diagnostics" not in phase for phase in case["phases"].values())


def test_summary_captured_text_is_covered_by_the_existing_full_block_gate(project, checked_evidence):
    """A manual change to captured text is rejected without any new gate or required field."""
    source = project / "ut_project/testbenches/block/tests/test_contract.py"
    source.write_text('"""Never executed: capture-to-report projection fixture."""\n')
    row = adapted_phase([("Captured stdout call", "synthetic runtime message")])
    case = next(iter(checked_evidence["cases"]["cases"].values()))
    case["phases"]["call"] = row
    summarize(project, "Block", "ut_project")
    assert audit_project(project, "Block", phase="final")["ok"]
    path = project / "ut_project/docs/README.md"
    original = path.read_text()
    path.write_text(original.replace("synthetic runtime message", "invented message", 1))
    result = audit_project(project, "Block", phase="final")
    assert not result["ok"] and "summary" in result["error"]
    path.write_text(original.replace('&quot;omitted_chars&quot;: 0', '&quot;omitted_chars&quot;: 9', 1))
    result = audit_project(project, "Block", phase="final")
    assert not result["ok"] and "summary" in result["error"]
    path.write_text(original)
    assert audit_project(project, "Block", phase="final")["ok"]
