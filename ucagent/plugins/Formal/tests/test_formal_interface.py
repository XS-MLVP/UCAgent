"""Source-backed interface binding across unrelated parameterized Formal designs."""

import builtins
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest
import yaml

from formal.interface import inspect_interface
from formal.tools import render_environment
from formal.execution import FormalExecution, ACTIVE_RUNS
from ucagent.util.config import Config


def design(tmp_path, text, name="RouteSelector"):
    """Write a fresh source unit with independently named DUT and output directories."""
    source = tmp_path / name
    source.mkdir()
    (source / f"{name}.sv").write_text(text, encoding="utf-8")
    return name


def test_declared_defaults_recompute_after_override_and_preserve_zero(tmp_path):
    """Omitted dependent defaults must not be copied into explicit DUT overrides."""
    name = design(tmp_path, "module RouteSelector #(parameter LANES=4, WIDTH=LANES*2, MODE=1, localparam LIMIT=WIDTH+1)(input signed[WIDTH-1:0] left,right, output selected); assign selected=left[0]; endmodule")
    default = inspect_interface(str(tmp_path), "proof", name, {})
    assert {row["name"]: row["value"] for row in default["parameters"]} == {"LANES": 4, "WIDTH": 8, "MODE": 1, "LIMIT": 9}
    assert default["explicit_overrides"] == {}
    overridden = inspect_interface(str(tmp_path), "proof", name, {"LANES": 6, "MODE": 0})
    values = {row["name"]: row["value"] for row in overridden["parameters"]}
    assert values == {"LANES": 6, "WIDTH": 12, "MODE": 0, "LIMIT": 13}
    assert set(overridden["explicit_overrides"]) == {"LANES", "MODE"}
    assert [(row["name"], row["width"], row["signed"]) for row in overridden["ports"]] == [("left", 12, True), ("right", 12, True), ("selected", 1, False)]
    with pytest.raises(ValueError, match="unknown, local"):
        inspect_interface(str(tmp_path), "proof", name, {"LIMIT": 3})
    with pytest.raises(ValueError, match="unknown, local"):
        inspect_interface(str(tmp_path), "proof", name, {"MISSING": 3})


def test_large_signed_values_and_ascending_port_range(tmp_path):
    """Concrete declarations preserve signedness, width and HDL index direction."""
    name = design(tmp_path, "module RouteSelector #(parameter signed[79:0] NEG=-2, parameter[95:0] MASK=96'h800000000000000000000001)(input[0:7] request, output signed[79:0] response); assign response=NEG; endmodule")
    result = inspect_interface(str(tmp_path), "proof", name)
    values = {row["name"]: row for row in result["parameters"]}
    assert values["NEG"]["value"] == -2 and values["NEG"]["signed"]
    assert values["MASK"]["value"] > 2**64
    assert values["NEG"]["sv_literal"] == "80'shfffffffffffffffffffe"
    assert result["ports"][0]["declaration"] == "input logic [0:7] request"


def test_top_selection_ordered_packages_and_nonansi_ports(tmp_path):
    """An unrelated root module cannot replace the named DUT during inspection."""
    source = tmp_path / "Mailbox"
    source.mkdir()
    (source / "00_definitions.v").write_text("package Definitions; parameter N=3; endpackage\nmodule Unrelated(input x); endmodule\n")
    (source / "Mailbox.sv").write_text("module Mailbox(request,response); parameter SIZE=Definitions::N; input[SIZE-1:0] request; output[SIZE-1:0] response; assign response=request; endmodule\n")
    result = inspect_interface(str(tmp_path), "proof", "Mailbox")
    assert result["source_files"] == ["Mailbox/00_definitions.v", "Mailbox/Mailbox.sv"]
    assert [row["width"] for row in result["ports"]] == [3, 3]


@pytest.mark.parametrize("source,overrides,match", [
    ("module RouteSelector #(parameter type WORD=logic)(input WORD a,output y); assign y=a; endmodule", {}, "type parameter"),
    ("module RouteSelector #(parameter TEXT=\"word\")(input a,output y); assign y=a; endmodule", {}, "non-scalar"),
    ("module RouteSelector #(parameter N=4)(input[N-1:0] a,output y); assign y=a[0]; endmodule", {"N": "1; $finish;"}, "integer"),
    ("`include \"external.svh\"\nmodule RouteSelector(input a,output y);assign y=a;endmodule", {}, "missing local include"),
    ("module RouteSelector(input[1:0][3:0] a,output y);assign y=a[0][0];endmodule", {}, "unsupported array"),
    ("module RouteSelector #(parameter N=missing)(input[N-1:0] a,output y);assign y=a[0];endmodule", {}, "elaboration failed"),
])
def test_unsupported_contexts_fail_explicitly(tmp_path, source, overrides, match):
    """Unsupported values and contexts are never guessed into generated declarations."""
    name = design(tmp_path, source)
    with pytest.raises(ValueError, match=match):
        inspect_interface(str(tmp_path), "proof", name, overrides)
    assert not (tmp_path / "proof").exists()


