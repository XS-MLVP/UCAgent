"""USDB registration, dependency isolation, fake CLI and live UVS tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ucagent.util.waveform_formats.read_usdb import UsdbReader
from ucagent.util.waveform_formats import open_waveform_reader, WaveformBackendArgumentError


def test_usdb_dispatch_without_wavekit():
    """USDB factory resolution must work even when wavekit imports are blocked."""
    script = """
import sys
sys.modules['wavekit'] = None
from ucagent.util.waveform_formats import open_waveform_reader
from ucagent.util.waveform_formats.read_usdb import UsdbReader
with open_waveform_reader('capture.USDB') as reader:
    assert isinstance(reader, UsdbReader)
    assert reader.path == 'capture.USDB'
    assert reader.backend_name == 'uvd'
    assert reader.configure_backend({}) == {}
assert sys.modules['wavekit'] is None
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1], check=True,
    )


def test_stateless_context_propagates_errors():
    """The context holds no session and never suppresses query failures."""
    reader = UsdbReader("capture.usdb")
    with reader as entered:
        assert entered is reader
    with pytest.raises(RuntimeError, match="query failed"):
        with reader:
            raise RuntimeError("query failed")


def test_missing_file_does_not_invent_data(tmp_path):
    """A missing file must fail explicitly rather than return empty metadata."""
    from ucagent.util.waveform_formats.read_usdb import UsdbRuntimeError

    reader = UsdbReader(tmp_path / "absent.usdb")
    for attribute in ("begin_time", "end_time", "top_scopes"):
        with pytest.raises(UsdbRuntimeError, match="does not exist"):
            getattr(reader, attribute)
    with pytest.raises(UsdbRuntimeError, match="does not exist"):
        reader.get_matched_signals("**")


def test_backend_configuration():
    """USDB supports defaults/help and rejects unsupported advanced options."""
    reader = UsdbReader("capture.usdb")
    assert reader.configure_backend({}) == {}
    assert reader.configure_backend("help") == {"options": {}}
    for options in ({"unknown": True}, [], None):
        with pytest.raises(WaveformBackendArgumentError):
            reader.configure_backend(options)


def test_waveinfo_usdb_uses_standard_error_and_help_paths(tmp_path, monkeypatch):
    """USDB read failures and help use the standard WaveInfo handling."""
    pytest.importorskip("mcp.server.mcpserver", reason="mcp runtime mismatch in this environment")
    from ucagent.tools import WaveInfo
    from ucagent.util.waveform_formats import read_usdb

    def unavailable(name):
        """Simulate an unavailable operator tool without probing the host."""
        raise read_usdb.UsdbRuntimeError("CLI unavailable")

    monkeypatch.setattr(read_usdb, "_find_tool", unavailable)

    test_dir = tmp_path / "tests"
    session = test_dir / "data" / "toffee_tmp_20261101120000_001" / "master"
    session.mkdir(parents=True)
    (session / "test_demo.usdb").write_bytes(b"USDB fixture")
    tool = WaveInfo(workspace=str(tmp_path), test_dir=str(test_dir))
    result = tool.analyze(test_case_name="test_demo")
    assert tool.format_priority == ["fst", "vcd", "fsdb", "usdb"]
    assert result["success"] is False
    assert result["status"] == "waveform_parse_error"
    assert result["suggestions"]
    assert "NotImplementedError" not in str(result)
    help_result = tool.analyze(test_case_name="test_demo", backend_args="help")
    assert help_result["status"] == "advanced_help"
    assert help_result["evidence_usable"] is False


@pytest.fixture
def cli_reader(tmp_path, monkeypatch):
    """Emulate the documented CLI reports while exercising real reader parsing."""
    from ucagent.util.waveform_formats import read_usdb as module

    path = tmp_path / "capture with spaces.usdb"
    path.touch()
    calls = []
    outputs = {"values": "Signal: TOP.data\nTime: 0 Value: 0000\nTime: 10 Value: 0011\nTime: 20 Value: xz01\nTime: 20 Value: zx01\nTime: 30 Value: 1111\n"}

    def run(command, *, check=True, cwd=None):
        """Produce metadata, a dap report, or the current digital trace fixture."""
        calls.append(command)
        if "--info" in command:
            return 0, "start time: 0\nend time: 40\n"
        if "--hier" in command:
            return 0, "Var: TOP.data P:[3:0] Bits:4\nVar: TOP.clk Bits:1\n"
        if "getUsdbHier" in command:
            (Path(cwd) / "getUsdbHier.log").write_text("# scopes\nTOP\nTOP.dut\nsignal: TOP.clk\n")
            return 0, ""
        assert Path(command[command.index("--sg") + 1]).read_text().strip() == "TOP.data"
        return 0, outputs["values"]

    monkeypatch.setattr(module, "_find_tool", lambda name: name)
    monkeypatch.setattr(module, "_run_tool", run)
    return UsdbReader(path), calls, outputs


