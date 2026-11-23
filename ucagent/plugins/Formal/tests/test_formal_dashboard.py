"""Exercise Formal preflight, archived proof projection, and shared trace queries."""

from dataclasses import asdict
from hashlib import sha256
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from formal.checkers.formal import ScriptGenerationChecker
from formal.dashboard import FormalDashboard
from formal.execution import ExecutionPolicy, FormalExecution
from formal.preflight import PreflightError, check_bodies
from formal.skills.lib.models import semantic_inputs
from formal.tools import RunFormal, render_environment
from formal.trace import TraceQuery
from ucagent.interfaces.server.api_cmd.formal_routes import register_formal_routes
from ucagent.util.config import Config


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


@pytest.mark.parametrize(("boolean_operator", "property_operator"), [("&&", "and"), ("||", "or")])
def test_local_sva_diagnostic_identifies_temporal_property_operator(boolean_operator, property_operator):
    """A misplaced Boolean operator between properties has a targeted syntax hint."""
    expression = f"@(posedge clk) ((a |-> b)\n  {boolean_operator} (c |=> d));"
    with pytest.raises(PreflightError) as error:
        check_bodies({"CK-TEMPORAL": expression}, "formal_test/.formal_records.yaml")
    first = error.value.diagnostic["diagnostics"][0]
    assert first["ck_id"] == "CK-TEMPORAL" and first["body_line"] == 1
    assert f"property operator '{property_operator}'" in first["hint"]
    check_bodies({"CK-TEMPORAL": expression.replace(boolean_operator, property_operator),
                  "CK-BOOLEAN": f"(a {boolean_operator} c) |-> b;"}, "formal_test/.formal_records.yaml")


def test_assume_until_warning_distinguishes_event_trigger_from_continuously_armed_branch():
    """A per-sample until can outlaw delayed behavior allowed by a transaction rule."""
    bodies = {"CK-UNGUARDED": "@(posedge clk) disable iff (!rst_n) ((a |-> s_eventually b) and (!b until a));",
              "CK-GUARDED": "@(posedge clk) disable iff (!rst_n) (retire |=> (!b until a));",
              "CK-ASSERT": "@(posedge clk) (!b until a);"}
    alerts = check_bodies(bodies, "out/.formal_records.yaml", assume_ids={"CK-UNGUARDED", "CK-GUARDED"})
    warning, = alerts
    assert warning["ck_id"] == "CK-UNGUARDED" and warning["body_line"] == 1
    assert warning["code"] == "formal_unguarded_until_assume"
    assert "every enabled sample" in warning["message"]


