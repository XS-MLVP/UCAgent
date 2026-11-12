"""Ordered manifests and local preprocessing share the parser and solver context."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from formal.interface import compile_context, inspect_interface
from formal.tools import render_environment


def project(tmp_path):
    """Create a generic guarded macro header whose lexical order is deliberately wrong."""
    source = tmp_path / "RoutePort"
    source.mkdir()
    (source / "z_defs.v").write_text("`ifndef ROUTE_DEFS\n`define ROUTE_DEFS\n`define ROUTE_WIDTH 11\n`define HAS_READY\n`endif\n")
    (source / "a_top.v").write_text("module RoutePort(input [`ROUTE_WIDTH-1:0] payload,\n`ifdef HAS_READY\noutput ready,\n`endif\noutput [`ROUTE_WIDTH-1:0] observed); assign observed=payload; assign ready=1'b1; endmodule\n")
    (source / "filelist.txt").write_text("# ordered compilation unit\nz_defs.v\na_top.v\n")
    return source


def test_filelist_preserves_macro_order_and_guarded_ports(tmp_path):
    """One preprocessing unit retains definitions across explicitly ordered files."""
    project(tmp_path)
    interface = inspect_interface(str(tmp_path), "proof", "RoutePort")
    assert interface["source_files"] == ["RoutePort/z_defs.v", "RoutePort/a_top.v"]
    assert [(row["name"], row["width"]) for row in interface["ports"]] == [("payload", 11), ("ready", 1), ("observed", 11)]
    assert interface["source_manifest"] == "RoutePort/filelist.txt"


def test_literal_local_include_dependencies_are_confined_and_reported(tmp_path):
    """Included headers have explicit dependencies and the parser sees actual macros."""
    source = project(tmp_path)
    (source / "filelist.txt").write_text("a_top.v\n")
    top = source / "a_top.v"
    top.write_text('`include "z_defs.v"\n' + top.read_text())
    interface = inspect_interface(str(tmp_path), "proof", "RoutePort")
    assert "RoutePort/z_defs.v" in interface["dependency_files"]
    assert interface["ports"][0]["width"] == 11
    (source / "z_defs.v").write_text("`define ROUTE_WIDTH 7\n`define HAS_READY\n")
    assert inspect_interface(str(tmp_path), "proof", "RoutePort")["ports"][0]["width"] == 7
    top.write_text('`include "../outside.v"\nmodule RoutePort(input a);endmodule\n')
    (tmp_path / "outside.v").write_text("`define OUTSIDE 1\n")
    with pytest.raises(ValueError, match="relative path|DUT|outside"):
        compile_context(str(tmp_path), "RoutePort")


@pytest.mark.parametrize("manifest", ["/tmp/input.v\n", "../outside.v\n", "-f nested.txt\n", "+define+SIZE=3\n", "z_defs.v\nz_defs.v\n", "missing.v\n"])
def test_manifest_rejects_unsafe_or_unsupported_entries(tmp_path, manifest):
    """A source manifest cannot silently become an arbitrary build command."""
    source = project(tmp_path)
    (source / "filelist.txt").write_text(manifest)
    with pytest.raises(ValueError):
        compile_context(str(tmp_path), "RoutePort")


def test_symlink_source_is_rejected(tmp_path):
    """Explicitly listed files still obey source-tree confinement."""
    source = project(tmp_path)
    outside = tmp_path / "external.v"
    outside.write_text("module External;endmodule\n")
    (source / "linked.v").symlink_to(outside)
    (source / "filelist.txt").write_text("linked.v\n")
    with pytest.raises(ValueError, match="symlink"):
        compile_context(str(tmp_path), "RoutePort")


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Enable licensed tool preflight explicitly")
def test_generated_solver_uses_same_manifest_and_local_include_context(tmp_path):
    """Real FormalMC elaboration confirms the parser's conditional interface."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    source = project(tmp_path)
    (source / "filelist.txt").write_text("a_top.v\n")
    top = source / "a_top.v"
    top.write_text('`include "z_defs.v"\n' + top.read_text())
    output = tmp_path / "proof"
    output.mkdir()
    records = {"dut": "RoutePort", "basic_info": {"clock_reset": {"clock_count": 0, "clock_signal": "", "reset_signal": ""}},
        "spec": {"parameters": {}, "function_groups": [{"id": "FG-ROUTE", "functions": [{"id": "FC-ROUTE", "check_points": [{"id": "CK-WIDTH", "style": "Comb", "description": "Resolved port width", "sva_body": "$bits(observed) == 11;"}]}]}]},
        "extra_config": {"tcl": {"timeout": 2, "extra_commands": []}}}
    (output / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    render_environment(str(tmp_path), "proof", "RoutePort")
    script = output / "tests/RoutePort_formal.tcl"
    text = script.read_text()
    assert "-incdir $INCLUDE_DIRS" in text
    assert "../../RoutePort/a_top.v" in text
    assert "glob -nocomplain" not in text[:text.index("# Clock and Reset")]
    result = subprocess.run(["FormalMC", "-f", str(script), "-override", "-work_dir", str(output / "solver")], cwd=script.parent, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TRIVIALLY_TRUE" in result.stdout + result.stderr or " is TRUE" in result.stdout + result.stderr
