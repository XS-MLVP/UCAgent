"""Host modes, real stage gates and persisted human-wait outcomes."""

import threading
import time

import pytest

from test_runtime_stage_control import build_runtime
from ucagent.control.commands import CommandSession
from ucagent.control.controller import ControlError
from ucagent.control.runtime.host import RuntimeHost
from ucagent.util.functions import load_ucagent_info


def make_host(tmp_path, **kwargs):
    """Attach the host to a real stage runtime without constructing a debugger."""
    runtime = build_runtime(tmp_path)
    runtime.agent.cfg.set_value("master_api", {"sync_workspace": {"on_exit": True}})
    host = RuntimeHost(runtime.agent, controller=runtime.control, operations=runtime.owner, **kwargs)
    return host, runtime


def wait_state(host, expected):
    """Observe asynchronous state with a bounded deadline and useful failure snapshot."""
    deadline = time.monotonic() + 3
    while host.snapshot()["execution"] != expected:
        assert time.monotonic() < deadline, host.snapshot()
        threading.Event().wait(0.01)


def test_waiting_human_persists_blocked_without_review_entry(tmp_path):
    """No input surface means a saved blocking reason and nonzero process outcome."""
    host, runtime = make_host(tmp_path, mode="once")
    host.start()
    accepted = host.registry.execute("continue", runtime.session).data
    assert host.operations.wait(accepted["id"], 2)["state"] == "succeeded"
    state = host.wait(3)
    assert state["instance"] == "closed", state
    assert state["task_outcome"] == "blocked" and state["exit_code"] == 2
    assert load_ucagent_info(str(tmp_path))["runtime"]["close_reason"] == "human_review_unavailable"
    with pytest.raises(ControlError):
        host.start()


@pytest.mark.parametrize("mode", ["console", "service", "master"])
def test_review_entry_keeps_host_alive_and_domain_gates_still_apply(tmp_path, mode):
    """Human review does not equate to Complete, and premature Exit cannot close the host."""
    host, runtime = make_host(tmp_path, mode=mode)
    host.attach_control("test-control")
    host.start()
    try:
        accepted = host.registry.execute("continue", runtime.session).data
        host.operations.wait(accepted["id"], 2)
        wait_state(host, "waiting_human")
        assert host.snapshot()["instance"] == "ready"
        assert runtime.manager.exit()["exit"] is False
        snapshot = runtime.control.stage_state()
        runtime.control.review_stage(0, snapshot["control_revision"], True, "Reviewed evidence")
        assert not runtime.manager.stages[0].is_completed()
        assert runtime.manager.exit()["exit"] is False
    finally:
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


@pytest.mark.parametrize("mode,exit_on_completion,closes", [
    ("once", False, True), ("service", False, False), ("master", False, False), ("console", True, True)])
def test_completed_task_and_instance_lifetime_are_independent(tmp_path, mode, exit_on_completion, closes):
    """A completed mission stays available unless its explicit mode requests closure."""
    host, runtime = make_host(tmp_path, mode=mode, exit_on_completion=exit_on_completion)
    host.start()
    host.complete_mission()
    if closes:
        assert host.wait(3)["instance"] == "closed"
    else:
        assert host.snapshot()["instance"] == "ready"
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"
    assert host.snapshot()["task_outcome"] == "completed"


def test_automatic_single_round_finishes_without_claiming_mission_complete(tmp_path):
    """One-round completion can end a process without passing unfinished stages."""
    host, runtime = make_host(tmp_path, mode="once")
    runtime.agent.one_loop = lambda message=None: None
    host.start()
    op = host.registry.execute("nr", CommandSession(tmp_path)).data
    host.operations.wait(op["id"], 2)
    assert host.wait(3)["instance"] == "closed"
    assert host.snapshot()["task_outcome"] is None


def test_single_round_human_wait_obeys_missing_control_policy(tmp_path):
    """Manual one-round execution also records a blocking human requirement explicitly."""
    host, runtime = make_host(tmp_path, mode="once")
    host.start()
    operation = host.registry.execute("nr", runtime.session).data
    assert host.operations.wait(operation["id"], 2)["result"]["reason"] == "waiting_human"
    assert host.wait(3)["exit_code"] == 2
