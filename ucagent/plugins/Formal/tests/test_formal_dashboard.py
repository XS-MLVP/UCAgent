"""Exercise Formal preflight, archived proof projection, and shared trace queries."""

from dataclasses import asdict
from hashlib import sha256
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from formal.dashboard import FormalDashboard
from formal.execution import ExecutionPolicy
from formal.preflight import PreflightError, check_bodies
from formal.skills.lib.models import semantic_inputs
from formal.tools import render_environment
from formal.trace import TraceQuery
from ucagent.interfaces.server.api_cmd.formal_routes import register_formal_routes


FULL = "a" * 32
SECOND = "b" * 32
ASSERT = "top.u_checker.A_CK_VALUE"
COVER = "top.u_checker.C_CK_ACTIVE"


def records_fixture():
    """Return a small three-kind property tree with stable identifiers."""
    return {"dut": "Adder", "basic_info": {"clock_reset": {"clock_count": 0}},
            "spec": {"function_groups": [{"id": "FG-SUM", "name": "Sum and carry", "functions": [
                {"id": "FC-SUM", "description": "Compare sum outputs", "check_points": [
                    {"id": "CK-VALUE", "style": "Comb", "description": "Sum value", "sva_body": "sum == a;"},
                    {"id": "CK-ACTIVE", "style": "Cover", "description": "Carry is reachable", "sva_body": "carry;"},
                    {"id": "CK-LEGAL", "style": "Assume", "description": "Allowed inputs", "sva_body": "a != 0;"},
                ]}
            ]}]}}


def write_vcd(path):
    """Write an independent multi-clock trace with unknown and wide samples."""
    path.write_text("""$timescale 10 ps $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 1 % auxclk $end
$var wire 80 @ bus [79:0] $end
$var wire 4 # status [3:0] $end
$scope module nested $end
$var wire 1 & clk $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0%
0&
b0 @
b0 #
#5
1!
1&
b1xz0 #
#10
0!
1%
b10000000000000000000000000000000000000000000000000000000000000000000000000000001 @
#15
1!
0%
#20
0!
#25
""")


def write_saved_formal(workspace):
    """Create portable stopped run artifacts with a real VCD and hashed tool report."""
    out = workspace / "formal_test"
    out.mkdir(parents=True)
    runtime = workspace / ".ucagent"
    runtime.mkdir()
    (runtime / "runtime_config.json").write_text(json.dumps({"DUT": "Adder", "OUT": "formal_test", "formal_data": {}}))
    records = records_fixture()
    (out / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    (out / "05_Adder_formal_summary.md").write_text("# Fixture summary\n")
    root = out / "formal_runs"
    attempt = root / FULL / "attempts" / "000001"
    witness = attempt / "avis" / ASSERT / (ASSERT + ".tb.v")
    witness.parent.mkdir(parents=True)
    witness.write_text("// initialization\ninitial begin\na <= 4'b0010;\nend\n")
    vcd = witness.with_name(ASSERT + ".vcd")
    write_vcd(vcd)
    console = attempt / "console.log"
    console.write_text(f"UCAGENT_RESULT_BEGIN\n 1 {ASSERT} : Fail (2)\nUCAGENT_RESULT_END\n")
    state = {"run_id": FULL, "scope": "full", "fingerprint": "current-fingerprint", "status": "AWAITING_REVIEW",
             "workspace": str(workspace), "semantic_inputs": semantic_inputs(records), "created_at": 2,
             "policy": asdict(ExecutionPolicy()), "decisions": [], "checkpoints": [], "properties": {
                 ASSERT: {"kind": "assert", "result": "FALSIFIED", "state": "RESOLVED", "raw_status": "Fail",
                          "depth": 2, "execution_elapsed_s": 1, "attempts": [{
                              "console": "attempts/000001/console.log", "returncode": 0, "budget_s": 300,
                              "active_s": 1, "lane": "fast", "console_hash": sha256(console.read_bytes()).hexdigest(),
                              "witness_hash": sha256(witness.read_bytes()).hexdigest(), "trace_hash": sha256(vcd.read_bytes()).hexdigest(),
                          }]},
                 COVER: {"kind": "cover", "result": "UNPROVEN", "state": "REVIEW", "review_round": 1,
                         "execution_elapsed_s": 1200, "attempts": [], "disposition": "DEFERRED"},
             }}
    (root / FULL / "state.json").write_text(json.dumps(state))
    (root / FULL / "report.md").write_text("# Batch report\n")
    other = root / SECOND
    other.mkdir()
    old = json.loads(json.dumps(state))
    old.update(run_id=SECOND, created_at=1, status="COMPLETED", fingerprint="older-fingerprint")
    old["properties"][COVER].update(result="COVER_REACHED", state="RESOLVED", disposition=None)
    (other / "state.json").write_text(json.dumps(old))
    (root / "current.json").write_text(json.dumps({"run_id": FULL}))
    return records, vcd


def test_local_sva_diagnostics_collect_ck_positions():
    """A fragment can reference unknown names, while malformed bodies report exact CKs."""
    check_bodies({"CK-VALID": "valid |-> unknown_name;"}, "formal_test/.formal_records.yaml")
    with pytest.raises(PreflightError) as error:
        check_bodies({"CK-A": "(valid == ;", "CK-B": "ready |-> ;"}, "formal_test/.formal_records.yaml")
    assert {item["ck_id"] for item in error.value.diagnostic["diagnostics"]} == {"CK-A", "CK-B"}
    assert error.value.diagnostic["layer"] == "property_body"


def test_full_sva_preflight_reports_width_and_preserves_previous_artifacts(tmp_path):
    """Warnings preserve the expression while elaboration failures preserve prior files."""
    dut = tmp_path / "Adder"
    dut.mkdir()
    (dut / "adder.sv").write_text("module Adder(input logic [31:0] a, output logic [191:0] sum, output logic carry); assign sum={160'b0,a}; assign carry=|a; endmodule\n")
    output = tmp_path / "formal_test"
    output.mkdir()
    records = records_fixture()
    path = output / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(records))
    result = render_environment(str(tmp_path), "formal_test", "Adder")
    width = next(warning for warning in result["warnings"] if warning["ck_id"] == "CK-VALUE")
    assert [item["width"] for item in width["operands"]] == [192, 32]
    checker = output / "tests" / "Adder_checker.sv"
    original = checker.read_bytes()
    records["spec"]["function_groups"][0]["functions"][0]["check_points"][0]["sva_body"] = "sum == undeclared;"
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(PreflightError) as error:
        render_environment(str(tmp_path), "formal_test", "Adder")
    assert any(item.get("ck_id") == "CK-VALUE" and "undeclared" in item["message"]
               for item in error.value.diagnostic["diagnostics"])
    assert checker.read_bytes() == original


