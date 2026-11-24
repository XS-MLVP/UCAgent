"""Real tool/Checker regressions for actionable pauses and operator recovery."""

import time
import pytest
from langchain_core.messages import AIMessage
from multi_agent_fakes import install_planner
from test_multi_agent import make_agent, stage, tool, finish
from ucagent.core.tools.uctool import to_mcp_tool


def issue(kind="capability", **extra):
    """Construct the current structured issue contract for actual tool invocation."""
    return {"kind": kind, "summary": "Preferred editor unavailable", "next_action": "Check available editors",
            **({"conditions": [{"kind": "capability_available", "value": "edit_file"}, {"kind": "file_writable", "value": "out/result.md"}]} if kind == "capability" else {}), **extra}


def test_missing_preferred_editor_does_not_freeze_worker(tmp_path):
    """An available task capability prevents an unsupported missing-tool pause."""
    agent = make_agent(tmp_path)
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        args = {"status": "needs_attention", "summary": "No apply_patch", "issue": issue()}
        assert to_mcp_tool(next(t for t in worker.test_tools if t.name == "SubmitTaskResult")).parameters
        rejected = tool(worker, "SubmitTaskResult", **args)
        assert rejected["error_code"] == "REQUIREMENTS_SATISFIED"
        assert "EditTextFile" in rejected["available_capabilities"]["edit_file"]
        assert worker.record.result is None
        tool(worker, "EditTextFile", path="out/result.md", content="Evidence")
        evidence = worker.get_current_tips()["recent_tool_evidence"]
        assert evidence[-1]["tool"] == "EditTextFile"
        assert "content" not in evidence[-1]
        tool(worker, "SubmitTaskResult", summary="Done")
    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "p", "tasks": [{"id": "t", "instruction": "Write"}]})
        assert finish(agent.multi_agent, "p")["plans"]["p"]["state"] == "completed"
    finally:
        agent._startup_cleanup.close()


def test_forged_evidence_rejected(tmp_path):
    """Only invocation receipts produced by the current worker may support a report."""
    agent = make_agent(tmp_path)
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        result = tool(worker, "SubmitTaskResult", status="needs_attention", summary="Claim",
                      issue=issue(evidence_ids=["invented"]))
        assert result["error_code"] == "UNKNOWN_EVIDENCE"
        tool(worker, "EditTextFile", path="out/result.md", content="Evidence")
        tool(worker, "SubmitTaskResult", summary="Done")
    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "p", "tasks": [{"id": "t", "instruction": "Write"}]})
        assert finish(agent.multi_agent, "p")["plans"]["p"]["state"] == "completed"
    finally:
        agent._startup_cleanup.close()


def test_chat_preserves_interruption_and_planning_budget(tmp_path, monkeypatch):
    """Repeated discussion remains possible after stage planning is exhausted."""
    agent = make_agent(tmp_path, limits={"planning_revisions": 1})
    planner = install_planner(agent, monkeypatch, lambda context, turn: AIMessage(content="Waiting for your decision."))
    service = agent.multi_agent
    service._planning_turns[id(agent.stage_manager.get_current_stage())] = 1
    service.set_issue("input", "Select a format", "Reply with the format")
    original = service.issue.copy()
    try:
        for _ in range(5):
            agent.custom_chat("What is happening?")
        assert len(planner.contexts) == 5
        assert service.planning_used() == 1
        assert service.issue == original and agent._need_human
        assert not service.records
    finally:
        agent._startup_cleanup.close()


