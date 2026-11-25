"""Check the UnitTest workspace preparer selects the correct Picker access mode."""

from pathlib import Path

import pytest

from ucagent.core.workspace.preparation import WorkspacePreparation
from unit_test.preparation import (
    UnitTestPreparationOptions,
    prepare_unittest,
    simulator_rw_mode,
)


@pytest.mark.parametrize("simulator,access", [
    ("verilator", "1"),
    ("gsim", "0"),
    ("vcs", "0"),
    ("uvs", "0"),
])
def test_prepare_unittest_uses_simulator_access_mode(tmp_path, simulator, access):
    """Pass simulator-specific memory access through the real preparation command."""
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    (source / "Adder.v").write_text("module Adder; endmodule\n", encoding="utf-8")
    calls = []

    def run_command(argv):
        args = [str(value) for value in argv]
        calls.append(args)
        if args[0] == "picker":
            output = Path(args[args.index("--tdir") + 1]) / "Adder"
            output.mkdir(parents=True, exist_ok=True)
            (output / "example.py").write_text("# generated test stub\n", encoding="utf-8")

    context = WorkspacePreparation(
        source=source,
        workspace=workspace,
        dut_name="Adder",
        options=UnitTestPreparationOptions(simulator=simulator),
        progress=lambda _message: None,
        check_cancelled=lambda: None,
        run_command=run_command,
    )

    prepare_unittest(context)

    picker_calls = [args for args in calls if args[0] == "picker"]
    assert len(picker_calls) == 1
    assert picker_calls[0][picker_calls[0].index("--sim") + 1] == simulator
    assert picker_calls[0][picker_calls[0].index("--rw") + 1] == access
    assert simulator_rw_mode(simulator) == access
