"""Native metric separation and required coverage closure, without compiling a DUT."""

from copy import deepcopy
from pathlib import Path

from toffee_ut.audit import audit_project, delivery_data
from toffee_ut.coverage import coverage_data
from toffee_ut.paths import digest
from toffee_ut.tools import CoverageInfo
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


def test_native_line_branch_toggle_are_distinct_and_gaps_block_delivery(project, checked_evidence, contract_writer, monkeypatch):
    """Listing a gap is not closing it, and a toggle hit cannot inflate physical lines."""
    data = checked_evidence
    monkeypatch.setattr("toffee_ut.stage_checks.line_coverage.current_run", lambda workspace, project: data)
    data["record"]["line_coverage_required"] = True
    native = Path(data["manifest"]["artifacts"][0]["path"])
    native.write_bytes(native.read_bytes() + b"C '\x01f\x02inputs/Block.sv\x01l\x021\x01page\x02v_toggle\x01o\x02data[0]' 9\n"
        b"C '\x01f\x02inputs/Block.sv\x01l\x021\x01page\x02v_branch\x01o\x02true' 0\n")
    lcov = native.with_suffix(".info")
    lcov.write_text("SF:inputs/Block.sv\nDA:1,0\nDA:2,7\nend_of_record\n")
    data["manifest"]["artifacts"].append({"kind": "lcov", "path": str(lcov)})
    report = coverage_data(project, "ut_project", "Block", data)
    assert report["line"]["found"] == 2 and report["line"]["coverage"] == 50
    assert report["toggle"]["coverage"] == 100 and report["branch"]["coverage"] == 0
    assert delivery_data(project, "Block", "ut_project")["status"] == "INCOMPLETE"
    source = project / "inputs/interface.md"
    entry = {"source": "inputs/interface.md", "sha256": digest(source), "run": data["record"]["run"],
             "observation": "Review actual uncovered physical lines", "next_action": "Fix the legal stimulus gap",
             "uncovered": [{"source": "inputs/Block.sv", "line": 1, "status": "gap", "reason": "Required path not exercised"},
                           {**report["branch"]["uncovered"][0], "metric": "branch", "status": "justified",
                            "reason": "This branch alternative is outside the independently declared fixture contract"}]}
    path = project / "ut_project/docs/reviews/Block-stage-evidence.md"
    contract_writer(path, {"kind": "stage_evidence", "dut": "Block", "reviews": {"line_coverage": entry}})
    summary = delivery_data(project, "Block", "ut_project")
    assert "native_line_coverage_review_gaps" in summary["problems"] and summary["status"] == "INCOMPLETE"
    assert not audit_project(project, "Block", phase="line_coverage")["ok"]
    assert "CoverageInfo" in audit_project(project, "Block", phase="final")["error"]
    entry["uncovered"][0].update(status="justified", reason="Independent contract excludes the unreachable fixture branch")
    contract_writer(path, {"kind": "stage_evidence", "dut": "Block", "reviews": {"line_coverage": entry}})
    assert audit_project(project, "Block", phase="line_coverage")["ok"]
    assert delivery_data(project, "Block", "ut_project")["status"] == "PASS"
    for change in ({"run": "results/other"}, {"uncovered": []}, {"sha256": "0" * 64}):
        contract_writer(path, {"kind": "stage_evidence", "dut": "Block", "reviews": {"line_coverage": {**entry, **change}}})
        assert not audit_project(project, "Block", phase="line_coverage")["ok"]
        assert delivery_data(project, "Block", "ut_project")["status"] == "INCOMPLETE"


def test_missing_coverage_and_wrong_dut_do_not_become_full_coverage(project, checked_evidence, monkeypatch):
    """No LCOV remains not_collected; another DUT's counters never satisfy this DUT."""
    report = coverage_data(project, "ut_project", "Block", checked_evidence)
    assert report["line"]["state"] == "not_collected" and report["line"]["coverage"] is None
    other = deepcopy(checked_evidence)
    other["manifest"]["artifacts"][0]["build"]["name"] = "DUTOther"
    assert coverage_data(project, "ut_project", "Block", other)["builds"] == 0
    monkeypatch.setattr("toffee_ut.tools.current_run", lambda workspace, project: checked_evidence)
    tool = CoverageInfo(workspace=str(project), project="ut_project", dut="Block", cfg=Config({}))
    assert to_mcp_tool(tool).parameters["additionalProperties"] is False
    result = tool._run(metric="toggle", limit=1)
    assert result["ok"] and result["metrics"]["toggle"]["state"] == "not_collected"