def test_metadata_cache_and_signal_queries(cli_reader):
    """Metadata loads once and exact/glob/regex/brace queries share sorted paging."""
    reader, calls, _ = cli_reader
    assert calls == []
    assert (reader.begin_time, reader.end_time) == (0, 40)
    assert [scope.full_name for scope in reader.top_scopes] == ["TOP"]
    for query in ("TOP.*", "**", "TOP.{clk,data}", "TOP./clk|data/"):
        page = reader.get_matched_signals(query, offset=1, limit=1)
        assert page["total"] == 2
        assert list(page["signals"]) == ["TOP.data[3:0]"]
    assert reader.get_matched_signals("TOP.data")["total"] == 1
    assert reader.get_matched_signals("**", offset=10)["total"] == 2
    assert reader.get_matched_signals("**", offset=10)["signals"] == {}
    assert len(calls) == 3
    for kwargs in ({"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": 1001}):
        with pytest.raises(ValueError):
            reader.get_matched_signals("**", **kwargs)
    with pytest.raises(ValueError):
        reader.get_matched_signals("TOP.{")


def test_value_window_masks_and_duplicates(cli_reader):
    """Keep the predecessor timestamp, exclusive end and identical mapped timelines."""
    reader, calls, _ = cli_reader
    signal = reader.get_matched_signals("TOP.data")["signals"]["TOP.data[3:0]"]
    mappings = (
        {"0": 0, "1": 1, "x": 0, "z": 0},
        {"0": 0, "1": 0, "x": 1, "z": 0},
        {"0": 0, "1": 0, "x": 0, "z": 1},
    )
    expected = ([(10, 3), (20, 1)], [(10, 0), (20, 4)], [(10, 0), (20, 8)])
    for mapping, rows in zip(mappings, expected):
        assert reader.load_value_changes(signal, mapping, 15, 30) == {"mapped": rows}
        assert calls[-1][-2:] == ["--end", "29"]
        assert calls[-1][calls[-1].index("--begin") + 1] == "15"
    assert reader.load_value_changes(signal, mappings[0], 20, 30)["mapped"] == [(20, 1)]
    assert reader.load_value_changes(signal, mappings[0], 35)["mapped"] == [(30, 15)]
    assert reader.load_value_changes(signal, mappings[0], end_time=0) == {"mapped": []}
    assert len(reader.load_value_changes(signal, mappings[0])["mapped"]) == 4
    for bounds in ((-1, None), (True, None), (0, 0), (20, 10), (None, 1.5)):
        with pytest.raises(ValueError):
            reader.load_value_changes(signal, mappings[0], *bounds)
    with pytest.raises(ValueError, match="value_mapping"):
        reader.load_value_changes(signal, {"0": 0})


@pytest.mark.parametrize("output", [
    "", "Signal: OTHER\n", "Signal: TOP.data\nTime: 0 Value: q\n",
    "Signal: TOP.data\nTime: 0 Value: 1\n",
    "Signal: TOP.data\nTime: 10 Value: 0000\nTime: 0 Value: 0000\n",
])
def test_invalid_value_reports_raise(cli_reader, output):
    """Missing blocks, malformed states, widths and timestamps cannot imply no data."""
    from ucagent.util.waveform_formats.read_usdb import UsdbRuntimeError

    reader, _, outputs = cli_reader
    signal = reader.get_matched_signals("TOP.data")["signals"]["TOP.data[3:0]"]
    outputs["values"] = output
    with pytest.raises(UsdbRuntimeError):
        reader.load_value_changes(signal, {"0": 0, "1": 1, "x": 0, "z": 0})
    outputs["values"] = "Signal: TOP.data\n"
    assert reader.load_value_changes(signal, {"0": 0, "1": 1, "x": 0, "z": 0}) == {"mapped": []}


def test_hierarchy_arrays_and_escaped_names():
    """Preserve spaces, negative bounds, multidimensional arrays and packed widths."""
    from ucagent.util.waveform_formats.read_usdb import _parse_hier, UsdbRuntimeError

    signals = _parse_hier(
        "Var: TOP.mem U:[0:1][-1:0] P:[7:0] Bits:8\n"
        "Var: TOP.escaped name P:[3:0] Bits:4\n"
        "Var: TOP.matrix P:[1:0][3:0] Bits:8\n"
    )
    assert list(signals)[:4] == ["TOP.mem[0][-1]", "TOP.mem[0][0]", "TOP.mem[1][-1]", "TOP.mem[1][0]"]
    assert signals["TOP.escaped name[3:0]"].native_name == "TOP.escaped name"
    assert signals["TOP.mem[0][-1]"].native_name == "TOP.mem[0][-1]"
    assert signals["TOP.matrix"].width == 8
    for row in ("Var: TOP.a", "Var: TOP.a Bits:0", "Var: TOP.a P:[1:0] P:[3:0] Bits:8",
                "Var: TOP.a U:[0:100000] Bits:1", "Var: TOP.a Bits:1\nVar: TOP.a Bits:1"):
        with pytest.raises(UsdbRuntimeError):
            _parse_hier(row)


def test_wide_values_and_foreign_descriptors(cli_reader):
    """Use Python integer precision and reject descriptors not issued by this reader."""
    from ucagent.util.waveform_formats import read_usdb as module

    reader, _, outputs = cli_reader
    reader.begin_time
    signal = module.UsdbSignal("TOP.data[79:0]", "data", 80)
    reader._metadata.signals.clear()
    reader._metadata.signals[signal.full_name] = signal
    outputs["values"] = "Signal: TOP.data\nTime: 9007199254740993 Value: " + "1" * 80 + "\n"
    mapping = {"0": 0, "1": 1, "x": 0, "z": 0}
    assert reader.load_value_changes(signal, mapping)["mapped"] == [(9007199254740993, (1 << 80) - 1)]
    with pytest.raises(module.UsdbRuntimeError, match="not from this reader"):
        reader.load_value_changes(module.UsdbSignal(signal.full_name, "data", 80), mapping)