@pytest.mark.parametrize("use_macro", [False, True])
def test_joint_assumption_is_reported_without_blocking_preflight(tmp_path, monkeypatch, use_macro):
    """Check reports a cost warning before a run and RunFormal can still dispatch."""
    calls = []

    def dispatch(execution, *, preflight, retry_prepare=False):
        """Record native dispatch without running the solver."""
        calls.append(preflight)
        return {"status": "RUNNING"}

    def missing_smoke(execution):
        """Represent an environment without current native preflight results."""
        raise ValueError("Current toolchain smoke is missing.")

    monkeypatch.setattr(FormalExecution, "run", dispatch)
    monkeypatch.setattr(FormalExecution, "check_smoke", missing_smoke)
    rtl = tmp_path / "Adder"
    rtl.mkdir()
    fair = "((a && b) |-> s_eventually c) and (c |-> s_eventually a)"
    (rtl / "adder.sv").write_text(f"`define FAIR {fair}\n"
                                "module Adder(input clk,rst_n,a,b,c, output sum,carry); "
                                "assign sum=a; assign carry=a; endmodule\n")
    output = tmp_path / "formal_test"
    output.mkdir()
    path = output / ".formal_records.yaml"
    records = records_fixture()
    records["basic_info"]["clock_reset"] = {
        "clock_count": 1, "clock_signal": "clk", "reset_signal": "rst_n", "reset_type": "low",
    }
    points = records["spec"]["function_groups"][0]["functions"][0]["check_points"]
    clock = "@(posedge clk) disable iff (!rst_n) "
    body = clock + ("`FAIR" if use_macro else fair) + ";"
    points[-1]["sva_body"] = body
    points.extend([
        {"id": "CK-BOUNDED", "style": "Assume", "description": "Bounded responses",
         "sva_body": clock + "(a |-> ##[1:8] b) and (c |-> s_eventually [1:8] a);"},
        {"id": "CK-SINGLE", "style": "Assume", "description": "One eventual response",
         "sva_body": clock + "((a && b) |-> s_eventually c) and (a |=> b);"},
        {"id": "CK-ASSERT", "style": "Seq", "description": "Assertion with two eventual responses",
         "sva_body": body},
    ])
    path.write_text(yaml.safe_dump(records))
    cfg = Config({"output": "formal_test", "runtime_options": {"formal_batched_sva": True}})
    checker = ScriptGenerationChecker("Adder", cfg=cfg)
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    passed, check = checker.do_check()
    assert not passed and not calls
    assert check["error"] == "Current toolchain smoke is missing."
    result = RunFormal(str(tmp_path), "formal_test", "Adder", cfg=cfg).invoke({"action": "preflight"})
    assert result["status"] == "RUNNING" and calls == [True]
    # Official property warnings belong to official rendering, never to disposable smoke.
    from formal.tools import render_environment
    official = render_environment(str(tmp_path), "formal_test", "Adder")
    row, = [warning for warning in official["warnings"] if warning["code"] == "formal_combined_unbounded_assume"]
    assert row["ck_id"] == "CK-LEGAL"
    assert body in (output / "tests" / "Adder_checker.sv").read_text()
    assert yaml.safe_load(path.read_text()) == records


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
    detail = next(item for item in error.value.diagnostic["diagnostics"]
                  if item.get("ck_id") == "CK-VALUE" and "undeclared" in item["message"])
    assert "sum == undeclared;" in detail["candidate_source"]["text"]
    assert detail["candidate_source"]["first_column"] <= detail["column"]
    assert error.value.diagnostic["inspect_calls"] == [{"request": {"action": "inspect", "section": "spec", "query": "CK-VALUE"}}]
    assert checker.read_bytes() == original


def test_assume_knownness_rejects_bound_dut_outputs(tmp_path):
    """The rendered port directions, including a reversed handshake, define the environment boundary."""
    dut = tmp_path / "Adder"
    dut.mkdir()
    (dut / "adder.sv").write_text(
        "module Adder(input clk,rst_n,a, output [1:0] sum, output carry); "
        "assign sum={a,a}; assign carry=a; endmodule\n"
    )
    output = tmp_path / "formal_test"
    output.mkdir()
    path = output / ".formal_records.yaml"
    records = records_fixture()
    records["basic_info"]["clock_reset"] = {"clock_count": 1, "clock_signal": "clk", "reset_signal": "rst_n", "reset_type": "low"}
    points = records["spec"]["function_groups"][0]["functions"][0]["check_points"]
    assumption = next(point for point in points if point["style"] == "Assume")
    assumption["sva_body"] = "@(posedge clk) !$isunknown({a, carry, sum[0]});"
    path.write_text(yaml.safe_dump(records))
    with pytest.raises(PreflightError) as caught:
        render_environment(str(tmp_path), "formal_test", "Adder")
    failures = caught.value.diagnostic["diagnostics"]
    assert {row["signal"] for row in failures} == {"carry", "sum"}
    assert all(row["ck_id"] == assumption["id"] and row["code"] == "formal_assume_output_known" for row in failures)
    assumption["sva_body"] = "@(posedge clk) !$isunknown(a);"
    points += [
        {"id": "CK-OUTPUT-TIMING", "style": "Assume", "description": "DUT output triggers an input protocol obligation",
         "sva_body": "@(posedge clk) carry |=> a;"},
        {"id": "CK-OUTPUT-VALID", "style": "Comb", "description": "DUT output must be known", "sva_body": "!$isunknown(sum);"},
    ]
    path.write_text(yaml.safe_dump(records))
    assert render_environment(str(tmp_path), "formal_test", "Adder")["status"] == "passed"


