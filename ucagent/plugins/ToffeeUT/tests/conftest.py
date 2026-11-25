"""Temporary, pure-Python contract fixtures; these tests make no hardware PASS claim."""

from pathlib import Path
import sys

import pytest
import yaml

from toffee_ut.project import inspect_inputs, scaffold
from toffee_ut.paths import digest, write_json
from toffee_ut.sources import capture_source_documents, record_source_documents


def write_contract(path, data):
    """Write one complete Markdown contract with the canonical typed YAML block."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n# Contract\n\n```yaml\n" + yaml.safe_dump(data, sort_keys=False) + "```\n")


@pytest.fixture
def contract_writer():
    """Provide the same complete contract writer to tests without cross-conftest imports."""
    return write_contract


@pytest.fixture
def project(tmp_path):
    """Create source/contract files without a native DUT or any compilation."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "interface.md").write_text("\n# Independent test fixture contract\n\nIdentity is preserved.\n")
    (inputs / "Block.sv").write_text("// Inventory fixture only, never compiled.\n")
    scaffold(tmp_path, "Block")
    root = tmp_path / "ut_project"
    (root / "conftest.py").write_text('"""Pure-Python adapter self-test; deliberately no native DUT."""\n')
    (root / "testbenches/block/tests/test_contract.py").write_text(
        '"""Pure adapter test, not hardware evidence."""\nimport pytest\n'
        '@pytest.mark.scenario("S1")\ndef test_value():\n    actual = int("1")\n    assert actual == 1\n')
    write_contract(root / "docs/spec/design/Block.md", {
        "kind": "design", "dut": "Block", "requirements": [{"id": "R1", "statement": "Identity is preserved",
        "precondition": "Legal input", "observation": "Returned value", "timing": "On response",
        "source": "inputs/interface.md", "basis": "confirmed"}]})
    write_contract(root / "docs/spec/verification/Block.md", {
        "kind": "verification", "dut": "Block", "scenarios": [{"id": "S1", "requirement": "R1",
        "stimulus": "Offer one legal input", "expected": "Same value", "oracle": "Independent fixture contract",
        "completion": "Compare the returned value", "status": "active"}]})
    record_source_documents(tmp_path, "Block", "ut_project", capture_source_documents(
        tmp_path, "Block", "ut_project", ["inputs/interface.md"]))
    return tmp_path


@pytest.fixture
def checked_evidence(project, monkeypatch):
    """Inject typed audit input, not a runnable or signed claim of real native execution."""
    from toffee import Bin, CoverGroupDef, CoverPointDef, CoverageDatabase
    root = project / "ut_project"
    write_json(root / "results/input_inventory.json", inspect_inputs(
        project, "Block", documents=[], rtl_dirs=["inputs/Block.sv"], mode="derive"))
    source_rtl = project / "inputs/Block.sv"
    write_contract(root / "docs/reviews/Block-static-review.md", {
        "kind": "static_review", "dut": "Block",
        "sources": [{"path": "inputs/Block.sv", "sha256": digest(source_rtl),
                     "review": "One-line inventory fixture has no actual simulator logic"}], "candidates": []})
    source = root / "dut/Block/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('"""Audit input fixture, not a native simulator."""\n')
    definition = CoverGroupDef("checks", (CoverPointDef("result", {"matched": Bin.values(1)}),))
    group = definition.instantiate("unit-audit-only", capture=False)
    group.sample({"result": 1})
    coverage = root / "results/unit-audit-only/functional-coverage.json"
    CoverageDatabase([group]).write_json(coverage)
    node = "testbenches/block/tests/test_contract.py::test_value"
    phases = {phase: {"outcome": "passed", "duration": 0.01, "wasxfail": None}
               for phase in ("setup", "call", "teardown")}
    native = root / "results/unit-audit-only/native/coverage.dat"
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_bytes(b"# SystemC::Coverage-3\nC '\x01f\x02inputs/Block.sv\x01l\x021\x01page\x02v_line' 1\n")
    data = {"record": {"dut": "Block", "run": "results/unit-audit-only", "full_selection": True,
                       "seed": 17, "signature": "unit-audit-input-not-a-real-receipt", "line_coverage_required": False},
            "cases": {"cases": {node: {"phases": phases, "scenarios": ["S1"], "selftest": False,
                                       "native_duts": [{"class": "DUTBlock", "source": str(source)}], "status": "PASS"}}},
            "manifest": {"artifacts": [{"kind": "native", "path": str(native),
                                         "build": {"name": "DUTBlock", "build_id": "unit-only", "files": {str(source): "unit-only"}}},
                                        {"kind": "functional", "path": str(coverage)}]}}
    monkeypatch.setattr("toffee_ut.audit.current_run", lambda workspace, project: data)
    return data


@pytest.fixture(scope="session", autouse=True)
def candidate_imports():
    """Assert every plugin import remains in this isolated candidate, never the live plugin."""
    root = Path(__file__).resolve().parents[1] / "src"
    yield
    modules = {name: module.__file__ for name, module in tuple(sys.modules.items())
               if name == "toffee_ut" or name.startswith("toffee_ut.")}
    for name, filename in modules.items():
        assert filename and Path(filename).resolve().is_relative_to(root), (name, filename)
    print({"isolated_src": str(root), "checked_plugin_modules": len(modules), "all_isolated": True})