def test_tool_resolution_and_environment(tmp_path, monkeypatch):
    """Search only configured homes, cache probes and preserve the operator environment."""
    from ucagent.util.waveform_formats import read_usdb as module
    from types import SimpleNamespace

    broken = tmp_path / "broken" / "bin" / "usdbaccess"
    working = tmp_path / "working" / "bin" / "usdbaccess"
    for path in (broken, working):
        path.parent.mkdir(parents=True)
        path.touch()
    monkeypatch.setattr(module, "_RESOLVED_TOOLS", {})
    monkeypatch.setenv("UVD_HOME", str(broken.parent.parent))
    monkeypatch.setenv("UVS_HOME", str(working.parent.parent))
    monkeypatch.setattr(module.os, "access", lambda *args: True)
    calls = []

    def run(command, **kwargs):
        """Emulate a missing wrapper target and a working alternate installation."""
        calls.append(command)
        assert "env" not in kwargs
        assert os.environ["UVD_HOME"] == str(broken.parent.parent)
        return SimpleNamespace(returncode=127 if command[0] == str(broken) else 0, stderr="", stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._find_tool("usdbaccess") == str(working)
    assert module._find_tool("usdbaccess") == str(working)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [OSError("unavailable"), subprocess.TimeoutExpired("tool", 120)])
def test_cli_execution_failures(monkeypatch, failure):
    """Normalize launch and timeout failures into explicit adapter errors."""
    from ucagent.util.waveform_formats import read_usdb as module

    def run(*args, **kwargs):
        """Raise the requested subprocess failure."""
        raise failure

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.UsdbRuntimeError):
        module._run_tool(["usdbaccess", "--info"])
    assert module._tool_works("usdbaccess") is False


def test_invalid_metadata_and_missing_scope_report(cli_reader, monkeypatch):
    """Invalid times and absent dap reports must leave the cache unpublished."""
    from ucagent.util.waveform_formats import read_usdb as module

    for output in ("", "start time: -1\nend time: 10", "start time: 10\nend time: 1"):
        with pytest.raises(module.UsdbRuntimeError):
            module._parse_info(output)
    reader, _, _ = cli_reader
    original = module._run_tool

    def run(command, **kwargs):
        """Suppress the dap report to simulate a successful but incomplete command."""
        return (0, "") if "getUsdbHier" in command else original(command, **kwargs)

    monkeypatch.setattr(module, "_run_tool", run)
    with pytest.raises(module.UsdbRuntimeError, match="scope report missing"):
        reader.begin_time
    assert reader._metadata is None


def test_real_subprocess_execution_and_exit_status():
    """Exercise shell-free execution and nonzero status handling with real processes."""
    from ucagent.util.waveform_formats import read_usdb as module

    code, output = module._run_tool([sys.executable, "-c", "print('report')"])
    assert code == 0 and output.strip() == "report"
    command = [sys.executable, "-c", "import sys; print('query rejected', file=sys.stderr); sys.exit(2)"]
    with pytest.raises(module.UsdbRuntimeError, match="query rejected"):
        module._run_tool(command)
    code, output = module._run_tool(command, check=False)
    assert code == 2 and "query rejected" in output


_TEST_SOURCES = {
    "tb_xz.sv": """
module dut(input clk, input rst_n, input [3:0] in1, output reg [3:0] out1, output reg [3:0] outz);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin out1 <= 4'b0000; outz <= 4'bzzzz; end
    else begin out1 <= in1; outz <= {in1[3], 1'bz, in1[1:0]}; end
  end
endmodule
module tb;
  reg clk = 0, rst_n = 0;
  reg [3:0] in1 = 4'bx001;
  wire [3:0] out1, outz;
  dut d(.clk(clk), .rst_n(rst_n), .in1(in1), .out1(out1), .outz(outz));
  always #5 clk = ~clk;
  initial begin
    #12 rst_n = 1;
    #8 in1 = 4'b0010;
    #10 in1 = 4'b0110;
    #10 in1 = 4'b1z10;
    #20 $finish;
  end
endmodule
""",
    "tb_mem.sv": """
module tb;
  reg clk = 0;
  reg [7:0] mem [0:3];
  logic [15:0] wide;
  initial begin
    mem[0] = 8'hA5; mem[2] = 8'h3C;
    wide = 16'hx0F0;
    #10 wide = 16'h1234;
    #10 mem[1] = 8'hFF;
    #10 $finish;
  end
  always #5 clk = ~clk;
endmodule
""",
    "tb_multidim.sv": """
module tb;
  reg clk = 0;
  reg [7:0] mem2 [0:1][0:3];
  reg [3:0][7:0] pk;
  initial begin
    mem2[0][0] = 8'hA0; mem2[0][3] = 8'hA3; mem2[1][2] = 8'hB2;
    pk = 32'h12345678;
    #10 mem2[1][2] = 8'hFF; pk[1] = 8'hBB;
    #10 $finish;
  end
  always #5 clk = ~clk;
endmodule
""",
}


