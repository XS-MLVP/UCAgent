"""Managed pytest fixtures binding test cases to the latest measured unit build.

The conftest loads the most recent sealed measurement record, imports its
compiled public-pin DUT, and exposes an ``env`` fixture with the same pin
discipline as the managed workflow runner. It also exposes the frozen Python
reference as a ``reference`` fixture so test cases derive expected values
from ``evaluate(transactions)`` instead of hand-coded constants. Test cases
drive and observe only the pins declared in candidate/interface.yaml.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import uuid

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[3]


def _latest_record():
    """Return the record backing these tests: the delivered variant when the
    delivery revalidation pins it via REPO_TC_RECORD, else the newest record."""

    import json

    override = os.environ.get("REPO_TC_RECORD")
    if override:
        return json.loads(Path(override).read_text(encoding="utf-8"))["payload"]
    records = sorted((WORKSPACE / ".ucagent" / "repo_module" / "records").glob("*.json"))
    if not records:
        return None
    return json.loads(records[-1].read_text(encoding="utf-8"))["payload"]


@pytest.fixture
def reference():
    """Load the frozen independent reference model for expected values."""

    import importlib.util

    spec = importlib.util.spec_from_file_location("repo_reference_model", REPO_ROOT / "verification" / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


@pytest.fixture
def env():
    """Provide one fresh public-pin environment for the latest measured build."""

    record = _latest_record()
    if record is None:
        pytest.skip("No measured unit build is available; complete the baseline stage first")
    from design_with_ppa.repo.models import Interface, TaskContract, read_model
    from design_with_ppa.repo.runner import PinEnvironment

    build = WORKSPACE / record["run_directory"] / "validation"
    dut_path = build / "run" / "design_with_ppa" / "python-dut"
    if str(dut_path) not in sys.path:
        sys.path.insert(0, str(dut_path))
    interface = read_model(REPO_ROOT / "candidate", "interface.yaml", Interface)
    contract = read_model(REPO_ROOT, "contract.yaml", TaskContract)
    dut = getattr(importlib.import_module("unit_runtime"), "DUT" + interface.top)()
    wave = build / "waves" / f"tc-{uuid.uuid4().hex}.fst"
    try:
        dut.SetWaveform(str(wave))
        yield PinEnvironment(dut, interface, contract, [], wave)
    finally:
        dut.Finish()
