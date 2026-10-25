"""Opt-in licensed VCS compilation, simulation and real FSDB analysis acceptance."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.server.api_master import PdbMasterApiServer
from ucagent.tools import WaveInfo


@pytest.mark.skipif(not os.environ.get("UCAGENT_VCS_PICKER"), reason="Requires VCS/Verdi and picker")
def test_vcs_compile_simulate_analyze(tmp_path, monkeypatch):
    """Exercise the production command builder and check real arithmetic, FSDB and VDB data."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "Adder.v"
    source.write_text(
        "module Adder(input [127:0] a, b, input cin, output [127:0] sum, output cout);\n"
        "assign {cout, sum} = {1'b0, a} + {1'b0, b} + cin;\nendmodule\n"
    )
    build = tmp_path / "build"
    build.mkdir()
    command = PdbMasterApiServer._build_picker_command(
        None, workspace_dir=str(tmp_path), picker_workspace=str(build), dut_name="Adder",
        selected_module="Adder", main_verilog_path=str(source),
        picker_extra_args=["--sim", "vcs", "--verdi-mode", "modern", "--autobuild", "false"],
    )
    command[0] = os.environ["UCAGENT_VCS_PICKER"]
    environment = os.environ.copy()
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONPATH"] = os.pathsep.join([
        str(build), str(Path(__file__).resolve().parents[1]), environment.get("PYTHONPATH", ""),
    ])
    for name, invocation in [("generate", command), ("build", ["make", "-C", str(build / "Adder"), "NPROC=2"])]:
        result = subprocess.run(invocation, env=environment, capture_output=True, text=True, timeout=300)
        (tmp_path / f"{name}.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    test_dir = tmp_path / "tests"
    session = test_dir / "data/toffee_tmp_20261024000000_123/master"
    session.mkdir(parents=True)
    waveform = session / "test_real_vcs.fsdb"
    environment["LD_PRELOAD"] = str(build / "Adder/libUTAdder.so") + " " + environment.get("LD_PRELOAD", "")
    simulation = f'''
import ucagent
from Adder import DUTAdder
assert DUTAdder.SIMULATOR == "vcs"
dut = DUTAdder()
assert ucagent.get_default_subfix(dut, "waveform") == "fsdb"
assert ucagent.get_default_subfix(dut, "coverage") == "vdb"
dut.SetWaveform({str(waveform)!r})
dut.SetCoverage("test_real_vcs.vdb")
for left, right, carry in [(0, 0, 0), (1, 2, 0), (15, 1, 1), (2**128 - 1, 0, 1)]:
    dut.a.value, dut.b.value, dut.cin.value = left, right, carry
    dut.Step(2)
    total = left + right + carry
    assert dut.sum.value == total % 2**128
    assert dut.cout.value == total >> 128
print("VCS_ARITHMETIC_PASSED", flush=True)
dut.Finish()
print("VCS_FINISH_RETURNED", flush=True)
dut.Finish()
print("VCS_FINISH_IDEMPOTENT", flush=True)
'''
    result = subprocess.run([sys.executable, "-c", simulation], env=environment,
                            capture_output=True, text=True, timeout=120)
    (tmp_path / "simulation.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VCS_ARITHMETIC_PASSED" in result.stdout, result.stdout + result.stderr
    assert "VCS_FINISH_RETURNED" in result.stdout, result.stdout + result.stderr
    assert "VCS_FINISH_IDEMPOTENT" in result.stdout, result.stdout + result.stderr
    assert waveform.is_file() and waveform.stat().st_size > 0
    coverage = build / "Adder/Adder.vdb/snps/coverage/db/testdata/test_real_vcs"
    assert (coverage / "line.verilog.data.xml").is_file()
    pytest_case = tmp_path / "test_finish.py"
    pytest_case.write_text(
        "import pytest\nfrom Adder import DUTAdder\n"
        "@pytest.fixture\ndef dut():\n"
        "    instance = DUTAdder()\n    yield instance\n    instance.Finish()\n"
        "def test_finish(dut):\n"
        "    dut.a.value = 1\n    dut.b.value = 2\n    dut.cin.value = 0\n"
        "    dut.Step(2)\n    assert dut.sum.value == 3\n"
    )
    for options in ([], ["--forked"]):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *options, str(pytest_case)],
            env=environment, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout + result.stderr
    tool = WaveInfo(workspace=str(tmp_path), test_dir=str(test_dir), format_priority=["fsdb"])
    analysis = tool.analyze(test_case_name="test_real_vcs",
                            pattern=[{"signal": "Adder_top.Adder.cout", "event": "change"}],
                            start_step=0, end_step=100000)
    (tmp_path / "analysis.json").write_text(json.dumps(analysis, indent=2))
    assert analysis["success"] is True, analysis
    assert analysis["waveform_selection"]["format"] == "fsdb"
    assert analysis["timeline"], analysis
    assert analysis["signals"]["Adder_top.Adder.cout"]["width"] == 1
    assert analysis["waveform_info"]["last_wave_step"] == 80000
    assert analysis["timeline"][65000]["values"]["Adder_top.Adder.cout"] == "1'b1"