def _build_usdb(tmp_path: Path, source_name: str) -> Path:
    """Compile and simulate a fixture in a temporary directory, skipping absent UVS."""
    home = os.environ.get("UVS_HOME")
    if not home:
        pytest.skip("UVS_HOME is not configured for USDB fixtures")
    uvs = Path(home).resolve() / "bin" / "uvs"
    if not uvs.is_file() or not os.access(uvs, os.X_OK):
        pytest.skip("no uvs executable under UVS_HOME/bin for USDB fixtures")
    (tmp_path / source_name).write_text(_TEST_SOURCES[source_name], encoding="utf-8")
    env = dict(os.environ)
    compile_result = subprocess.run(
        [str(uvs), "-sv", source_name, "-top", "tb", "-usdbon"], cwd=tmp_path,
        capture_output=True, text=True, timeout=300, env=env,
    )
    assert compile_result.returncode == 0, (
        f"uvs compile failed: {compile_result.stdout[-500:]}\n{compile_result.stderr[-500:]}"
    )
    sim_result = subprocess.run(
        [str(tmp_path / "uvsim"), "-usdb", "all"], cwd=tmp_path,
        capture_output=True, text=True, timeout=300, env=env,
    )
    assert sim_result.returncode == 0, (
        f"uvsim failed: {sim_result.stdout[-500:]}\n{sim_result.stderr[-500:]}"
    )
    usdb = tmp_path / "vista.usdb"
    assert usdb.is_file(), "uvsim did not produce vista.usdb"
    return usdb


def _load_xz_reader(usdb: Path) -> UsdbReader:
    """Open the X/Z fixture and assert its fixed top-level metadata."""
    reader = UsdbReader(usdb)
    assert reader.begin_time == 0
    assert reader.end_time == 60
    assert [scope.full_name for scope in reader.top_scopes] == ["tb"]
    return reader


def test_paginated_query_bounds_are_enforced():
    """Validate page offsets and limits before touching files or tools."""
    reader = UsdbReader("capture.usdb")
    for kwargs in ({"offset": -1}, {"limit": 0}, {"limit": 1001}):
        with pytest.raises(ValueError):
            reader.get_matched_signals("TOP.**", **kwargs)


def test_parse_info_time_bounds():
    """Extract start/end ticks from the report including its time scale field."""
    from ucagent.util.waveform_formats.read_usdb import _parse_info, UsdbRuntimeError

    assert _parse_info("start time: 0\nend time: 60\ntime scale: 1ns\n") == (0, 60)
    for report in ("no time fields here", "start time: 5\nend time: 2\n"):
        with pytest.raises(UsdbRuntimeError):
            _parse_info(report)


def test_parse_hier_declares_ranges_and_elements():
    """Keep packed ranges and expand unpacked elements from complete CLI Var rows."""
    from ucagent.util.waveform_formats.read_usdb import _parse_hier, UsdbRuntimeError

    signals = _parse_hier("\n".join([
        "banner lines",
        "Var:tb.clk Bits:1 Idcode:3 Type:Reg",
        "Var:tb.wide P:[15:0] Bits:16 Idcode:6 Type:Reg",
        "Var:tb.mem U:[0:3] P:[7:0] Bits:8 Idcode:0 Type:Reg",
        r"Var:top.\weird [1].name with spaces Bits:1 Idcode:9 Type:Wire",
    ]))
    assert set(signals) == {
        "tb.clk", "tb.wide[15:0]", "tb.mem[0]", "tb.mem[1]", "tb.mem[2]", "tb.mem[3]",
        r"top.\weird [1].name with spaces",
    }
    assert (signals["tb.wide[15:0]"].width, signals["tb.wide[15:0]"].base_name) == (16, "wide")
    assert (signals["tb.mem[2]"].width, signals["tb.mem[2]"].base_name) == (8, "mem")
    assert signals["tb.clk"].native_name == "tb.clk"
    assert signals["tb.wide[15:0]"].native_name == "tb.wide"
    with pytest.raises(UsdbRuntimeError):
        _parse_hier("Var:tb.x Idcode:1 Type:Wire")


def test_parse_hier_multidimensional_declarations():
    """Expand merged unpacked dimensions while retaining bare multi-packed names."""
    from ucagent.util.waveform_formats.read_usdb import _parse_hier, UsdbRuntimeError

    signals = _parse_hier("\n".join([
        "Var:tb.mem2 U:[0:1][0:3] P:[7:0] Bits:8 Idcode:0 Type:Reg",
        "Var:tb.pk P:[3:0][7:0] Bits:32 Idcode:10 Type:Reg",
    ]))
    assert list(signals) == [f"tb.mem2[{i}][{j}]" for i in range(2) for j in range(4)] + ["tb.pk"]
    assert signals["tb.mem2[1][2]"].width == 8
    assert signals["tb.mem2[1][2]"].base_name == "mem2"
    assert signals["tb.mem2[1][2]"].native_name == "tb.mem2[1][2]"
    assert signals["tb.pk"].width == 32
    assert signals["tb.pk"].native_name == "tb.pk"
    with pytest.raises(UsdbRuntimeError):
        _parse_hier("Var:tb.big U:[0:1000000] Bits:1 Idcode:0 Type:Reg")


def test_parse_scopes_keeps_top_level_only():
    """Drop nested instances and signal rows while retaining genuine roots."""
    from ucagent.util.waveform_formats.read_usdb import _parse_scopes

    output = "\n".join(["# header", "tb", "signal: tb.clk", "tb.d", "signal: tb.d.clk"])
    assert [scope.full_name for scope in _parse_scopes(output)] == ["tb"]
    assert _parse_scopes("# only comments\n") == []


