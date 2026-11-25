"""Actual waveform decoding and controlled receipts; no RTL or demo DUT is built."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from toffee_ut.audit import audit_project, read_spec, summarize
from toffee_ut.paths import digest, source_identity, write_json
from toffee_ut.runner import _signature, current_run, run_tests
from toffee_ut.waveform import WaveArgs, WaveInfo, inspect_waveform
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


VCD = """$timescale 1ns $end
$scope module TOP $end
$var wire 1 ! clk $end
$var wire 1 \" request $end
$var wire 4 # response [3:0] $end
$upscope $end
$enddefinitions $end
#0
0!
0\"
b0000 #
#5
1!
1\"
b10xz #
#10
0!
#15
1!
b0011 #
#20
0!
"""


@pytest.fixture(params=["vcd", "fst"])
def waveform_input(project, checked_evidence, monkeypatch, request):
    """Attach known physical VCD bytes to a controlled audit input, not a real DUT claim."""
    data = checked_evidence
    root = project / "ut_project"
    relative = data["record"]["run"] + "/waveforms/test.vcd"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(VCD)
    if request.param == "fst":
        converter = shutil.which("vcd2fst")
        if converter is None:
            pytest.skip("FST decoder test requires vcd2fst; no RTL is compiled")
        target = path.with_suffix(".fst")
        subprocess.run([converter, str(path), str(target)], check=True, capture_output=True)
        path = target
        relative = path.relative_to(root).as_posix()
    node, case = next(iter(data["cases"]["cases"].items()))
    case["status"] = "FAIL"
    case["phases"]["call"]["outcome"] = "failed"
    case["waveforms"] = [{"path": relative, "native_dut": case["native_duts"][0]}]
    data["record"]["waveforms"] = {relative: digest(path)}
    _signature(project, {"fixture": "decoder-only"}, create=True)
    monkeypatch.setattr("toffee_ut.waveform.current_run", lambda workspace, project: data)
    monkeypatch.setattr("toffee_ut.stage_audit.current_run", lambda workspace, project: data)
    args = WaveArgs(test_case_name=node, signal_groups={"clocks": ["TOP.clk"],
        "inputs": ["TOP.request"], "outputs": ["TOP.response"]}, begin_time=4, end_time=16)
    return data, args, path


def test_real_reader_preserves_unknowns_and_signed_analysis_unblocks_rtl(project, waveform_input, contract_writer):
    """A valid per-node observation enables real evidence checking instead of a blanket ban."""
    data, args, path = waveform_input
    original_wave = path.read_bytes()
    catalog = inspect_waveform(project, "ut_project", "Block", WaveArgs(test_case_name=args.test_case_name))
    assert catalog["ok"] and catalog["total"] == 3 and "receipt" not in catalog
    result = inspect_waveform(project, "ut_project", "Block", args)
    event = next(row for row in result["timeline"] if row["time"] == 5)
    assert event["values"]["TOP.response"] == "10xz"
    reference = {"nodeid": args.test_case_name, "receipt": result["receipt"], "at_time": 5,
                 "analysis": "Decoder fixture shows actual request=1 and response=10xz; unit test is not hardware verification"}
    issue = project / "ut_project/docs/bugs/open/mismatch.md"
    contract_writer(issue, {"kind": "issue", "run": data["record"]["run"], "nodeids": [args.test_case_name],
        "classification": "rtl", "requirement": "R1", "evidence": "Controlled audit FAIL", "next_action": "Inspect actual DUT separately",
        "waveform_evidence": [reference]})
    assert audit_project(project, "Block", phase="triage")["ok"]
    assert summarize(project, "Block", "ut_project")["status"] == "FAIL"
    assert audit_project(project, "Block", phase="final")["ok"]
    path.unlink()
    assert audit_project(project, "Block", phase="final")["ok"]
    path.write_bytes(original_wave)
    static = project / "ut_project/docs/reviews/Block-static-review.md"
    review = read_spec(static, "static_review", "Block")
    review["candidates"] = [{"id": "candidate", "source": "inputs/Block.sv", "line": 1,
        "hypothesis": "Controlled audit candidate", "status": "rtl", "evidence": "Controlled audit FAIL",
        "requirement": "R1", "run": data["record"]["run"], "nodeids": [args.test_case_name],
        "waveform_evidence": [reference]}]
    contract_writer(static, review)
    assert audit_project(project, "Block", phase="static_validation")["ok"]
    receipt = project / "ut_project" / result["receipt"]
    original = receipt.read_text()
    modified = json.loads(original)
    modified["timeline"][0]["values"]["TOP.response"] = "1111"
    receipt.write_text(json.dumps(modified))
    assert not audit_project(project, "Block", phase="triage")["ok"]
    receipt.write_text(original)
    for change in ({"at_time": 999}, {"nodeid": "another::case"}, {"analysis": ""}):
        value = read_spec(issue, "issue")
        value["waveform_evidence"] = [{**reference, **change}]
        contract_writer(issue, value)
        assert not audit_project(project, "Block", phase="triage")["ok"]
    assert path.read_bytes() == original_wave


@pytest.mark.parametrize("change", [{"begin_time": None}, {"end_time": 100},
                                   {"test_case_name": "unknown"}, {"waveform": "../outside.vcd"}])
def test_missing_or_wrong_context_never_creates_waveform_receipt(project, waveform_input, change):
    """Unknown nodes and unsupported windows fail without inventing observations."""
    _, args, _ = waveform_input
    with pytest.raises(ValueError):
        inspect_waveform(project, "ut_project", "Block", WaveArgs(**{**args.model_dump(), **change}))
    assert not (project / "ut_project/results/waveform-evidence").exists()


def test_waveform_tool_schema_permissions_and_run_identity(project, waveform_input):
    """MCP and local calls share one schema, policy and signed-run association."""
    data, args, _ = waveform_input
    cfg = Config({"write_dirs": [], "un_write_dirs": []})
    tool = WaveInfo(workspace=str(project), project="ut_project", dut="Block", cfg=cfg)
    assert to_mcp_tool(tool).parameters["additionalProperties"] is False
    assert not tool._run(**args.model_dump())["ok"]
    cfg.set_value("write_dirs", ["ut_project/results"])
    result = tool._run(**args.model_dump())
    assert result["ok"]
    data["record"]["dut"] = "Other"
    assert not tool._run(**args.model_dump())["ok"]


def test_waveinfo_archive_is_current_and_does_not_move_latest(project, waveform_input):
    data, args, selected = waveform_input
    root = project / "ut_project"
    run = data["record"]["run"]
    folder = root / run
    node = args.test_case_name
    cases = {**data["cases"], "collection": [node], "errors": [], "collect_only": False,
             "exitstatus": 1, "counts": {"FAIL": 1}, "deselected": []}
    manifest = {**data["manifest"], "state": "committed", "coverage_complete": True,
                "tests": cases["counts"], "pytest_exitstatus": 1}
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = digest(artifact["path"])
        if "build" in artifact:
            artifact["build"]["files"] = {name: digest(name) for name in artifact["build"]["files"]}
    write_json(folder / "cases.json", cases)
    write_json(folder / "manifest.json", manifest)
    identity = source_identity(root, project)
    record = {**data["record"], "files": {"cases.json": digest(folder / "cases.json"),
              "manifest.json": digest(folder / "manifest.json")}, "extra_inputs": [],
              "source_before": identity, "source_after": identity, "returncode": 1}
    record.pop("signature")
    record["signature"] = _signature(project, record)
    receipt = folder / "receipt.json"
    write_json(receipt, record)
    latest = root / "results/latest.json"
    write_json(latest, {"run": "results/another-selection"})
    before = digest(latest), digest(receipt), digest(selected)
    tool = WaveInfo(workspace=str(project), project="ut_project", dut="Block",
                    cfg=Config({"write_dirs": ["ut_project/results"], "un_write_dirs": []}))
    response = tool._run(**{**args.model_dump(), "run": run})
    assert response["ok"] and response["run"] == run and response["run_signature"] == record["signature"]
    evidence = root / response["receipt"]
    assert evidence.is_file() and (digest(latest), digest(receipt), digest(selected)) == before

    (root / "pytest.ini").write_text("[pytest]\n# input changed since this run\n")
    stale = tool._run(**{**args.model_dump(), "run": run})
    assert not stale["ok"] and "stale" in stale["error"]
    assert list(evidence.parent.iterdir()) == [evidence]


@pytest.mark.parametrize("workers", [1, 2])
def test_capture_hook_records_paths_without_advancing_a_dut(project, workers):
    """Serial/xdist adapter doubles test capture only, not native simulation correctness."""
    root = project / "ut_project"
    (root / "conftest.py").write_text('''import pytest
from pathlib import Path
class CaptureDouble:
    def SetCoverage(self, path): raise AssertionError("No actual coverage in this adapter double")
    def GetCovMetrics(self): return 0
    def GetXClock(self): return None
    def SetWaveform(self, path): self.path = path
    def Step(self, *args): raise AssertionError("Capture must not advance simulation")
    def Finish(self): Path(self.path).write_text("decoder-double-only")
@pytest.fixture
def native_dut(toffee_register_dut):
    dut = CaptureDouble()
    toffee_register_dut(dut)
    yield dut
    dut.Finish()
''')
    (root / "testbenches/block/tests/test_contract.py").write_text('''import pytest
@pytest.mark.scenario("S1")
@pytest.mark.parametrize("value", [1, 2])
def test_capture(native_dut, value):
    assert value in (1, 2)
''')
    result = run_tests(project, "Block", workers=workers)
    assert result["ok"], result
    checked = current_run(project, "ut_project")
    paths = [wave["path"] for case in checked["cases"]["cases"].values() for wave in case["waveforms"]]
    assert len(paths) == len(set(paths)) == 2
    assert all((root / path).read_text() == "decoder-double-only" for path in paths)
    (root / paths[0]).unlink()
    assert current_run(project, "ut_project")["record"]["signature"] == checked["record"]["signature"]
    (root / paths[0]).write_text("changed")
    with pytest.raises(ValueError, match="artifact"):
        current_run(project, "ut_project")