def test_budget_pause_can_grant_and_resume_exactly_once(tmp_path, monkeypatch):
    """Explicit additions preserve usage and duplicate recovery cannot launch twice."""
    agent = make_agent(tmp_path, limits={"worker_tool_calls": 1})
    install_planner(agent, monkeypatch)
    service = agent.multi_agent
    starts = []
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        starts.append(worker)
        if len(starts) == 1:
            tool(worker, "CurrentTips")
        tool(worker, "EditTextFile", path="out/result.md", content="Evidence")
        tool(worker, "SubmitTaskResult", summary="Done")
    service.runner_factory = run
    try:
        agent.one_loop()
        assert service.issue["kind"] == "budget"
        assert service.issue["budget"]["dimension"] == "worker_tool_calls"
        old_calls = starts[0].record.calls
        request = {"issue_id": service.issue["id"], "action": "grant", "grant": {"worker_tool_calls": 10}}
        service.recover(request)
        service.recover(request)
        service.workflow_thread.join(5)
        assert service.workflow_state == "completed", service.status()
        assert len(starts) == 2
        assert starts[0].record.budget is starts[1].record.budget
        assert starts[1].record.calls > old_calls
        assert len(service.recovery_history) == 1
    finally:
        agent._startup_cleanup.close()


def test_chat_cannot_dispatch_and_review_cannot_be_bypassed(tmp_path, monkeypatch):
    """Read-only conversation and normal replies cannot bypass execution gates."""
    from test_multi_agent_supervisor import plan_message
    agent = make_agent(tmp_path, stages=[stage("review", need_human_check=True)])
    install_planner(agent, monkeypatch, lambda context, turn: plan_message(context, "forbidden", [{"id": "t", "instruction": "Write"}]))
    try:
        with pytest.raises(PermissionError, match="read-only"):
            agent.custom_chat("Explain")
        assert not agent.multi_agent.plans
        agent.multi_agent.set_issue("review", "Review required", "Review first")
        with pytest.raises(ValueError, match="human review"):
            agent.multi_agent.recover({"issue_id": agent.multi_agent.issue["id"], "message": "looks fine"})
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("kind", ["capability", "environment"])
def test_general_prerequisite_pause_rechecks_before_resume(tmp_path, monkeypatch, kind):
    """The same admission and recovery code handles any registered prerequisite."""
    agent = make_agent(tmp_path)
    service = agent.multi_agent
    install_planner(agent, monkeypatch)
    available = False
    service.requirement_checks.register("fixture_ready", lambda service, record, value: available)
    starts = []
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        starts.append(worker)
        if len(starts) == 1:
            tool(worker, "SubmitTaskResult", status="needs_attention", summary="A prerequisite is missing",
                 issue={"kind": kind, "summary": "Fixture prerequisite is missing", "next_action": "Prepare it and recheck",
                        "conditions": [{"kind": "fixture_ready", "value": "fixture"}]})
        else:
            tool(worker, "EditTextFile", path="out/result.md", content="evidence")
            tool(worker, "SubmitTaskResult", summary="Done")
    service.runner_factory = run
    try:
        agent.one_loop()
        assert service.issue["kind"] == kind
        assert service.issue["source"] == "sub_report"
        assert service.issue["checks"][0]["satisfied"] is False
        request = {"issue_id": service.issue["id"]}
        with pytest.raises(ValueError, match="Prerequisites"):
            service.recover(request)
        assert len(starts) == 1
        available = True
        service.recover(request)
        service.workflow_thread.join(5)
        assert service.workflow_state == "completed", service.status()
    finally:
        agent._startup_cleanup.close()


def test_repairable_report_returns_to_super_without_human_pause(tmp_path, monkeypatch):
    """A recoverable task report requests bounded replanning rather than user input."""
    agent = make_agent(tmp_path)
    install_planner(agent, monkeypatch)
    attempts = []
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        attempts.append(worker)
        if len(attempts) == 1:
            tool(worker, "SubmitTaskResult", status="needs_attention", summary="Revise the task",
                 issue={"kind": "repairable", "summary": "Need a revised implementation", "next_action": "Replan with the feedback"})
        else:
            tool(worker, "EditTextFile", path="out/result.md", content="evidence")
            tool(worker, "SubmitTaskResult", summary="Done")
    agent.multi_agent.runner_factory = run
    try:
        agent.one_loop()
        assert agent.multi_agent.workflow_state == "completed"
        assert not agent.multi_agent.issue and len(attempts) == 2
    finally:
        agent._startup_cleanup.close()


