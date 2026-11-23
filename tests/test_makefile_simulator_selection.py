"""Check that make init_<DUT> exports each simulator with the access mode it supports."""

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("make") is None, reason="requires make")
@pytest.mark.parametrize("simulator,suffix,access", [
    ("verilator", "fst", "1"), ("gsim", "fst", "0"),
    ("vcs", "fsdb", "0"), ("uvs", "usdb", "0"),
])
def test_init_uses_the_same_access_mode_as_master(tmp_path, simulator, suffix, access):
    """Only Verilator uses MEM_DIRECT; see test_api_master_compilation.py for Master."""
    result = subprocess.run(
        ["make", "-n", "init_Adder", f"SIM={simulator}", f"CWD={tmp_path}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    exports = [line for line in result.stdout.splitlines() if "picker export" in line]
    assert len(exports) == 2  # one branch for .v and one for .sv
    for line in exports:
        assert f"--sim {simulator} --rw {access} " in line
        assert f"Adder.{suffix}" in line