def test_workbench_assets_are_served_from_the_plugin():
    """An asset request reads packaged UI without loading a task workspace."""
    app = FastAPI()

    def fail_workspace(_request):
        pytest.fail("Packaged assets should not require a task workspace")

    register_formal_routes(app, None, fail_workspace)
    client = TestClient(app)
    entry = client.get("/static/formal/workbench-entry.js")
    assert entry.status_code == 200
    assert entry.headers["content-type"].startswith("text/javascript")
    assert "export async function load" in entry.text
    layout = client.get("/static/formal/workbench.html")
    assert layout.status_code == 200
    assert layout.headers["content-type"].startswith("text/html")
    assert 'class="activity-bar fc-rail"' in layout.text
    assert client.get("/static/formal/task-overview.js").status_code == 200
    assert client.get("/static/formal/missing.js").status_code == 404
    assert client.get("/static/formal/.formal_records.yaml").status_code == 404
    assert client.get("/static/formal/%2E%2E%2Fdashboard.py").status_code == 404


def test_overview_identifies_unfilled_formal_reports(tmp_path):
    """Distinguish generated placeholders, authored reports and older archives."""
    records, _ = write_saved_formal(tmp_path)
    output = tmp_path / "formal_test"
    (output / "01_Adder_verification_needs_and_plan.md").write_text("# Planning template\n")
    (output / "02_Adder_basic_info.md").write_text("# Adder interfaces\n")
    records.update(planning={}, basic_info={"interface_summary": "Adder inputs a and b"})
    (output / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    view = FormalDashboard(tmp_path, archived=True).view()
    reports = {report["name"]: report for report in view["reports"]}
    assert view["solver"] == "FormalMC"
    assert reports["01_Adder_verification_needs_and_plan.md"]["template_only"]
    assert not reports["02_Adder_basic_info.md"]["template_only"]
    assert not reports["05_Adder_formal_summary.md"]["template_only"]
    assert reports["02_Adder_basic_info.md"]["modified_at"] > 0


def test_fc_review_metadata_tracks_current_and_frozen_specs(tmp_path):
    records, _ = write_saved_formal(tmp_path)
    output = tmp_path / "formal_test"
    path = output / ".formal_records.yaml"
    fc = records["spec"]["function_groups"][0]["functions"][0]
    fc.update(title="Check the low bits of sum", review_order=1)
    frozen = output / "formal_runs" / FULL / "inputs" / "formal_test"
    frozen.mkdir(parents=True)
    (frozen / path.name).write_text(yaml.safe_dump(records))
    fc.update(title="Check the truncated sum", review_order=2)
    path.write_text(yaml.safe_dump(records))
    app = FastAPI()
    register_formal_routes(app, None, lambda request: (tmp_path, "", True))
    client = TestClient(app)
    view = client.get("/api/formal/view").json()["data"]
    assert view["freshness"] == "archived"
    point = view["groups"][0]["children"][0]
    assert (point["title"], point["review_order"], point["description"]) == (
        "Check the truncated sum", 2, "Compare sum outputs")

    fc["check_points"][0]["sva_body"] = "sum == a + 1;"
    path.write_text(yaml.safe_dump(records))
    view = client.get("/api/formal/view").json()["data"]
    assert view["freshness"] == "historical"
    point = view["groups"][0]["children"][0]
    assert (point["title"], point["review_order"]) == ("Check the low bits of sum", 1)


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


def test_preflight_matches_explicit_planned_output_and_sampling():
    """A different pin or a different handshake sample cannot satisfy the recorded goal."""
    plan = {
        "CK-RELEASE": {"description": "After reset release, busy must be low."},
        "CK-TRANSFER": {"description": "接受（valid & ready）后下一拍，输出保持已接受的数据。"},
    }
    def check(key, body):
        return check_bodies({key: body}, "proof/.formal_records.yaml", plan=plan, outputs={"busy"})

    with pytest.raises(PreflightError, match="busy"):
        check("CK-RELEASE", "@(posedge clk) (!req && !fifo_busy) |=> !fifo_busy; // busy")
    with pytest.raises(PreflightError, match="next sample"):
        check("CK-TRANSFER", "@(posedge clk) (valid && ready) |-> (out_data == in_data);")
    with pytest.raises(PreflightError, match="next sample"):
        check("CK-TRANSFER", "(((valid && ready && sel) |-> (a == b)) and ((valid && ready && !sel) |-> (a == c)));")
    with pytest.raises(PreflightError, match="next sample"):
        check("CK-TRANSFER", "(!(valid && ready && sel) || (left == data)) && (!(valid && ready && !sel) || (right == data));")
    assert check("CK-TRANSFER", "(!($past(valid && ready)) || posted);") == []
    assert check("CK-TRANSFER", "(valid && ready)[*2] |-> posted;") == []
    assert check("CK-TRANSFER", "((valid && ready) |-> legal) and ((valid && ready) |=> posted);") == []
    assert check("CK-RELEASE", "@(posedge clk) $rose(rst_n) |-> !busy;") == []
    assert check("CK-TRANSFER", "@(posedge clk) (valid && ready) |=> (out_data == $past(in_data));") == []
    assert check("CK-TRANSFER", "@(posedge clk) $past(valid && ready) |-> (out_data == $past(in_data));") == []


def test_source_tracking_and_corresponding_response_scope():
    """Current handshakes and a later matching response cannot by themselves identify the request."""
    plan = {"CK-SOURCE": {"description": "检查器跟踪最近一次请求选择（route_tag 记录值），比较响应来源。"},
            "CK-REPLY": {"description": "An accepted request must deliver its response with the specified payload."}}
    with pytest.raises(PreflightError, match="route_tag"):
        check_bodies({"CK-SOURCE": "(rsp_valid && rsp_ready) |-> $onehot0({left_ready, right_ready});"},
                     "out/.formal_records.yaml", plan=plan)
    body = "(rsp_valid && rsp_ready) |-> (!route_tag || (rsp_data == lane_data));"
    with pytest.raises(PreflightError, match="independent request history"):
        check_bodies({"CK-SOURCE": body}, "records.yaml", plan=plan, outputs={"rsp_valid", "rsp_data"},
                     data_inputs={"rsp_ready", "lane_data"}, internal_signals={"route_tag"})
    assert check_bodies({"CK-SOURCE": "(rsp_valid && rsp_ready) |-> (route_tag == independently_saved);"},
                        "records.yaml", plan=plan, outputs={"rsp_valid"}, data_inputs={"rsp_ready"},
                        internal_signals={"route_tag"}) == []
    warning, = check_bodies({"CK-REPLY": "(req_valid && req_ready) |-> s_eventually (rsp_valid && rsp_ok);"},
                            "out/.formal_records.yaml", plan=plan)
    assert warning["code"] == "formal_response_matching"
    assert check_bodies({"CK-REPLY": "accepted |-> (!delivered s_until (delivered && rsp_ok));"},
                        "out/.formal_records.yaml", plan=plan) == []


def test_unconditional_release_scope_does_not_depend_on_idle_inputs():
    body = "@(posedge clk) disable iff (!reset_n) ((!start && !queue_busy) |-> !active);"
    def check(requirement, expression):
        return check_bodies({"CK-RST": expression}, "out/.formal_records.yaml", outputs={"active"},
                            data_inputs={"start"}, plan={"CK-RST": {"description": requirement}})

    unconditional = "After reset release, active must be low, and the idle state must keep it low."
    with pytest.raises(PreflightError, match="pass vacuously.*start"):
        check(unconditional, body)
    with pytest.raises(PreflightError, match="masked: start=1"):
        check(unconditional, "(start || !active) && (!$rose(reset_n) || (active == (start || other)));")
    assert check("After reset release, active must be low when idle.", body) == []
    assert check(unconditional, "@(posedge clk) ($rose(reset_n) |-> !active) and (!start |-> !active);") == []
    assert check(unconditional, "@(posedge clk) !active;") == []


@pytest.mark.parametrize(("description", "pin", "level"), [
    ("At the first sample POR must be high.", "POR", "high"),
    ("假设验证初始 cold_reset_n 为低（初始复位有效）。", "cold_reset_n", "low"),
])
def test_planned_first_reset_rejects_unanchored_eventuality(description, pin, level):
    clock = {"has_clock": True, "has_reset": True, "actual_reset": pin, "reset_active_level": level}
    def check(body, requirement=description):
        return check_bodies({"CK-START": body}, "records.yaml", assume_ids={"CK-START"},
                            plan={"CK-START": {"description": requirement}}, clock_reset=clock)

    with pytest.raises(PreflightError, match="first sample"):
        check("@(posedge clk) disable iff (1'b0) (s_eventually (!rst_n));")
    assert check("initial_sample |-> !rst_n;") == []
    assert check("recover |-> s_eventually (!rst_n);") == []
    assert check("s_eventually [0:0] (!rst_n);") == []
    assert check("s_eventually (!rst_n);", f"Initially {pin} is high if cold boot was selected.") == []
    assert check("s_eventually (!rst_n);", f"Initially {pin} is high (unless resuming).") == []
    assert check("s_eventually (!rst_n);", "At the first sample other_reset is high.") == []
    assert check("s_eventually (!rst_n);", "When a reset is requested it must eventually be asserted.") == []


def test_planned_stall_assume_allows_independent_pin_values():
    requirement = "Keep offer and payload stable while backpressured."
    hold = "(offer && !accept) |=> ($stable(offer) && $stable(payload))"
    rule = "!(offer && accept) || (new_item && available)"
    def check(body, intent=requirement):
        return check_bodies({"CK-STALL": body}, "records.yaml", assume_ids={"CK-STALL"},
                            plan={"CK-STALL": {"description": intent}}, outputs={"accept", "new_item"},
                            data_inputs={"offer", "payload", "available"}, internal_signals={"winner"})
    with pytest.raises(PreflightError, match="rejects those constant values"):
        check(f"({hold}) and ({rule});")
    with pytest.raises(PreflightError, match="winner=0"):
        check(f"({hold}) and ((!offer) || ($onehot(winner) && winner[3]));")
    assert check(hold + ";") == []
    assert check(f"({hold}) and ((offer || !offer) || (accept && available));") == []
    assert check(f"({hold}) and ({rule});", requirement + " Additionally require grant and available for each transfer.") == []


def test_release_boolean_escape_and_current_valid_do_not_meet_planned_obligations():
    release = {"CK-WAKE": {"description": "After reset release, busy must be low."}}
    with pytest.raises(PreflightError, match="launch=1"):
        check_bodies({"CK-WAKE": "@(posedge clk) ((launch || !busy) && ((!$rose(reset_n) || launch) || !busy));"},
                     "records.yaml", plan=release, outputs={"busy"}, data_inputs={"launch"})
    assert check_bodies({"CK-WAKE": "@(posedge clk) ((!$rose(reset_n) || !busy) && (launch || !busy));"},
                        "records.yaml", plan=release, outputs={"busy"}, data_inputs={"launch"}) == []
    route = {"CK-SRC": {"description": "检查器跟踪：交付（out_valid & out_ready）当拍，匹配请求（tag 记录值）。"}}
    with pytest.raises(PreflightError, match="captured identity"):
        check_bodies({"CK-SRC": "(accepted && tag && valid_b) |-> out_valid;"}, "records.yaml", plan=route)
    assert check_bodies({"CK-SRC": "(out_valid && out_ready) |-> (observed_tag == $past(tag));"},
                        "records.yaml", plan=route) == []


def test_new_response_contract_requires_history_when_restricting_input_by_dut_choice():
    description = {"CK-LEGAL": "No unsolicited responses; a command must have been accepted."}
    def check(body, claims=description):
        return check_bodies({"CK-LEGAL": body}, "records.yaml", assume_ids={"CK-LEGAL"}, data_inputs={"reply"},
                            internal_signals={"select_now"}, new_assume_descriptions=claims)
    with pytest.raises(PreflightError, match="earlier handshakes"):
        check("!reply || select_now;")
    assert check("!reply || select_now;", {"CK-LEGAL": "During isolation the response input is disabled."}) == []
    assert check("!reply || (|independent_outstanding);") == []
