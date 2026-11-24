"""Exercise the actual launch gate with isolated signed synthetic native artifacts."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from toffee_ut.paths import digest, source_identity, write_json
from toffee_ut.runner import _signature, run_tests
from toffee_ut.tools import RunToffee
from ucagent.core.tools.uctool import to_mcp_tool


SOURCE = "inputs/Block.sv"
NODE = "testbenches/block/tests/test_contract.py::test_value"
OLD, NEW = "results/old", "results/targeted"


def point(name):
    return f"\x01f\x02{SOURCE}\x01l\x0210\x01page\x02v_toggle\x01o\x02{name}"


def selector(name):
    return dict(metric="toggle", build="native", source=SOURCE, line=10, point=point(name))


def sign(workspace, run, values, *, full, build="native", seed=7, pass_=True):
    root = workspace / "ut_project"
    path = root / run
    path.mkdir(parents=True, exist_ok=True)
    native = path / "coverage.dat"
    native.write_bytes(b"# SystemC::Coverage-3\n" + b"".join(
        f"C '{point(name)}' {count}\n".encode() for name, count in values.items()))
    status = "PASS" if pass_ else "FAIL"
    rc = int(not pass_)
    phases = {n: {"outcome": "failed" if not pass_ and n == "call" else "passed", "wasxfail": None}
              for n in ("setup", "call", "teardown")}
    write_json(path / "cases.json", {"cases": {NODE: {"status": status, "phases": phases, "selftest": False,
                                                    "native_duts": [{"class": "DUTBlock"}]}},
                                      "collection": [NODE], "errors": [], "collect_only": False,
                                      "deselected": [], "counts": {status: 1}, "exitstatus": rc})
    write_json(path / "manifest.json", {"state": "committed", "coverage_complete": True, "tests": {status: 1},
                                        "pytest_exitstatus": rc, "artifacts": [{"kind": "native", "path": str(native),
                                        "sha256": digest(native), "build": {"name": "DUTBlock", "build_id": build}}]})
    sources = source_identity(root, workspace, ["inputs/interface.md"])
    record = {"dut": "Block", "run": run, "full_selection": full, "line_coverage_required": True, "seed": seed,
              "selection": {"targets": [NODE.split("::")[0].rsplit("/", 1)[0] if full else NODE], "keyword": "", "markers": ""},
              "returncode": rc, "waveforms": {}, "extra_inputs": ["inputs/interface.md"],
              "source_before": sources, "source_after": sources,
              "files": {n: digest(path / n) for n in ("cases.json", "manifest.json")}}
    record["signature"] = _signature(workspace, record, create=True)
    write_json(path / "receipt.json", record)
    if not full:
        write_json(root / "results/latest.json", record)
    return record


@pytest.fixture
def launch_gate(project, monkeypatch):
    root = project / "ut_project"
    calls = []
    stage = SimpleNamespace(name="line_coverage_analysis_and_improvement")
    config = {"runtime_options.ut_coverage_batch_preflight": True, "write_dirs": ["ut_project"]}
    cfg = SimpleNamespace(get_value=config.get, seed=7)
    tool = RunToffee(manager=SimpleNamespace(cfg=cfg, get_current_stage=lambda: stage),
                     workspace=str(project), project="ut_project", dut="Block")
    monkeypatch.setattr("toffee_ut.tools.load_runtime_config", lambda *_: {"ucagent_python_path": str(project)})
    monkeypatch.setattr("toffee_ut.tools.run_tests", lambda *a, **kw: calls.append((a, kw)) or {"ok": True})
    sign(project, OLD, {"way0-rise": 0, "known": 2, "unrelated": 0}, full=True)
    source = root / NODE.split("::")[0]
    source.write_text(source.read_text() + "\n# changed candidate\n")
    batch = {"baseline": OLD, "targeted": NEW, "expect_hits": [selector("way0-rise")], "retain_hits": [selector("known")]}
    return tool, calls, stage, source, batch


@pytest.mark.parametrize("targets", [None, ["testbenches/block/tests"]])
def test_no_probe_cannot_launch_full_or_invalidate_pointer(project, launch_gate, targets):
    tool, calls, _, _, _ = launch_gate
    rec = sign(project, NEW, {"way0-rise": 0}, full=False)
    result = tool._run(targets=targets)
    assert result["error_code"] == "UT_COVERAGE_PREFLIGHT"
    assert not calls
    assert json.loads((project / "ut_project/results/latest.json").read_text()) == rec


@pytest.mark.parametrize("values, kwargs, why", [
    ({"way0-rise": 0, "known": 4, "unrelated": 5}, {}, "expect_hits[0]"),
    ({"way0-rise": 1, "known": 0}, {}, "retain_hits[0]"),
    ({"known": 4, "unrelated": 5}, {}, "expect_hits[0]"),
    ({"way0-rise": 1, "known": 4}, {"build": "different"}, "same native builds"),
    ({"way0-rise": 1, "known": 4}, {"seed": 8}, "inputs and seed"),
    ({"way0-rise": 1, "known": 4}, {"pass_": False}, "PASS outcomes"),
])
def test_wrong_or_regressed_evidence_does_not_launch(project, launch_gate, values, kwargs, why):
    tool, calls, _, _, batch = launch_gate
    sign(project, NEW, values, full=False, **kwargs)
    result = tool._run(coverage_batch=batch)
    assert result["error_code"] == "UT_COVERAGE_PREFLIGHT" and why in result["error"]
    assert not calls


def test_exact_signed_current_evidence_launches_once(project, launch_gate):
    tool, calls, _, source, batch = launch_gate
    rec = sign(project, NEW, {"way0-rise": 1, "known": 4, "unrelated": 0}, full=False)
    assert tool.invoke({"coverage_batch": batch})["ok"]
    assert len(calls) == 1
    assert calls[0][1]["expected_sources"] == rec["source_after"]
    source.write_text(source.read_text() + "\n# changed again\n")
    result = tool._run(coverage_batch=batch)
    assert result["error_code"] == "UT_COVERAGE_PREFLIGHT" and "stale" in result["error"]
    assert len(calls) == 1


def test_same_inputs_require_reusing_the_full_baseline(project, launch_gate):
    tool, calls, _, _, batch = launch_gate
    sign(project, OLD, {"way0-rise": 0, "known": 1}, full=True)
    sign(project, NEW, {"way0-rise": 1, "known": 1}, full=False)
    assert "reuse" in tool._run(coverage_batch=batch)["error"]
    assert not calls


def test_targeted_and_noncoverage_stages_still_launch(launch_gate):
    tool, calls, stage, _, _ = launch_gate
    assert tool._run(targets=[NODE])["ok"]
    stage.name = "other_stage"
    assert tool._run()["ok"]
    assert len(calls) == 2 and all(row[1]["expected_sources"] is None for row in calls)


def test_late_source_mismatch_preserves_pointer(project, launch_gate, monkeypatch):
    sign(project, NEW, {"way0-rise": 1}, full=False)
    latest = project / "ut_project/results/latest.json"
    before = latest.read_bytes()
    monkeypatch.setattr("toffee_ut.runner.execute", lambda *a, **k: pytest.fail("started pytest"))
    assert run_tests(project, "Block", expected_sources={"stale": "value"})["error_code"] == "UT_COVERAGE_PREFLIGHT"
    assert latest.read_bytes() == before


def test_plugin_workflow_enables_preflight():
    config = Path(__file__).resolve().parents[1] / "src/toffee_ut/workflows/ut.yaml"
    data = yaml.safe_load(config.read_text())
    assert data["runtime_options"]["ut_coverage_batch_preflight"] is True


def test_mcp_schema_exposes_exact_point_members_without_refs():
    schema = to_mcp_tool(RunToffee()).parameters
    assert '"$ref"' not in json.dumps(schema)
    batch = next(item for item in schema["properties"]["coverage_batch"]["anyOf"] if item.get("type") == "object")
    assert set(batch["required"]) == {"baseline", "targeted", "expect_hits", "retain_hits"}
    assert set(batch["properties"]["expect_hits"]["items"]["properties"]) == set(selector("bit"))