def test_subtree_pause_preserves_accepted_child_and_resumes_remaining_work(tmp_path, monkeypatch):
    """Resume from the uncompleted child while retaining accepted files and stage state."""
    agent = make_agent(tmp_path, stages=[stage("spec", stage=[
        stage("first", output_files=["out/first.txt"]), stage("second", output_files=["out/second.txt"])])])
    install_planner(agent, monkeypatch)
    calls = []
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        tips = worker.get_current_tips()
        calls.append(tips["stage_index"])
        if tips["stage_index"] == 0:
            tool(worker, "EditTextFile", path="out/first.txt", content="accepted evidence")
            tool(worker, "SetCurrentStageJournal", journal="First done")
            tool(worker, "CompleteSubStage", step_token=tips["step_token"])
            tool(worker, "SubmitTaskResult", status="needs_attention", summary="First accepted; second needs input",
                 issue={"kind": "input", "summary": "Choose the format", "next_action": "Specify the format"})
        else:
            assert (tmp_path / "out/first.txt").read_text() == "accepted evidence"
            tool(worker, "EditTextFile", path="out/second.txt", content="evidence")
            tool(worker, "SetCurrentStageJournal", journal="Second done")
            tool(worker, "CompleteSubStage", step_token=tips["step_token"])
            tool(worker, "SubmitTaskResult", summary="Both accepted")
    service = agent.multi_agent
    service.runner_factory = run
    try:
        agent.one_loop()
        assert agent.stage_manager.stages[0].is_completed()
        request = {"issue_id": service.issue["id"], "action": "reply", "message": "Text"}
        service.recover(request)
        service.workflow_thread.join(5)
        assert service.workflow_state == "completed", service.status()
        assert calls == [0, 1]
    finally:
        agent._startup_cleanup.close()


@pytest.mark.parametrize("interruptions", [1, 2])
def test_final_submission_is_recovered_without_reexecuting_completed_children(tmp_path, monkeypatch, interruptions):
    """A missing final submission is recovered under a fresh lease before acceptance."""
    agent = make_agent(tmp_path, stages=[stage("spec", stage=[stage("last", output_files=["out/result.md"])])])
    install_planner(agent, monkeypatch)
    starts = []
    def run(worker):
        """Exercise the delegated attempt through real scoped tools and acceptance gates."""
        starts.append(worker)
        tips = worker.get_current_tips()
        if len(starts) == 1:
            tool(worker, "EditTextFile", path="out/result.md", content="evidence")
            tool(worker, "SetCurrentStageJournal", journal="Completed the child")
            tool(worker, "CompleteSubStage", step_token=tips["step_token"])
        if len(starts) <= interruptions:
            worker.timeout()
        else:
            assert tips["scope_done"]
            tool(worker, "SubmitTaskResult", summary="Completed child evidence verified")
    service = agent.multi_agent
    service.runner_factory = run
    try:
        agent.one_loop()
        seen = set()
        for _ in range(interruptions):
            assert service.issue["kind"] == "execution", service.status()
            assert service.issue["category"] == "worker_timeout"
            assert service.issue["id"] not in seen
            seen.add(service.issue["id"])
            service.recover({"issue_id": service.issue["id"], "action": "resume"})
            service.workflow_thread.join(5)
        assert service.workflow_state == "completed", service.status()
        assert len(starts) == interruptions + 1
    finally:
        agent._startup_cleanup.close()