def test_parse_value_blocks_collapses_same_tick():
    """Key blocks by signal name and keep only the final state at each tick."""
    from ucagent.util.waveform_formats.read_usdb import _parse_value_blocks

    blocks = _parse_value_blocks("\n".join([
        "noise header", "Signal: tb.a", "Time: 0             Value: 0x",
        "Time: 10             Value: 11", "Time: 10             Value: 10",
        "Signal: tb.b", "Time: 5             Value: z",
    ]))
    assert blocks == {"tb.a": [(0, "0x"), (10, "10")], "tb.b": [(5, "z")]}


def test_declared_name_expansion_forms():
    """Exercise scalar, packed and separate unpacked tokens through hierarchy parsing."""
    from ucagent.util.waveform_formats.read_usdb import _parse_hier

    for row, names in (
        ("tb.mem U:[0:2] P:[7:0]", ["tb.mem[0]", "tb.mem[1]", "tb.mem[2]"]),
        ("tb.wide P:[15:0]", ["tb.wide[15:0]"]),
        ("tb.clk", ["tb.clk"]),
        ("tb.m U:[0:1] U:[0:1] P:[7:0]", ["tb.m[0][0]", "tb.m[0][1]", "tb.m[1][0]", "tb.m[1][1]"]),
        ("tb.pk P:[3:0][7:0]", ["tb.pk"]),
    ):
        assert list(_parse_hier(f"Var:{row} Bits:32")) == names


def test_map_state_msb_first_and_wide(cli_reader):
    """Exercise MSB-first mapping and invalid states through the public value load."""
    from ucagent.util.waveform_formats.read_usdb import UsdbRuntimeError

    reader, _, outputs = cli_reader
    signal = reader.get_matched_signals("TOP.data")["signals"]["TOP.data[3:0]"]
    mapping = {"0": 0, "1": 1, "x": 0, "z": 1}
    outputs["values"] = "Signal: TOP.data\nTime: 0 Value: xz01\n"
    assert reader.load_value_changes(signal, mapping)["mapped"] == [(0, 0b0101)]
    for state in ("01", "0a10"):
        outputs["values"] = f"Signal: TOP.data\nTime: 0 Value: {state}\n"
        with pytest.raises(UsdbRuntimeError):
            reader.load_value_changes(signal, mapping)
    # Wide integer conversion is also covered by test_wide_values_and_foreign_descriptors.


def test_find_tool_requires_working_installation(monkeypatch):
    """Report the requested tool and searched locations when no installation works."""
    from ucagent.util.waveform_formats import read_usdb as module

    monkeypatch.delenv("UVD_HOME", raising=False)
    monkeypatch.delenv("UVS_HOME", raising=False)
    monkeypatch.setattr(module, "_RESOLVED_TOOLS", {})
    monkeypatch.setattr(module.os.path, "isfile", lambda path: False)
    with pytest.raises(module.UsdbRuntimeError, match="uvd_missing_tool_xyz") as error:
        module._find_tool("uvd_missing_tool_xyz")
    assert "Searched:" in str(error.value)


def test_live_xz_metadata_and_queries(tmp_path):
    """Match real USDB metadata, scopes and signal paging to the X/Z fixture."""
    reader = _load_xz_reader(_build_usdb(tmp_path, "tb_xz.sv"))
    matches = reader.get_matched_signals("tb.**")
    assert matches["total"] == 10
    assert matches["offset"] == 0 and matches["limit"] == 100
    outz = reader.get_matched_signals("tb.outz")["signals"]["tb.outz[3:0]"]
    assert (outz.full_name, outz.base_name, outz.width) == ("tb.outz[3:0]", "outz", 4)
    page = reader.get_matched_signals("tb.**", offset=8, limit=4)
    assert list(page["signals"]) == ["tb.outz[3:0]", "tb.rst_n"]
    assert page["total"] == 10
    empty = reader.get_matched_signals("tb.**", offset=100, limit=10)
    assert empty["signals"] == {} and empty["total"] == 10
    regex_page = reader.get_matched_signals("tb.d./[io][a-z]+/")
    assert list(regex_page["signals"]) == ["tb.d.outz[3:0]"]
    with pytest.raises(ValueError):
        reader.get_matched_signals("/unclosed")


def test_live_xz_value_changes_and_mapping(tmp_path):
    """Retain the state at the begin bound and exclude the exclusive end bound."""
    from ucagent.util.waveform_formats.read_usdb import UsdbRuntimeError, UsdbSignal

    reader = _load_xz_reader(_build_usdb(tmp_path, "tb_xz.sv"))
    outz = reader.get_matched_signals("tb.outz")["signals"]["tb.outz[3:0]"]
    value_map = {"0": 0, "1": 1, "x": 0, "z": 0}
    assert reader.load_value_changes(outz, value_map)["mapped"] == [(0, 0), (15, 1), (25, 2), (45, 10)]
    assert reader.load_value_changes(outz, value_map, 15, 30)["mapped"] == [(15, 1), (25, 2)]
    assert reader.load_value_changes(outz, value_map, 3, 16)["mapped"] == [(0, 0), (15, 1)]
    assert reader.load_value_changes(outz, value_map, 50, 60)["mapped"] == [(45, 10)]
    z_mask = reader.load_value_changes(outz, {"0": 0, "1": 1, "x": 0, "z": 1}, 15, 45)
    assert z_mask["mapped"] == [(15, 5), (25, 6)]
    with pytest.raises(ValueError):
        reader.load_value_changes(outz, value_map, 30, 30)
    with pytest.raises(ValueError):
        reader.load_value_changes(outz, {"0": 0, "1": 1, "x": 0})
    with pytest.raises(UsdbRuntimeError):
        reader.load_value_changes(UsdbSignal("tb.absent", "absent", 4), value_map)


