"""Disposable smoke validates the actual compiler/solver without consuming official proof goals."""

import hashlib
import json
from pathlib import Path
import shutil
import time

import pytest
import yaml

from formal.execution import FormalExecution, ACTIVE_RUNS
from formal.tools import AnalyzeFormal, FormalData, RunFormal
from ucagent.util.config import Config


def finish(execution, run, limit=30):
    """Wait for a selected real-tool smoke run within a bounded test deadline."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        result = execution.status(scope="preflight", run_id=run["run_id"])
        if result["status"] not in ACTIVE_RUNS:
            return result
        time.sleep(.1)
    execution.cancel(scope="preflight", run_id=run["run_id"])
    pytest.fail("Toolchain smoke did not stop within the test budget")


@pytest.mark.parametrize("clocked", [False, True])
def test_actual_toolchain_smoke_has_no_official_ck_or_generation(tmp_path, clocked):
    """A no-CK or broken-body plan cannot contaminate a solver-health smoke result."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    dut = tmp_path / "DUT"
    dut.mkdir()
    (dut / "DUT.sv").write_text("module DUT(input logic a, output logic y" + (",input logic clk, rst_n" if clocked else "") + ");assign y=a;endmodule\n")
    output = tmp_path / "proofs"
    output.mkdir()
    records = {"dut": "DUT", "basic_info": {"clock_reset": {"clock_count": 1 if clocked else 0,
               **({"clock_signal": "clk", "reset_signal": "rst_n", "reset_active_level": "low"} if clocked else {})}},
               "spec": {"parameters": {}, "whitebox_signals": ["logic official_observer"], "function_groups": []},
               "extra_config": {"tcl": {"extra_commands": ["error OFFICIAL_ONLY"]}}}
    path = output / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(records))
    cfg = Config({"runtime_options": {"formal_batched_sva": True, "formal_execution": {"setup_timeout_s": 10}}})
    execution = FormalExecution(str(tmp_path), "proofs", "DUT", cfg)
    tool = RunFormal(str(tmp_path), "proofs", "DUT", cfg)
    before = path.read_bytes()
    try:
        result = tool._run(action="preflight")
        complete = finish(execution, result)
        assert complete["status"] == "COMPLETED", complete
        assert complete["preflight_complete"] and not complete["proof_complete"]
        assert complete["counts"] == {"COVER_REACHED": 1}
        assert execution.check_smoke()["preflight_complete"]
        assert path.read_bytes() == before
        inputs = output / "formal_runs" / result["run_id"] / "inputs/proofs/tests"
        assert "OFFICIAL_ONLY" not in (inputs / "DUT_formal.tcl").read_text()
        assert "official_observer" not in (inputs / "DUT_wrapper.sv").read_text()
        assert not (output / "tests").exists()
        assert execution.status()["status"] == "NOT_STARTED"
        from formal.dashboard import FormalDashboard
        projection = FormalDashboard(tmp_path, archived=True, output="proofs").view()
        assert projection["run"] is None and projection["counts"] == {}
        assert not (output / "formal_runs/current.json").exists()
        assert not (output / "formal_runs/baseline.json").exists()
        # Implemented, pending, malformed official properties and assumptions are not read by smoke.
        records["spec"]["function_groups"] = [{"id": "FG-A", "functions": [{"id": "FC-X", "check_points": [
            {"id": "CK-ONE", "style": "Comb", "description": "broken official body", "sva_body": "(!"},
            {"id": "CK-ASSUME", "style": "Assume", "description": "pending assumption", "sva_body": "[LLM-TODO]"}]}]}]
        records["spec"]["whitebox_signals"] = ["logic different_official_observer"]
        records["extra_config"]["tcl"]["extra_commands"] = ["error CHANGED_OFFICIAL_ONLY"]
        path.write_text(yaml.safe_dump(records))
        assert execution.check_smoke()["preflight_complete"]
        assert tool._run(action="preflight")["run_id"] == result["run_id"]
        assert not (output / "tests").exists()
        analyzer = AnalyzeFormal(workspace=str(tmp_path), output_dir="proofs", dut="DUT", cfg=cfg)
        analysis = analyzer.invoke({"mode": "environment", "run_id": result["run_id"]})
        assert analysis["status"] == "completed", analysis
        assert analysis["scope"] == "preflight"
        archived_checker = output / "formal_runs" / result["run_id"] / "inputs/proofs/tests/DUT_checker.sv"
        with archived_checker.open("a") as handle:
            handle.write("// changed after the run\n")
        with pytest.raises(ValueError, match="archived Formal inputs have changed"):
            analyzer._run(mode="environment", run_id=result["run_id"])
    finally:
        execution.cancel(scope="preflight", run_id=result["run_id"])


def test_smoke_parameter_elaboration_failure_does_not_publish_official_files(tmp_path):
    """Invalid overrides fail locally and cannot produce a misleading successful smoke."""
    d = tmp_path / "DUT"
    d.mkdir()
    (d / "DUT.v").write_text("module DUT #(parameter WIDTH=4)(input [WIDTH-1:0] a,output [WIDTH-1:0] y);assign y=a;endmodule")
    out = tmp_path / "p"
    out.mkdir()
    (out / ".formal_records.yaml").write_text(yaml.safe_dump({"dut": "DUT", "spec": {"parameters": {"MISSING": 1}, "function_groups": []}}))
    execution = FormalExecution(str(tmp_path), "p", "DUT", Config({}))
    with pytest.raises(ValueError, match="MISSING"):
        execution.run(preflight=True)
    assert not (out / "tests").exists()


def test_missing_official_assumptions_block_selected_without_smoke_freeze(tmp_path, monkeypatch):
    """Formal selected proofs may omit other goals, never a pending shared Assume."""
    from formal.tools import render_environment
    from formal.data import FormalDataStore

    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    source = tmp_path / "DUT"
    source.mkdir()
    (source / "DUT.v").write_text("module DUT(input a,output y);assign y=a;endmodule")
    out = tmp_path / "proofs"
    out.mkdir()
    body = {"dut": "DUT", "spec": {"function_groups": [{"id": "FG-A", "functions": [
        {"id": "FC-ENV", "title": "Environment", "description": "Legal inputs", "review_order": 1,
         "check_points": [{"id": "CK-ENV", "style": "Assume", "description": "Known input"}]},
        {"id": "FC-Y", "title": "Output", "description": "Output relation", "review_order": 2,
         "check_points": [{"id": "CK-Y", "style": "Comb", "description": "Identity", "sva_body": "y==a;"}]}]}]}}
    path = out / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(body))
    cfg = Config({"runtime_options": {"formal_batched_sva": True}})
    store = FormalDataStore(str(tmp_path), "proofs", "DUT", cfg=cfg)
    prepared = store.prepare("sva")
    assert prepared["check_points"]["items"][0]["id"] == "CK-ENV"
    assert prepared["run_call"] is None
    assert not prepared["clock_reset"]["has_clock"]
    port_request = prepared["inspect_ports_call"]["request"]
    ports = FormalData(str(tmp_path), "proofs", "DUT", cfg).invoke({"request": {**port_request, "query": "y"}})
    assert [(row["name"], row["direction"]) for row in ports["ports"]["items"]] == [("y", "output")]
    render_environment(str(tmp_path), "proofs", "DUT")
    execution = FormalExecution(str(tmp_path), "proofs", "DUT", cfg)
    with pytest.raises(ValueError, match="planned shared Assume"):
        execution.run(fc_id="FC-Y")
    assert not (out / "formal_runs/selected.json").exists()
