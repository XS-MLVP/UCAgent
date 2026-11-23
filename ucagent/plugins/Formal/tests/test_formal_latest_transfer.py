"""Exercise the public latest-value observer on an independent tagged channel."""

import copy
import shutil
import time

import pytest
import yaml

from formal.execution import ACTIVE_RUNS, FormalExecution
from formal.tools import FormalData, RunFormal, render_environment
from ucagent.util.config import Config


@pytest.fixture
def channel(tmp_path):
    root = tmp_path
    rtl, out = root / "Channel", root / "proof"
    rtl.mkdir()
    out.mkdir()
    (rtl / "Channel.sv").write_text("""module Channel(input clk, rst_n, req, accept, take, swap,
        input [1:0] new_tag, output [1:0] response_tag, output response);
      logic [1:0] saved;
      logic valid;
      always @(posedge clk) begin
        if (!rst_n) begin saved <= 0; valid <= 0; end
        else if (req && accept) begin saved <= new_tag; valid <= 1; end
      end
      assign response = valid;
      assign response_tag = swap ? ~saved : saved;
    endmodule
    """)
    ck = {"id": "CK-TAG", "style": "Seq", "description": "Delivery must match the latest captured tag."}
    init = {"id": "CK-RESET", "style": "Assume", "description": "Reset starts asserted.",
            "initial_reset": True,
            "sva_body": "@(posedge clk) disable iff (1'b0) ucagent_initial_reset_sample |-> !rst_n;"}
    records = {"dut": "Channel", "basic_info": {"clock_reset": {"clock_signal": "clk", "reset_signal": "rst_n",
                "reset_active_level": "low", "reset_assertion": "sync"}},
               "spec": {"function_groups": [{"id": "FG-TAG", "functions": [
                   {"id": "FC-TAG", "check_points": [init, ck]}]}]}}
    path = out / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(records))
    cfg = Config({"runtime_options": {"formal_batched_sva": True}})
    tool = FormalData(str(root), "proof", "Channel", cfg=cfg)
    rule = dict(capture_valid="req", capture_ready="accept", captured="new_tag",
                delivery_valid="response", delivery_ready="take", observed="response_tag",
                simultaneous="previous", reset_assertion="sync")
    return root, path, cfg, tool, {"action": "draft_latest_transfer", "ck_id": "CK-TAG", "rule": rule}


def test_draft_latest_transfer_validates_bindings_and_renders_atomically(channel):
    root, path, _, tool, request = channel
    original = path.read_bytes()
    for edit in [dict(observed="take"), dict(capture_ready="missing"), dict(reset_assertion="async"),
                 dict(observed="new_tag"), dict(observed=[{"valid": "req", "ready": "accept"}])]:
        invalid = {**request, "rule": {**request["rule"], **edit}}
        assert tool.invoke({"request": invalid})["status"] == "error"
    assert path.read_bytes() == original
    for priority in ("previous", "current"):
        request["rule"]["simultaneous"] = priority
        result = tool.invoke({"request": request})["ready_update"]
        body = result["bodies"]["CK-TAG"]
        assert ("? (response_tag == new_tag)" in body) == (priority == "current")
    assert tool.invoke({"request": result})["status"] == "updated"
    render_environment(str(root), "proof", "Channel")
    generated = (path.parent / "tests/Channel_checker.sv").read_text()
    assert "always @(posedge clk) begin" in generated
    assert "uca_latest_CK_TAG_value <= new_tag;" in generated
    assert body in generated


@pytest.mark.parametrize("observed, expression", [
    ([{"valid": "req", "ready": "take"}, {"valid": "response", "ready": "take"}], "{(response && take), (req && take)}"),
    ({"valid_vector": "lane_v", "ready_vector": "lane_r"}, "(lane_v & lane_r)"),
])
def test_latest_transfer_lane_comparison_uses_explicit_bit_order(channel, observed, expression):
    root, path, _, tool, request = channel
    request = copy.deepcopy(request)
    rtl = root / "Channel/Channel.sv"
    rtl.write_text(rtl.read_text().replace("input [1:0] new_tag", "input [1:0] lane_v, lane_r, new_tag"))
    request["rule"]["observed"] = observed
    result = tool.invoke({"request": request})["ready_update"]
    assert expression in result["bodies"]["CK-TAG"]
    assert tool.invoke({"request": result})["status"] == "updated"
    render_environment(str(root), "proof", "Channel")
    assert "uca_latest_CK_TAG_value" in (path.parent / "tests/Channel_checker.sv").read_text()


@pytest.mark.parametrize("corrupt, verdict", [(False, "PROVEN"), (True, "FALSIFIED")])
def test_native_delayed_tag_keeps_real_mismatch_failing(channel, corrupt, verdict):
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC unavailable")
    root, _, cfg, tool, request = channel
    if not corrupt:
        rtl = root / "Channel/Channel.sv"
        rtl.write_text(rtl.read_text().replace("swap ? ~saved : saved", "saved"))
    update = tool.invoke({"request": request})["ready_update"]
    assert tool.invoke({"request": update})["status"] == "updated"
    execution = FormalExecution(str(root), "proof", "Channel", cfg)
    run = RunFormal(str(root), "proof", "Channel", cfg).invoke({"action": "run"})
    try:
        deadline = time.monotonic() + 25
        while run["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
            run = execution.status(wait_s=1)
        assert run["status"] == "COMPLETED", run
        assert run["counts"] == {verdict: 1}
    finally:
        if run["status"] in ACTIVE_RUNS:
            execution.cancel()
