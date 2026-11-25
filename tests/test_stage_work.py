"""Exercise independent work across multiple model rounds in one UCA operation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_runtime_stage_control import build_runtime
from ucagent.core.stage.vmanager import ToolStageWork


@pytest.fixture
def work_runtime(tmp_path):
    runtime = build_runtime(tmp_path, autonomous=True)
    runtime.agent._max_stalled_rounds = 2
    runtime.agent._reset_stalled_rounds = Mock()
    runtime.agent.set_continue_msg = Mock()
    yield runtime
    assert runtime.owner.close(3)["closed"]


def test_one_operation_does_ai_work_before_human_input(work_runtime):
    r = work_runtime
    manager = r.manager
    work = ToolStageWork().set_function(manager.tool_stage_work)
    original = manager.stage_index

    def round_hook():
        step = r.agent.invoke_round
        if step == 0:
            work.invoke({"action": "human", "item_id": "missing-contract", "detail": "Design owner: supply spec R1", "evidence": "Spec R1 is absent"})
            for name in ("review-run", "check-wave"):
                work.invoke({"action": "ready", "item_id": name, "detail": "Verify " + name, "evidence": "run-a"})
        elif step in (1, 2):
            name = ("review-run", "check-wave")[step - 1]
            assert name in r.agent.set_continue_msg.call_args.args[0]
            work.invoke({"action": "done", "item_id": name, "evidence": "checked evidence for " + name})
        elif step == 3:
            work.invoke({"action": "review", "evidence": "Compared open obligations and run-a; only R1 needs the owner"})
        manager.last_check_info = {"check_pass": False, "failure_summary": {"stage_index": original, "error_code": "GAP"}}
        manager.validation_revision += 1
        r.agent.invoke_round += 1

    r.agent.one_loop = round_hook
    r.agent._update_stalled_rounds = lambda *_: r.agent.invoke_round >= 2
    op = r.owner.execute("continue", {}, r.session)
    result = r.owner.wait(op["id"], 3)
    assert result["state"] == "succeeded", result
    assert result["result"] == {"reason": "paused", "stop_reason": "human_input_required", "invoke_round": 4}
    assert len(r.owner.list()) == 1 and manager.stage_index == original
    assert not manager.get_current_stage().is_completed() and not r.agent._need_human
    view = manager.stage_work.public(manager._stage_work_view())
    assert not view["ready"] and view["reviewed"]
    assert [row["id"] for row in view["human"]] == ["missing-contract"]
    assert (manager.stage_work.root / "00.json").is_file()


def test_stalled_item_does_not_block_next_and_is_not_human(work_runtime):
    r = work_runtime
    manager = r.manager
    work = manager.stage_work
    index = manager.stage_index
    for item in ("unproductive", "next-action"):
        work.update(manager.stages, index, "ready", item, "Check evidence", "run-a")

    def round_hook():
        calls = r.agent.set_continue_msg.call_args_list
        if (calls and "next-action" in calls[-1].args[0]
                and any(item["id"] == "next-action" for item in manager._stage_work_view()["ready"])):
            work.update(manager.stages, index, "done", "next-action", "", "waveform b")
        r.agent.invoke_round += 1

    r.agent.one_loop = round_hook
    op = r.owner.execute("continue", {}, r.session)
    res = r.owner.wait(op["id"], 3)
    assert res["state"] == "succeeded", res
    assert res["result"]["stop_reason"] == "checker_stall", res
    view = manager._stage_work_view()
    assert not view["human"] and not view["ready"]
    assert [i["id"] for i in view["stalled"]] == ["unproductive"]
    with pytest.raises(ValueError, match="Unresolved"):
        work.update(manager.stages, index, "review", "", "", "not enough")


def test_delivery_cannot_exit_before_review(work_runtime):
    manager = work_runtime.manager
    manager.stage_index = len(manager.stages)
    assert not manager.exit()["exit"]
    manager.stage_work.update(manager.stages, manager.stage_index, "review", "", "", "reviewed the report and signed runs")
    assert manager.exit()["exit"]


def test_delivery_exit_cannot_bypass_workflow_evidence(work_runtime):
    """Reproduce the distinct completed-stage exit path with omitted work."""
    manager = work_runtime.manager
    manager.stage_index = len(manager.stages)
    manager.stage_work.update(manager.stages, manager.stage_index, "review", "", "", "Registered report reviewed")
    decision = Mock(side_effect=["Signed report still lists an independent coverage check", None])
    manager.runtime_hooks = [SimpleNamespace(stage_work_handoff_blocker=decision)]
    result = manager.exit()
    assert not result["exit"] and "independent coverage check" in result["message"]
    assert manager.exit()["exit"]
    assert decision.call_count == 2


def _checked_inventory(manager):
    """Set up a handoff candidate without asserting that its evidence is current."""
    work = manager.stage_work
    index = manager.stage_index
    work.update(manager.stages, index, "human", "spec", "Owner must supply R1", "R1 is absent")
    work.update(manager.stages, index, "review", "", "", "Reviewed the registered inventory")
    manager.last_check_info = {"check_pass": False, "failure_summary": {"stage_index": index, "error_code": "GAP"}}


def test_workflow_veto_checks_again_inside_the_same_operation(work_runtime):
    r = work_runtime
    _checked_inventory(r.manager)
    observed = []

    def check(**_):
        """Expose a current diagnostic through the actual Checker and manager."""
        return False, {"error_code": "GAP", "error": "Evidence remains open",
                       "issue_kind": "repairable" if not r.agent.invoke_round else "external_dependency",
                       "next_action": "Check current evidence"}

    r.gate.do_check = check

    def consult(manager):
        kind = manager.last_check_info["failure_summary"]["issue_kind"]
        observed.append(kind)
        if kind == "repairable":
            return "Audit the current signed evidence"
        return None

    decision = Mock(side_effect=consult)
    r.manager.runtime_hooks = [SimpleNamespace(stage_work_handoff_blocker=decision)]

    def next_round():
        if r.agent.invoke_round:
            assert r.agent.set_continue_msg.call_args.args == ("Audit the current signed evidence",)
        assert r.manager.check(2)["check_pass"] is False
        r.agent.invoke_round += 1

    r.agent.one_loop = next_round
    op = r.owner.execute("continue", {}, r.session)
    result = r.owner.wait(op["id"], 3)
    assert result["state"] == "succeeded", result
    assert result["result"] == {"reason": "paused", "stop_reason": "human_input_required", "invoke_round": 2}
    assert len(r.owner.list()) == 1
    assert decision.call_count == 2
    decision.assert_called_with(r.manager)
    assert observed == ["repairable", "external_dependency"]
    assert r.manager.last_check_info["check_pass"] is False
    assert not r.manager.get_current_stage().is_completed()


@pytest.mark.parametrize("bad_result", [False, " ", RuntimeError("unreadable evidence")])
def test_veto_failure_is_bounded_and_never_waits_for_human(work_runtime, bad_result):
    r = work_runtime
    _checked_inventory(r.manager)
    if isinstance(bad_result, Exception):
        decision = Mock(side_effect=bad_result)
    else:
        decision = Mock(return_value=bad_result)
    r.manager.runtime_hooks = [SimpleNamespace(stage_work_handoff_blocker=decision)]

    def next_round():
        r.agent.invoke_round += 1

    r.agent.one_loop = next_round
    op = r.owner.execute("continue", {}, r.session)
    result = r.owner.wait(op["id"], 3)
    assert result["state"] == "succeeded", result
    assert result["result"] == {"reason": "paused", "stop_reason": "checker_stall", "invoke_round": 6}
    assert decision.call_count == 6
    assert "could not verify the handoff evidence" in r.agent.set_continue_msg.call_args.args[0]
