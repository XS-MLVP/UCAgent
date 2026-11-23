"""Deterministic checker hierarchy and coverage failure diagnostics."""
from pathlib import Path

import pytest
import yaml

from formal.preflight import PreflightError
from formal.tools import render_environment
from formal.checkers.formal import CoverageAnalysisChecker, ScriptGenerationChecker
from ucagent.util.config import Config
import formal.checkers.formal as checks


def write_design(tmp_path, body, whitebox=None):
    """Create a scalar design with legitimate internal hierarchy for generic preflight tests."""
    dut = tmp_path / "RouteUnit"
    dut.mkdir()
    (dut / "rtl.sv").write_text(
        "module Inner(input logic a,output logic q); assign q=a; endmodule\n"
        "module RouteUnit(input logic a,output logic y); wire internal; "
        "Inner child(a,internal); assign y=child.q; endmodule\n")
    output = tmp_path / "proof"
    output.mkdir()
    records = {"dut": "RouteUnit", "basic_info": {"clock_reset": {"clock_count": 0}},
               "spec": {"whitebox_signals": whitebox or [], "function_groups": [
                   {"id": "FG-ROUTE", "name": "Route", "functions": [
                       {"id": "FC-VALUE", "description": "Value", "check_points": [
                           {"id": "CK-VALUE", "style": "Comb", "description": "Value relation", "sva_body": body}]}]}]}}
    (output / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    return output


def test_checker_external_hierarchy_rejected_with_exact_ck_and_location(tmp_path):
    """Legal upward lookup must fail early when unsupported by the proof tool's checker dialect."""
    output = write_design(tmp_path, "y == u_dut.child.q;")
    with pytest.raises(PreflightError) as caught:
        render_environment(str(tmp_path), "proof", "RouteUnit")
    diagnostic = caught.value.diagnostic
    row = next(item for item in diagnostic["diagnostics"] if item["code"] == "formal_checker_hierarchy_unsupported")
    assert row["ck_id"] == "CK-VALUE"
    assert row["path"] == "proof/tests/RouteUnit_checker.sv"
    assert row["line"] > 0 and row["column"] > 0
    assert row["reference"] == "u_dut.child.q"
    assert "spec.whitebox_signals" in row["next_action"]
    assert diagnostic["next_action"]
    assert not (output / "tests/RouteUnit_checker.sv").exists()


def test_wrapper_whitebox_binding_and_rtl_internal_hierarchy_are_allowed(tmp_path):
    """A checker port bound to an actual internal net is supported; RTL hierarchy is not banned."""
    write_design(tmp_path, "y == internal;", ["logic internal"])
    result = render_environment(str(tmp_path), "proof", "RouteUnit")
    assert result["status"] == "passed"
    wrapper = (tmp_path / "proof/tests/RouteUnit_wrapper.sv").read_text()
    assert "assign internal = u_dut.internal;" in wrapper


def test_mixed_reset_is_accepted_and_resolved_consistently(tmp_path):
    """Async assertion and sync release are independent metadata for a real DUT input."""
    output = write_design(tmp_path, "y == a;")
    source = tmp_path / "RouteUnit" / "rtl.sv"
    source.write_text("module RouteUnit(input logic sysclk, reset, a, output logic y); assign y = a; endmodule\n")
    path = output / ".formal_records.yaml"
    records = yaml.safe_load(path.read_text())
    reset = {"clock_count": 1, "clock_signal": "sysclk", "reset_signal": "reset",
             "reset_type": "低有效异步断言，同步释放", "reset_active_level": "low",
             "reset_assertion": "async", "reset_release": "sync"}
    records["basic_info"]["clock_reset"] = reset
    path.write_text(yaml.safe_dump(records))
    assert render_environment(str(tmp_path), "proof", "RouteUnit")["status"] == "passed"
    wrapper = (output / "tests/RouteUnit_wrapper.sv").read_text()
    tcl = (output / "tests/RouteUnit_formal.tcl").read_text()
    assert "assign reset = rst_n;" in wrapper
    assert "def_clk clk" in tcl and "def_rst rst_n -value 0" in tcl
    reset["reset_signal"] = "y"
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(PreflightError) as caught:
        render_environment(str(tmp_path), "proof", "RouteUnit")
    assert caught.value.diagnostic["layer"] == "clock_reset"
    assert "reset_signal" in caught.value.diagnostic["diagnostics"][0]["message"]
    assert (output / "tests/RouteUnit_wrapper.sv").read_text() == wrapper
    source.write_text(source.read_text().replace("reset", "rst_n"))
    reset.update(reset_signal="rst_n", reset_active_level="high")
    path.write_text(yaml.safe_dump(records))
    render_environment(str(tmp_path), "proof", "RouteUnit")
    assert ".rst_n(~rst_n)" in (output / "tests/RouteUnit_wrapper.sv").read_text()


def test_missing_actual_whitebox_binding_fails_before_publication(tmp_path):
    """A declared checker input cannot invent a missing DUT signal."""
    output = write_design(tmp_path, "y == missing;", ["logic missing"])
    with pytest.raises(PreflightError) as caught:
        render_environment(str(tmp_path), "proof", "RouteUnit")
    assert any("missing" in row["message"] for row in caught.value.diagnostic["diagnostics"])
    assert not (output / "tests/RouteUnit_wrapper.sv").exists()


def test_stage_script_check_preserves_preflight_diagnostic(tmp_path):
    """Stage feedback retains the precise CK diagnostic instead of burying it in prose."""
    write_design(tmp_path, "y == u_dut.child.q;")
    checker = ScriptGenerationChecker("RouteUnit")
    checker.cfg = Config({"output": "proof"})
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "formal_sva_preflight"
    assert result["diagnostics"][0]["ck_id"] == "CK-VALUE"
    assert result["next_action"]


@pytest.mark.parametrize("uncovered", [[], ["some_internal_net"]])
def test_coverage_insufficient_explains_missing_detail_without_fabricating_signals(tmp_path, uncovered):
    """Low coverage stays blocking, with distinct next actions when the tool supplies no cone detail."""
    checker = CoverageAnalysisChecker("RouteUnit", coi_threshold=90)
    from formal.skills.lib.formal_paths import FormalPaths
    checker.paths = FormalPaths(dut="RouteUnit", out="proof", workspace=str(tmp_path))
    coi = {
        "overall_pct": 87.38, "uncovered": uncovered,
        "nets": {"covered": 1184, "total": 1355, "pct": 87.38},
        "dffs": {"covered": 0, "total": 0, "pct": 0.0}}
    checker._require_execution = lambda: (True, {"coverage": {"status": "verified", "run_id": "a" * 32,
        "input_fingerprint": "b" * 64, "report": "proof/formal_runs/original/fanin.rep", "sha256": "c" * 64,
        "metrics": coi}})
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "formal_coverage_below_threshold"
    assert result["expected"]["overall_pct_min"] == 90
    assert result["observed"]["signal_detail_available"] is bool(uncovered)
    assert result["observed"]["uncovered_signals"] == uncovered
    assert result["artifacts"]["run_id"] == "a" * 32
    assert result["report"]["Dffs COI"] == "N/A (no flip-flops)"
    assert ("no uncovered-signal detail" in result["next_action"]) is not bool(uncovered)
