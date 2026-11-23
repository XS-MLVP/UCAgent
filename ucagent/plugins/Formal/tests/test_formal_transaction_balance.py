"""Exercise the planned transaction checker through a real managed proof."""

import json
import shutil
import time

import pytest
import yaml

from formal.data import FormalDataStore
from formal.execution import ACTIVE_RUNS, FormalExecution
from formal.tools import RunFormal, render_environment
from ucagent.util.config import Config


@pytest.mark.parametrize("guard, verdict", [(None, "FALSIFIED"), ("permit", "PROVEN")])
def test_same_cycle_response_requires_the_planned_exception(tmp_path, guard, verdict):
    """A visible command and response in the same sample may be illegal at zero balance."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    dut = tmp_path / "DUT"
    dut.mkdir()
    (dut / "DUT.sv").write_text(
        "module DUT(input clk, rst_n, req, take, permit, output ready, rsp);\n"
        "assign ready = take && permit; assign rsp = req && permit;\nendmodule\n"
    )
    out = tmp_path / "proof"
    out.mkdir()
    rule = dict(command_valid="req", command_ready="ready", response_valid="rsp", response_ready="take")
    if guard:
        rule["zero_cycle_when"] = guard
    ck = dict(id="CK-BALANCE", style="Seq", description="Response consumes a request", transaction_balance=[rule])
    records = {"dut": "DUT", "basic_info": {"clock_reset": {"clock_signal": "clk", "reset_signal": "rst_n"}},
               "spec": {"function_groups": [{"id": "FG-BALANCE", "functions": [
                   {"id": "FC-BALANCE", "check_points": [ck]}]}]}}
    (out / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    cfg = Config({"runtime_options": {"formal_batched_sva": True}})
    store = FormalDataStore(str(tmp_path), "proof", "DUT", cfg=cfg)
    assert store.update(data=None, **store.prepare("sva")["ready_update"])["status"] == "updated"
    execution = FormalExecution(str(tmp_path), "proof", "DUT", cfg)
    tool = RunFormal(str(tmp_path), "proof", "DUT", cfg)
    stage = tmp_path / ".ucagent/ucagent_info.json"
    stage.parent.mkdir()
    stage.write_text(json.dumps({"stage_index": 5}))
    run = tool.invoke({"action": "run", "scope": "selected", "fc_id": "FC-BALANCE"})
    batch = {"run_id": run["run_id"], "scope": "selected"}
    try:
        deadline = time.monotonic() + 25
        while run["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
            run = execution.status(wait_s=1, **batch)
        assert run["status"] == "COMPLETED", run
        assert run["counts"] == {verdict: 1}
        summary = tool.invoke({"action": "status", "wait_s": 0, **batch})
        assert not summary["full_complete"] and not execution.check()[0]
        progress = summary["fc_progress"]
        if guard:
            assert progress["current_fc"] is None and progress["reviewed"] == 1
        else:
            current = progress["current_fc"]
            review = current["needs_review"][0]
            trace = tool.invoke(review["trace_call"])
            assert trace["run_id"] == run["run_id"] and trace["property"] == review["property"]
            request = current["review_call"]
            request["reviews"][0].update(classification="RTL_BUG", reason="Same-cycle response violates the planned zero-balance rule.")
            assert tool.invoke(request)["current_fc"] is None
    finally:
        if run["status"] in ACTIVE_RUNS:
            execution.cancel(**batch)

    stage.write_text(json.dumps({"stage_index": 6}))
    full = tool.invoke({"action": "run"})
    try:
        deadline = time.monotonic() + 25
        while full["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
            full = execution.status(wait_s=1)
        assert full["status"] == "COMPLETED" and full["run_id"] != run["run_id"]
        assert full["full_complete"] and full["counts"] == {verdict: 1}
        assert execution.check()[0]
        if not guard:
            analysis = store.prepare("analysis")
            delta = analysis["items"][0]["full_vs_local"]
            assert delta["local_result"] == delta["full_result"] == "FALSIFIED"
            assert delta["trace_bytes"] in {"same", "different"}
            assert analysis["ready_update"]["data"]["fa_entries"][0]["resolution"] == ""
    finally:
        if full["status"] in ACTIVE_RUNS:
            execution.cancel()


@pytest.mark.parametrize("response_at, reuse, verdict", [
    (1, False, "PROVEN"),
    (3, False, "FALSIFIED"),
    (2, False, "FALSIFIED"),
    (2, True, "PROVEN"),
])
def test_internal_acceptance_checks_only_completed_handshakes(tmp_path, response_at, reuse, verdict):
    """A high ready without valid cannot retire a command; same-cycle reuse is explicit."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    dut = tmp_path / "DUT"
    dut.mkdir()
    (dut / "DUT.sv").write_text(f"""module DUT(input logic clk, rst_n, output logic busy);
      logic [1:0] age;
      always @(posedge clk) if (!rst_n) age <= 0; else if (age != 3) age <= age + 1'b1;
      wire cmd_valid = (age == 0) || (age == 2);
      wire cmd_ready = 1'b1;
      wire rsp_valid = (age == {response_at});
      wire rsp_ready = 1'b1;
      assign busy = cmd_valid;
    endmodule
    """)
    out = tmp_path / "proof"
    out.mkdir()
    roles = ("command_valid", "command_ready", "response_valid", "response_ready")
    signals = ("cmd_valid", "cmd_ready", "rsp_valid", "rsp_ready")
    rule = dict(zip(roles, signals), binding="internal", counter_bits=1, max_pending=1)
    if reuse:
        rule["reuse_on_response"] = True
    ck = dict(id="CK-LIMIT", style="Seq", description="At most one outstanding command", transaction_balance=[rule])
    records = {"dut": "DUT", "basic_info": {"clock_reset": {"clock_signal": "clk", "reset_signal": "rst_n"}},
               "spec": {"whitebox_signals": [f"logic {signal}" for signal in signals],
                        "function_groups": [{"id": "FG-CAP", "functions": [{"id": "FC-CAP", "check_points": [ck]}]}]}}
    (out / ".formal_records.yaml").write_text(yaml.safe_dump(records))
    cfg = Config({"runtime_options": {"formal_batched_sva": True}})
    store = FormalDataStore(str(tmp_path), "proof", "DUT", cfg=cfg)
    assert store.update(data=None, **store.prepare("sva")["ready_update"])["status"] == "updated"
    render_environment(str(tmp_path), "proof", "DUT")
    execution = FormalExecution(str(tmp_path), "proof", "DUT", cfg)
    run = execution.run(ck_ids=["CK-LIMIT"])
    batch = {"run_id": run["run_id"], "scope": "selected"}
    try:
        deadline = time.monotonic() + 25
        while run["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
            run = execution.status(wait_s=1, **batch)
        assert run["status"] == "COMPLETED", run
        assert run["counts"] == {verdict: 1}
    finally:
        if run["status"] in ACTIVE_RUNS:
            execution.cancel(**batch)


@pytest.mark.parametrize("zero_cycle", [True, False])
def test_external_response_credit_allows_delay_without_permitting_unrequested_offers(tmp_path, zero_cycle):
    """Check the public environment recipe using reachable/unreachable native Covers."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    rtl, out = tmp_path / "Sender", tmp_path / "proof"
    rtl.mkdir()
    out.mkdir()
    (rtl / "Sender.sv").write_text("""module Sender(input clk, rst_n, cmd_ready, rsp_valid,
      output cmd_valid, rsp_ready, output logic [2:0] age);
      always @(posedge clk) if (!rst_n) age <= 0; else if (!(&age)) age <= age+1'b1;
      assign cmd_valid=(age==1); assign rsp_ready=1'b1;
      endmodule
    """)
    rule = dict(binding="egress", command_valid="cmd_valid", command_ready="cmd_ready",
                response_valid="rsp_valid", response_ready="rsp_ready", counter_bits=2)
    if zero_cycle:
        rule["zero_cycle_when"] = "1'b1"
    assume = dict(id="CK-LEGAL", style="Assume", description="No unsolicited responses.", transaction_balance=[rule])
    reset = dict(id="CK-INIT", style="Assume", description="Starts in reset.", initial_reset=True,
                 sva_body="@(posedge clk) disable iff (1'b0) ucagent_initial_reset_sample |-> !rst_n;")
    goals = [dict(id="CK-"+name, style="Cover", description=name, sva_body=expr) for name, expr in [
        ("ORPHAN", "(age == 3'd0) && rsp_valid;"), ("DELAYED", "(age == 3'd4) && rsp_valid;"),
        ("SIMULTANEOUS", "(age == 3'd1) && cmd_valid && cmd_ready && rsp_valid;")]]
    records = {"dut": "Sender", "basic_info": {"clock_reset": {"clock_signal": "clk", "reset_signal": "rst_n",
               "reset_assertion": "sync", "reset_active_level": "low"}},
               "spec": {"function_groups": [{"id": "FG-REQ", "functions": [{"id": "FC-REQ", "check_points": [reset, assume, *goals]}]}]}}
    path = out / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(records))
    cfg = Config({"runtime_options": {"formal_batched_sva": True}})
    store = FormalDataStore(str(tmp_path), "proof", "Sender", cfg=cfg)
    update = store.prepare("sva", assumptions=True)["ready_update"]
    assert "uca_balance_CK_LEGAL_0_overflow ||" in update["bodies"]["CK-LEGAL"]
    store.update(data=None, **update)
    tool = RunFormal(str(tmp_path), "proof", "Sender", cfg)
    ex = FormalExecution(str(tmp_path), "proof", "Sender", cfg)
    r = tool.invoke({"action": "run"})
    try:
        deadline = time.monotonic() + 25
        while r["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
            r = ex.status(wait_s=1)
        result = {row["name"].split(".")[-1]: row["result"] for row in ex.inventory()["properties"]}
        assert result["C_CK_DELAYED"] == "COVER_REACHED", r
        assert result["C_CK_ORPHAN"] == "COVER_UNREACHABLE", r
        assert result["C_CK_SIMULTANEOUS"] == ("COVER_REACHED" if zero_cycle else "COVER_UNREACHABLE"), r
    finally:
        if r["status"] in ACTIVE_RUNS:
            ex.cancel()