def test_parser_missing_is_operator_action_not_parameter_guess(tmp_path, monkeypatch):
    """Missing parser support is a tool environment issue, not a DUT repair task."""
    real_import = builtins.__import__
    def missing(name, *args, **kwargs):
        """Hide only the parser dependency for this focused failure boundary."""
        if name == "pyslang":
            raise ImportError("pyslang absent")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ValueError, match="operator.*declared dependencies"):
        inspect_interface(str(tmp_path), "proof", "RouteSelector")


def write_records(tmp_path, name, parameters=None):
    """Declare a clockless generic forwarding property without repeating RTL defaults."""
    output = tmp_path / "proof"
    output.mkdir()
    record = {"dut": name, "basic_info": {"clock_reset": {"clock_count": 0, "clock_signal": "", "reset_signal": ""}},
              "spec": {"parameters": parameters or {}, "function_groups": [{"id": "FG-ROUTE", "functions": [{"id": "FC-ROUTE", "check_points": [
                  {"id": "CK-ROUTE", "style": "Comb", "description": "Output follows input", "sva_body": "response == request;"}]}]}]},
              "extra_config": {"tcl": {"timeout": 100000, "extra_commands": []}}}
    (output / ".formal_records.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    return output


def test_render_uses_effective_parameters_without_rewriting_author_inputs(tmp_path):
    """Zero overrides reach the DUT while dependent defaults remain genuinely dependent."""
    name = design(tmp_path, "module RouteSelector #(parameter LANES=4, WIDTH=LANES*2, MODE=1)(input[WIDTH-1:0] request,output[WIDTH-1:0] response);assign response=request;endmodule")
    output = write_records(tmp_path, name, {"LANES": 6, "MODE": 0})
    original = (output / ".formal_records.yaml").read_bytes()
    render_environment(str(tmp_path), "proof", name)
    checker = (output / "tests" / f"{name}_checker.sv").read_text()
    wrapper = (output / "tests" / f"{name}_wrapper.sv").read_text()
    assert "input logic [11:0] request" in checker
    assert "parameter WIDTH = 32'shc" in checker
    dut_instantiation = wrapper.split("u_dut", 1)[0].split("RouteSelector", 2)[-1]
    assert ".LANES(32'sh6)" in dut_instantiation
    assert ".MODE(32'sh0)" in dut_instantiation
    assert ".WIDTH(" not in dut_instantiation
    assert (output / ".formal_records.yaml").read_bytes() == original
    first = {path.name: path.read_bytes() for path in (output / "tests").iterdir()}
    render_environment(str(tmp_path), "proof", name)
    assert first == {path.name: path.read_bytes() for path in (output / "tests").iterdir()}


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Enable the licensed parameterized interface smoke test")
@pytest.mark.parametrize("overrides", [{}, {"LANES": 6, "MODE": 0}])
def test_real_formalmc_default_and_derived_override(tmp_path, overrides):
    """Real FormalMC accepts generated concrete ports and the unchanged intended proof."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    name = design(tmp_path, "module RouteSelector #(parameter LANES=4, WIDTH=LANES*2, MODE=1)(input[WIDTH-1:0] request,output[WIDTH-1:0] response);assign response=request;endmodule")
    output = write_records(tmp_path, name, overrides)
    render_environment(str(tmp_path), "proof", name)
    cfg = Config({"runtime_options": {"formal_execution": {"first_pass_budget_s": 1, "analysis_threshold_s": 2, "setup_timeout_s": 15}}})
    execution = FormalExecution(str(tmp_path), "proof", name, cfg)
    try:
        execution.run()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = execution.status(wait_s=1)
            if result["status"] not in ACTIVE_RUNS:
                break
        assert result["status"] == "COMPLETED", result
        assert result["counts"] == {"TRIVIALLY_TRUE": 1} or result["counts"] == {"PROVEN": 1}
        assert execution.check()[0] is True
    finally:
        execution.cancel()
