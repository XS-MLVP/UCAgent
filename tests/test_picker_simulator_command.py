"""Picker launch defaults follow the selected simulator and explicit options."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.server.api_master import PdbMasterApiServer


def command(args):
    """Build a command without starting a master or executing a simulator."""
    return PdbMasterApiServer._build_picker_command(
        None, workspace_dir="/workspace", picker_workspace="/workspace/build",
        dut_name="Adder", selected_module="Adder", main_verilog_path="/workspace/Adder.v",
        picker_extra_args=args,
    )


@pytest.mark.parametrize("args,access,suffix", [
    ([], "mem_direct", "fst"),
    (["--sim", "vcs"], "dpi", "fsdb"),
    (["--sim=vcs"], "dpi", "fsdb"),
    (["--sim", "verilator"], "mem_direct", "fst"),
])
def test_simulator_defaults(args, access, suffix):
    """Both simulator option forms select matching access and waveform defaults."""
    result = command(args)
    assert result[result.index("--rw") + 1] == access
    assert result[result.index("-w") + 1] == f"/workspace/build/Adder/Adder.{suffix}"


def test_explicit_options_are_not_duplicated():
    """A requested waveform or access mode overrides defaults exactly once."""
    result = command(["--sim=vcs", "--access-mode=dpi", "--wave_file_name=custom.fsdb"])
    assert "--rw" not in result
    assert "-w" not in result
    assert result.count("--wave_file_name=custom.fsdb") == 1


@pytest.mark.parametrize("args", [
    ["--sim"], ["--sim="], ["--sim", "vcs", "--sim=verilator"],
    ["--sim=vcs", "--rw=mem_direct"], ["--rw", "2"],
    ["--rw=dpi", "--access-mode=dpi"], ["--sim", "--rw=dpi"],
])
def test_invalid_options_fail_before_execution(args):
    """Ambiguous or incompatible options cannot produce a launch command."""
    with pytest.raises(ValueError):
        command(args)


def test_picker_numeric_access_values_remain_valid():
    """Picker also accepts the underlying enum values for explicit access modes."""
    assert "--rw=0" in command(["--sim=vcs", "--rw=0"])
    assert "--rw=DPI" in command(["--sim=vcs", "--rw=DPI"])
    assert "--rw=1" in command(["--sim=verilator", "--rw=1"])
    with pytest.raises(ValueError):
        command(["--sim=vcs", "--rw=1"])


@pytest.mark.parametrize("flags", [[], ["-V", "-debug_access+all"], ["--vflag=-debug_access+all -kdb"]])
def test_vcs_builds_a_verdi_database_preserving_custom_flags(flags):
    """New VCS workspaces have a design database without duplicating user flags."""
    import shlex

    result = command(["--sim=vcs", *flags])
    index = next(index for index, arg in enumerate(result) if arg.partition("=")[0] in ("-V", "--vflag"))
    option, separator, value = result[index].partition("=")
    tokens = shlex.split(value if separator else result[index + 1])
    assert tokens.count("-kdb") == 1
    if flags:
        assert "-debug_access+all" in tokens
    assert "--vflag=-kdb" not in command(["--sim=verilator"])