def test_modified_accepted_artifacts_require_revalidation(tmp_path, monkeypatch):
    """Changing accepted evidence cannot preserve a stale completion or review."""
    agent = make_agent(tmp_path, stages=[stage("spec", stage=[
        stage("first", output_files=["out/first.txt"]), stage("second", output_files=["out/second.txt"])])])
    install_planner(agent, monkeypatch)
    def run(worker):
        """Accept the first child and request input for the second."""
        tips = worker.get_current_tips()
        tool(worker, "EditTextFile", path="out/first.txt", content="accepted")
        tool(worker, "SetCurrentStageJournal", journal="First accepted")
        tool(worker, "CompleteSubStage", step_token=tips["step_token"])
        tool(worker, "SubmitTaskResult", status="needs_attention", summary="Need a decision",
             issue={"kind": "input", "summary": "Choose format", "next_action": "Reply"})
    service = agent.multi_agent
    service.runner_factory = run
    try:
        agent.one_loop()
        assert agent.stage_manager.stages[0].is_completed()
        (tmp_path / "out/first.txt").write_text("changed outside the worker")
        service.recover({"issue_id": service.issue["id"], "action": "reply", "message": "Use text"}, start=False)
        assert agent.stage_manager.stage_index == 0
        assert not agent.stage_manager.stages[0].is_completed()
        assert agent.stage_manager.stages[0].meta_get_journal() is None
    finally:
        agent._startup_cleanup.close()


def test_failed_chat_does_not_close_paused_runtime(tmp_path, monkeypatch):
    """A rejected discussion tool cannot turn a live paused workflow into terminal failure."""
    from ucagent.runtime.host import RuntimeHost
    from ucagent.runtime.control.commands import CommandSession
    from test_multi_agent_supervisor import plan_message
    agent = make_agent(tmp_path)
    install_planner(agent, monkeypatch, lambda context, turn: plan_message(context, "forbidden", [{"id": "t", "instruction": "Write"}]))
    host = RuntimeHost(agent, mode="once")
    host.attach_control("test")
    service = agent.multi_agent
    service.set_issue("input", "Choose format", "Reply with a format")
    host.start()
    try:
        session = CommandSession(tmp_path)
        operation = host.registry.execute('chat "Explain the pause"', session).data
        outcome = host.operations.wait(operation["id"], 5)
        assert outcome["state"] == "failed"
        deadline = time.monotonic() + 2
        while host.snapshot()["execution"] != "waiting_human" and time.monotonic() < deadline:
            time.sleep(.01)
        assert host.snapshot()["instance"] == "ready"
        assert service.issue["kind"] == "input"
        assert not service.records
    finally:
        host.request_shutdown()
        host.wait(5)



def test_recovery_start_failure_retains_grant_and_actionable_pause(tmp_path, monkeypatch):
    """A failed thread launch cannot lose recovery or duplicate an approved grant."""
    import threading
    agent = make_agent(tmp_path)
    install_planner(agent, monkeypatch)
    service = agent.multi_agent
    service.set_issue("budget", "Planning exhausted", "Add planning budget",
                      budget={"dimension": "planning_revisions", "used": 3, "limit": 3})
    def run(worker):
        """Produce real evidence after the execution service becomes available."""
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SubmitTaskResult", summary="Done")
    service.runner_factory = run
    request = {"issue_id": service.issue["id"], "action": "grant", "grant": {"planning_revisions": 2}}
    original_start = threading.Thread.start
    def fail_supervisor_start(thread):
        """Inject a runtime resource failure only at the supervisor launch boundary."""
        if thread.name == "ucagent-supervisor":
            raise RuntimeError("Execution service unavailable")
        return original_start(thread)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", fail_supervisor_start)
            with pytest.raises(RuntimeError, match="unavailable"):
                service.recover(request)
        assert service.issue["kind"] == "environment"
        assert service.workflow_thread is None
        assert service.supervisor_limit("planning_revisions") == 2
        assert service.recover(request)["duplicate"]
        service.recover({"issue_id": service.issue["id"]})
        service.workflow_thread.join(5)
        assert service.workflow_state == "completed", service.status()
    finally:
        agent._startup_cleanup.close()