def test_live_mem_unpacked_and_wide_signals(tmp_path):
    """Round-trip unpacked array elements and wide buses through the real CLI."""
    reader = UsdbReader(_build_usdb(tmp_path, "tb_mem.sv"))
    assert sorted(reader.get_matched_signals("tb.mem*")["signals"]) == [f"tb.mem[{i}]" for i in range(4)]
    mem0 = reader.get_matched_signals("tb.mem[0]")["signals"]["tb.mem[0]"]
    assert mem0.width == 8
    mapping = {"0": 0, "1": 1, "x": 0, "z": 0}
    assert reader.load_value_changes(mem0, mapping)["mapped"] == [(0, 0b10100101)]
    wide = reader.get_matched_signals("tb.wide")["signals"]["tb.wide[15:0]"]
    assert reader.load_value_changes(wide, mapping, end_time=20)["mapped"] == [(0, 0x00F0), (10, 0x1234)]


def test_live_multidim_elements_and_packed(tmp_path):
    """Read real values for two-dimensional unpacked elements and packed buses."""
    reader = UsdbReader(_build_usdb(tmp_path, "tb_multidim.sv"))
    names = sorted(reader.get_matched_signals("tb.**")["signals"])
    assert names == ["tb.clk"] + [f"tb.mem2[{i}][{j}]" for i in range(2) for j in range(4)] + ["tb.pk"]
    mapping = {"0": 0, "1": 1, "x": 0, "z": 0}
    element = reader.get_matched_signals("tb.mem2[1][2]")["signals"]["tb.mem2[1][2]"]
    assert element.width == 8
    assert reader.load_value_changes(element, mapping, end_time=20)["mapped"] == [(0, 0xB2), (10, 0xFF)]
    untouched = reader.get_matched_signals("tb.mem2[0][1]")["signals"]["tb.mem2[0][1]"]
    assert reader.load_value_changes(untouched, mapping, end_time=20)["mapped"] == [(0, 0)]
    packed = reader.get_matched_signals("tb.pk")["signals"]["tb.pk"]
    assert packed.width == 32
    assert reader.load_value_changes(packed, mapping, end_time=20)["mapped"] == [(0, 0x12345678), (10, 0x1234BB78)]


def test_live_window_bounds_validation(tmp_path):
    """Reject noninteger or negative windows for a descriptor from a real database."""
    reader = UsdbReader(_build_usdb(tmp_path, "tb_multidim.sv"))
    signal = reader.get_matched_signals("tb.pk")["signals"]["tb.pk"]
    value_map = {"0": 0, "1": 1, "x": 0, "z": 0}
    for begin, end in ((None, -1), ("5", 10), (5.0, 10), (0, 0), (-1, 10)):
        with pytest.raises(ValueError):
            reader.load_value_changes(signal, value_map, begin, end)


@pytest.mark.parametrize("filename,expected", [
    ("values_begin3_end16.txt", {
        "tb.ohot.clk": [(0, "0"), (10, "1")],
        "tb.ohot.rst_n": [(0, "0"), (5, "1")],
        "tb.ohot.rd": [(0, "0"), (10, "1")],
        "tb.ohot.ds": [(0, "0")],
    }),
    ("values_begin50_end60.txt", {
        "tb.ohot.clk": [(50, "1"), (60, "0")],
        "tb.ohot.rst_n": [(5, "1")],
        "tb.ohot.rd": [(50, "0")],
        "tb.ohot.ds": [(50, "1")],
    }),
])
def test_captured_uvs_bounded_value_reports(filename, expected):
    """Parse UVS2026.06.P3 samples transcribed from the operator's screenshots."""
    from ucagent.util.waveform_formats.read_usdb import _parse_value_blocks

    report = (Path(__file__).parent / "fixtures" / "usdb" / filename).read_text(encoding="utf-8")
    assert _parse_value_blocks(report) == expected