def test_archived_view_and_trace_api_share_exact_evidence(tmp_path):
    """Saved browsing follows current archive identity and refuses mutated VCD evidence."""
    pytest.importorskip("wavekit")
    records, vcd = write_saved_formal(tmp_path)
    app = FastAPI()
    register_formal_routes(app, None, lambda request: (tmp_path, "", True))
    client = TestClient(app)
    view = client.get("/api/formal/view").json()["data"]
    assert view["freshness"] == "archived" and view["run"]["scope"] == "full"
    assert view["counts"]["UNPROVEN"] == 1 and view["counterexamples"] == 1 and view["bugs"] == 0
    item = view["groups"][0]["children"][0]["children"][0]["property"]
    assert item["name"] == ASSERT and item["trace"] and item["review_actions"] == []
    body = {"scope": "full", "run_id": FULL, "property": ASSERT, "query": {"mode": "signals", "limit": 2}}
    first = client.post("/api/formal/trace", json=body).json()["data"]
    assert first["time_unit"] == "ps" and first["time_magnitude"] == "10" and first["next_cursor"]
    body["query"]["cursor"] = first["next_cursor"]
    second = client.post("/api/formal/trace", json=body).json()["data"]
    assert set(row["path"] for row in first["signals"]).isdisjoint(row["path"] for row in second["signals"])
    query = TraceQuery(mode="samples", signals=["top.status[3:0]", "top.bus[79:0]", "top.absent"],
                       start="5", end="25", clock="top.clk", limit=1)
    page = FormalDashboard(tmp_path, archived=True).trace("full", FULL, ASSERT, query)
    assert page["samples"][0]["tick"] == "5" and page["next_cursor"]
    assert page["samples"][0]["values"]["top.status[3:0]"]["x_mask"] == "0x4"
    assert page["missing_signals"] == ["top.absent"]
    another = query.model_copy(update={"cursor": page["next_cursor"]})
    following = FormalDashboard(tmp_path, archived=True).trace("full", FULL, ASSERT, another)
    assert following["samples"][0]["tick"] == "15"
    assert int(following["samples"][0]["values"]["top.bus[79:0]"]["value"], 16) > 2**64
    assert client.post("/api/formal/action", json={"action": "cancel", "run_id": FULL}).status_code == 403
    compare = client.get("/api/formal/compare", params={"before_id": SECOND, "after_id": FULL,
        "before_scope": "full", "after_scope": "full"}).json()["data"]
    assert compare["cover_changes"][0]["after"] == "UNPROVEN"
    assert compare["causality"] == "pending_diagnosis"
    records["spec"]["parameters"] = {"WIDTH": 4}
    (tmp_path / "formal_test" / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    assert client.get("/api/formal/view").json()["data"]["freshness"] == "historical"
    vcd.write_text(vcd.read_text() + "\n#30\n")
    assert client.post("/api/formal/trace", json=body).status_code == 422