def test_captured_unbounded_clock_excerpt():
    """Collapse the duplicate initial tick in a captured prefix, not a full trace."""
    from ucagent.util.waveform_formats.read_usdb import _parse_value_blocks

    path = Path(__file__).parent / "fixtures" / "usdb" / "clock_unbounded_excerpt.txt"
    rows = _parse_value_blocks(path.read_text(encoding="utf-8"))["tb.ohot.clk"]
    assert rows == [(tick, str((tick // 10) % 2)) for tick in range(0, 251, 10)]


@pytest.mark.parametrize("begin,end,filename,expected", [
    (3, 17, "values_begin3_end16.txt", {
        "clk": [(0, 0), (10, 1)], "rst_n": [(0, 0), (5, 1)],
        "rd": [(0, 0), (10, 1)], "ds": [(0, 0)],
    }),
    (50, 61, "values_begin50_end60.txt", {
        "clk": [(50, 1), (60, 0)], "rst_n": [(5, 1)],
        "rd": [(50, 0)], "ds": [(50, 1)],
    }),
])
def test_captured_reports_through_fake_cli(tmp_path, monkeypatch, begin, end, filename, expected):
    """Send native bounds and signal lists while retaining original predecessor ticks."""
    from ucagent.util.waveform_formats import read_usdb as module

    capture = tmp_path / "vista.usdb"
    capture.touch()
    report = (Path(__file__).parent / "fixtures" / "usdb" / filename).read_text(encoding="utf-8")
    calls = []

    def run(command, *, check=True, cwd=None):
        """Use captured value reports and synthetic metadata for the four shown signals."""
        calls.append(command)
        if "--info" in command:
            return 0, "start time: 0\nend time: 250\n"
        if "--hier" in command:
            return 0, "\n".join(f"Var:tb.ohot.{name} Bits:1" for name in expected)
        if "getUsdbHier" in command:
            (Path(cwd) / "getUsdbHier.log").write_text("tb\ntb.ohot\n", encoding="utf-8")
            return 0, ""
        assert command[-4:] == ["--begin", str(begin), "--end", str(end - 1)]
        listing = Path(command[command.index("--sg") + 1]).read_text(encoding="utf-8")
        assert listing in {f"tb.ohot.{name}\n" for name in expected}
        return 0, report

    monkeypatch.setattr(module, "_find_tool", lambda name: name)
    monkeypatch.setattr(module, "_run_tool", run)
    with open_waveform_reader(str(capture)) as reader:
        for name, rows in expected.items():
            full_name = f"tb.ohot.{name}"
            signal = reader.get_matched_signals(full_name)["signals"][full_name]
            assert reader.load_value_changes(signal, {"0": 0, "1": 1, "x": 0, "z": 0}, begin, end) == {"mapped": rows}
    assert len(calls) == 7


def test_captured_metadata_reports():
    """Parse captured time bounds, digital types, array bounds and genuine scope roots."""
    from ucagent.util.waveform_formats import read_usdb as module

    fixtures = Path(__file__).parent / "fixtures" / "usdb"
    assert module._parse_info((fixtures / "info_excerpt.txt").read_text(encoding="utf-8")) == (0, 9000170)
    signals = module._parse_hier((fixtures / "hierarchy_excerpt.txt").read_text(encoding="utf-8"))
    assert signals["tb.state_name1[87:0]"].width == 88
    assert signals["tb.state_name4"].width == 32
    assert signals["tb.FSM_Moore_1_ins.a"].width == 32
    for index in (0, 1):
        assert signals[f"tb.FSM_Moore_1_ins.aa[{index}]"].width == 32
        assert f"tb.FSM_Moore_1_ins.b[{index}]" not in signals
    for i in range(4):
        for j in range(4):
            assert signals[f"tb.FSM_Moore_1_ins.ab[{i}][{j}]"].width == 32
    scopes = module._parse_scopes((fixtures / "getUsdbHier_report.txt").read_text(encoding="utf-8"))
    assert [scope.full_name for scope in scopes] == ["tb", "tb1", "ttb"]


@pytest.mark.parametrize("returncode,emit_report", [(0, True), (0, False), (2, True)])
def test_dap_report_file_isolated_from_terminal_logs(tmp_path, monkeypatch, returncode, emit_report):
    """Read dap's default report in scratch cwd, rejecting missing reports or failed runs."""
    from ucagent.util.waveform_formats import read_usdb as module

    fixtures = Path(__file__).parent / "fixtures" / "usdb"
    monkeypatch.chdir(tmp_path)
    capture = tmp_path / "capture with spaces.usdb"
    capture.touch()
    stale_report = tmp_path / "getUsdbHier.log"
    stale_report.write_text("STALE_SCOPE\n", encoding="utf-8")
    report_dirs = []

    def run(command, **kwargs):
        """Emulate stdout progress separately from dap's report file side effect."""
        if "--info" in command:
            output = (fixtures / "info_excerpt.txt").read_text(encoding="utf-8")
        elif "--hier" in command:
            output = (fixtures / "hierarchy_excerpt.txt").read_text(encoding="utf-8")
        else:
            assert command == ["dap", "getUsdbHier", "-export_scope", "-usdb", str(capture)]
            scratch = Path(kwargs["cwd"])
            assert scratch != tmp_path
            report_dirs.append(scratch)
            if emit_report:
                (scratch / "getUsdbHier.log").write_text(
                    (fixtures / "getUsdbHier_report.txt").read_text(encoding="utf-8"), encoding="utf-8",
                )
            output = (fixtures / "dap_stdout.txt").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, returncode, stdout=output, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(module, "_find_tool", lambda name: name)
    monkeypatch.setattr(module.subprocess, "run", run)
    reader = UsdbReader(capture.name)
    if returncode == 0 and emit_report:
        assert [scope.full_name for scope in reader.top_scopes] == ["tb", "tb1", "ttb"]
        assert (reader.begin_time, reader.end_time) == (0, 9000170)
    else:
        with pytest.raises(module.UsdbRuntimeError, match="dap getUsdbHier failed"):
            reader.top_scopes
        assert reader._metadata is None
    assert report_dirs and all(not directory.exists() for directory in report_dirs)
    assert stale_report.read_text(encoding="utf-8") == "STALE_SCOPE\n"


def test_cli_working_directory(tmp_path):
    """Pass a scratch working directory to a real child without changing the parent cwd."""
    from ucagent.util.waveform_formats import read_usdb as module

    parent_cwd = Path.cwd()
    code, output = module._run_tool([sys.executable, "-c", "import os; print(os.getcwd())"], cwd=tmp_path)
    assert code == 0 and Path(output.strip()) == tmp_path
    assert Path.cwd() == parent_cwd


@pytest.mark.parametrize("home_value", [None, "", "missing-installation"])
def test_tool_lookup_never_uses_path(tmp_path, monkeypatch, home_value):
    """Missing installation homes fail even when a same-named tool is on PATH."""
    from ucagent.util.waveform_formats import read_usdb as module

    executable = tmp_path / "usdbaccess"
    executable.touch()
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("UVD_HOME", raising=False)
    if home_value is None:
        monkeypatch.delenv("UVS_HOME", raising=False)
    else:
        monkeypatch.setenv("UVS_HOME", str(tmp_path / home_value) if home_value else "")
    monkeypatch.setattr(module, "_RESOLVED_TOOLS", {})

    def probe(candidate):
        """Reject an unexpected attempt to execute a tool outside configured homes."""
        pytest.fail(f"Unexpected tool probe: {candidate}")

    monkeypatch.setattr(module, "_tool_works", probe)
    with pytest.raises(module.UsdbRuntimeError, match="Set UVS_HOME and UVD_HOME"):
        module._find_tool("usdbaccess")


def test_tool_cache_tracks_installation_environment(tmp_path, monkeypatch):
    """A changed installation home must not return a tool cached from the previous home."""
    from ucagent.util.waveform_formats import read_usdb as module

    monkeypatch.delenv("UVD_HOME", raising=False)
    monkeypatch.setattr(module, "_RESOLVED_TOOLS", {})
    monkeypatch.setattr(module.os, "access", lambda *args: True)
    probes = []

    def probe(candidate):
        """Record the selected installation's probe without launching host tools."""
        probes.append(candidate)
        return True

    monkeypatch.setattr(module, "_tool_works", probe)
    for label in ("first", "second"):
        home = tmp_path / label
        executable = home / "bin" / "usdbaccess"
        executable.parent.mkdir(parents=True)
        executable.touch()
        monkeypatch.setenv("UVS_HOME", str(home))
        assert module._find_tool("usdbaccess") == str(executable)
        assert module._find_tool("usdbaccess") == str(executable)
    assert len(probes) == 2
    monkeypatch.delenv("UVS_HOME")
    with pytest.raises(module.UsdbRuntimeError):
        module._find_tool("usdbaccess")


def test_dap_requires_explicit_uvd_home(tmp_path, monkeypatch):
    """A dap executable under UVS_HOME cannot manufacture the required UVD_HOME."""
    from ucagent.util.waveform_formats import read_usdb as module

    home = tmp_path / "uvs"
    executable = home / "bin" / "dap"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("UVS_HOME", str(home))
    monkeypatch.delenv("UVD_HOME", raising=False)
    with pytest.raises(module.UsdbRuntimeError, match="dap requires UVD_HOME"):
        module._find_tool("dap")
    assert "UVD_HOME" not in os.environ


def test_subprocess_preserves_installation_variables(tmp_path, monkeypatch):
    """Queries inherit the configured UVS/UVD roots without deriving another release."""
    import json
    from ucagent.util.waveform_formats import read_usdb as module

    expected = {"UVS_HOME": str(tmp_path / "uvs"), "UVD_HOME": str(tmp_path / "uvd")}
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    command = [sys.executable, "-c", "import json, os; print(json.dumps({k: os.environ[k] for k in ('UVS_HOME', 'UVD_HOME')}))"]
    code, output = module._run_tool(command, cwd=tmp_path)
    assert code == 0
    assert json.loads(output) == expected
    assert {key: os.environ[key] for key in expected} == expected


@pytest.mark.parametrize("priority", [None, ["usdb"], ["vcd"]])
def test_default_formats_include_usdb_and_respect_overrides(tmp_path, priority):
    """YAML and runtime defaults include USDB; explicit format lists replace defaults."""
    import json
    from ucagent.util.config import Config, load_yaml_with_env_vars, load_runtime_config, save_runtime_config
    from ucagent.util.waveform_formats import DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY

    defaults = ["fst", "vcd", "fsdb", "usdb"]
    assert list(DEFAULT_WAVEFORM_ANALYSIS_FORMAT_PRIORITY) == defaults
    settings = load_yaml_with_env_vars(Path(__file__).resolve().parents[1] / "ucagent" / "setting.yaml")
    assert settings["runtime_options"]["waveform_analysis_format_priority"] == defaults
    options = {"need_ref_model": False, "mock_components_enabled": False}
    if priority is not None:
        options["waveform_analysis_format_priority"] = priority
    cfg = Config({"runtime_options": options, "tools": {"RunTestCases": {"test_dir": "tests"}}})
    cfg._temp_cfg = {"DUT": "Demo", "OUT": "out"}
    path = save_runtime_config(str(tmp_path), cfg)
    expected = defaults if priority is None else priority
    assert json.loads(path.read_text(encoding="utf-8"))["runtime_options"]["waveform_analysis_format_priority"] == expected
    assert load_runtime_config(str(tmp_path))["runtime_options"]["waveform_analysis_format_priority"] == expected
