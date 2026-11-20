"""Acceptance of real Super planning, event-driven continuation and dynamic parallel work."""

import json
import threading

import pytest
from langchain_core.messages import AIMessage

from multi_agent_fakes import install_planner
from test_multi_agent import make_agent, stage, tool, finish


def plan_message(context, name, tasks, scope="auto"):
    """Ask the production graph to submit a plan with its current ownership token."""
    return AIMessage(content="Analyze and delegate.", tool_calls=[{
        "name": "SubAgentTool", "id": name, "args": {"plan_id": name, "scope": scope,
        "planning_token": context["planning_token"], "tasks": tasks}}])


def test_model_splits_dynamic_tasks_then_receives_results_without_polling(tmp_path, monkeypatch):
    """Super chooses a DAG without predeclared contracts, waits, and plans the next stage."""
    value = make_agent(tmp_path, max_workers=2, stages=[
        stage("analysis", output_files=[f"out/{i}.txt" for i in range(3)]),
        stage("report", output_files=["out/report.txt"])])
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    running = peak = 0
    def decide(context, turn):
        """Inspect authoritative results before producing dependent follow-up work."""
        if context["workflow_complete"]:
            assert context["previous_result"]["plans"]["report"]["state"] == "completed"
            return AIMessage(content="Verified analysis and report.")
        if context["stage_name"] == "analysis":
            assert context["task_contracts"] == {}
            return plan_message(context, "analysis", [
                {"id": str(i), "instruction": f"Analyze {i}", "role": "worker", "outputs": [f"out/{i}.txt"],
                 "depends_on": ["0", "1"] if i == 2 else [],
                 "inputs": ["out/0.txt", "out/1.txt"] if i == 2 else []} for i in range(3)], "task")
        assert context["previous_result"]["plans"]["analysis"]["state"] == "completed"
        assert len(context["previous_result"]["tasks"]) == 3
        assert context["user_instruction"] == "Analyze then report"
        return plan_message(context, "report", [{"id": "report", "instruction": "Write report"}])
    planner = install_planner(value, monkeypatch, decide)
    def run(worker):
        """Hold the first pair to prove model silence and actual bounded concurrency."""
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            if running == 2:
                entered.set()
        if worker.record.plan_id == "analysis":
            assert release.wait(5)
            if worker.record.spec.id == "2":
                assert all(value.multi_agent.records[f"analysis/{i}"].state == "verified" for i in (0, 1))
            path = worker.record.spec.outputs[0]
        else:
            path = "out/report.txt"
        tool(worker, "EditTextFile", path=path, content="actual evidence")
        tool(worker, "SubmitTaskResult", summary=f"Created {path}")
        with lock:
            running -= 1
    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.start_workflow("Analyze then report")
        assert entered.wait(4), json.dumps(value.multi_agent.status(), indent=2, default=str)
        assert len(planner.contexts) == 1
        assert value.get_tool_by_name("SubAgentTool").call_count == 1
        assert value.get_tool_by_name("WaitTasks").call_count == 0
        assert value.get_tool_by_name("StartWorkflow").invoke({})["workflow_state"] == "running"
        assert len(planner.contexts) == 1
        release.set()
        value.multi_agent.workflow_thread.join(5)
        assert value.multi_agent.workflow_state == "completed", json.dumps(value.multi_agent.status(), indent=2, default=str)
        assert len(planner.contexts) == 3
        assert value.get_tool_by_name("SubAgentTool").call_count == 2
        assert value.multi_agent.status()["metrics"]["worker_starts"] == 4
        assert peak == 2
    finally:
        release.set()
        value._startup_cleanup.close()


def test_failed_checker_feedback_returns_to_super_for_replanning(tmp_path, monkeypatch):
    """Worker success cannot skip the Checker; Super receives failure and repairs the same stage."""
    value = make_agent(tmp_path, limits={"task_max_attempts": 1})
    def decide(context, turn):
        """Revise the plan only after examining actual validation failure."""
        if context["workflow_complete"]:
            return AIMessage(content="Verified repair.")
        if turn == 2:
            previous = context["previous_result"]["plans"]["attempt-1"]
            assert previous["state"] == "failed" and not previous["validation"].get("complete")
            assert value.stage_manager.stage_index == 0
        return plan_message(context, f"attempt-{turn}", [{"id": "t", "instruction": "repair"}])
    planner = install_planner(value, monkeypatch, decide)
    def run(worker):
        """The first result deliberately misses the required artifact; the second creates it."""
        if worker.record.plan_id == "attempt-2":
            tool(worker, "EditTextFile", path="out/result.md", content="verified evidence")
        tool(worker, "SubmitTaskResult", summary="Reported work; Checker must decide")
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", json.dumps(value.multi_agent.status(), indent=2, default=str)
        assert len(planner.contexts) == 3
        records = list(value.multi_agent.records.values())
        assert records[0].budget is records[1].budget
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("kind", ["plain_text", "read_loop", "tool_budget", "failed_plans"])
def test_supervisor_nonprogress_is_bounded(tmp_path, monkeypatch, kind):
    """No plan, repeated reads and repeatedly failed plans cannot create an endless loop."""
    value = make_agent(tmp_path, limits={"supervisor_model_rounds": 2,
        "supervisor_tool_calls": 1 if kind == "tool_budget" else 20,
        "planning_revisions": 2, "task_max_attempts": 1})
    def decide(context, turn):
        """Exercise each budget through genuine graph/model and tool dispatch."""
        if kind == "plain_text":
            return AIMessage(content="I will work on it.")
        if kind in {"read_loop", "tool_budget"}:
            return AIMessage(content="", tool_calls=[{"name": "CurrentTips", "args": {}, "id": f"read-{turn}"}])
        return plan_message(context, f"failure-{turn}", [{"id": "t", "instruction": "fail"}])
    planner = install_planner(value, monkeypatch, decide)
    def run(worker):
        """Leave the required artifact absent so the final stage gate fails."""
        tool(worker, "SubmitTaskResult", summary="No artifact created")
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "failed", value.multi_agent.status()
        assert len(planner.contexts) <= 2
        assert not value.stage_manager.stages[0].is_completed()
        errors = [e.get("error", "") for e in value.multi_agent.status()["events"]]
        assert any("without SubAgentTool" in e or "budget" in e or "revisions exhausted" in e for e in errors)
    finally:
        value._startup_cleanup.close()


def test_pause_request_waits_for_user_then_resumes_planning(tmp_path, monkeypatch):
    """Super can ask for a decision without dispatching work or bypassing a stage gate."""
    value = make_agent(tmp_path)
    def decide(context, turn):
        """Pause first, then consume the user's clarification in the next planning context."""
        if turn == 1:
            return AIMessage(content="", tool_calls=[{"name": "PauseWorkflow", "id": "pause", "args": {
                "reason": "Choose the output format", "planning_token": context["planning_token"]}}])
        if context["workflow_complete"]:
            return AIMessage(content="Verified output.")
        assert context["user_instruction"] == "Use Markdown"
        return plan_message(context, "clarified", [{"id": "t", "instruction": "Write Markdown"}])
    planner = install_planner(value, monkeypatch, decide)
    def run(worker):
        """Satisfy the original stage after user clarification."""
        tool(worker, "EditTextFile", path="out/result.md", content="Markdown evidence")
        tool(worker, "SubmitTaskResult", summary="Written")
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "waiting_human"
        assert not value.multi_agent.records and len(planner.contexts) == 1
        value.multi_agent.start_workflow("Use Markdown")
        value.multi_agent.workflow_thread.join(4)
        assert value.multi_agent.workflow_state == "completed", json.dumps(value.multi_agent.status(), indent=2, default=str)
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("action", ["pause", "timeout"])
def test_inflight_planner_retains_ownership_and_cannot_submit_late(tmp_path, monkeypatch, action):
    """A non-interruptible model call keeps ownership; its late plan never starts a worker."""
    value = make_agent(tmp_path, limits={"supervisor_timeout_seconds": 0.1 if action == "timeout" else 5})
    entered, release = threading.Event(), threading.Event()
    def decide(context, turn):
        """Represent a provider that returns only after cancellation or deadline expiry."""
        entered.set()
        assert release.wait(4)
        return plan_message(context, "late", [{"id": "t", "instruction": "Must not run"}])
    install_planner(value, monkeypatch, decide)
    try:
        value.multi_agent.start_workflow()
        assert entered.wait(3)
        if action == "pause":
            value.set_break(True)
        else:
            threading.Event().wait(0.15)
        assert value.multi_agent.has_active()
        release.set()
        value.multi_agent.workflow_thread.join(4)
        assert value.multi_agent.workflow_state in {"paused", "failed"}
        assert not value.multi_agent.records
    finally:
        release.set()
        value._startup_cleanup.close()


def test_dynamic_split_cannot_drop_configured_output_rules(tmp_path):
    """Omitting a named contract cannot bypass workflow-authored content or role constraints."""
    value = make_agent(tmp_path, stages=[stage("rules", output_files=["out/result.md"])],
        task_contracts={"required": {"rules": [{"path": "out/result.md", "contains": ["required-evidence"]}]}},
        limits={"task_max_attempts": 1})
    def run(worker):
        """Write a real but semantically invalid artifact through the managed tools."""
        tool(worker, "EditTextFile", path="out/result.md", content="wrong")
        tool(worker, "SubmitTaskResult", summary="Written")
    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.submit({"plan_id": "omit", "scope": "task", "tasks": [
            {"id": "t", "instruction": "write", "outputs": ["out/result.md"]}]})
        result = finish(value.multi_agent, "omit")
        assert result["plans"]["omit"]["state"] == "failed"
        assert "missing required text" in result["tasks"][0]["error"]
        assert not value.stage_manager.stages[0].is_completed()
    finally:
        value._startup_cleanup.close()


def test_blank_super_fails_explicitly_without_automatic_fallback(tmp_path):
    """A status-only server never pretends that fixed framework dispatch is model planning."""
    value = make_agent(tmp_path)
    try:
        with pytest.raises(ValueError, match="non-blank"):
            value.get_tool_by_name("StartWorkflow").invoke({})
        value.one_loop()
        assert value.multi_agent.workflow_state == "failed"
        assert not value.multi_agent.plans
    finally:
        value._startup_cleanup.close()


def test_rejected_plan_can_be_corrected_in_same_bounded_model_turn(tmp_path, monkeypatch):
    """Admission returns actionable feedback without starting an invalid worker."""
    value = make_agent(tmp_path)
    def decide(context, turn):
        """Propose an unknown role, then correct it using the unchanged stage token."""
        if context["workflow_complete"]:
            return AIMessage(content="Verified corrected plan.")
        return plan_message(context, "corrected", [{"id": "t", "instruction": "work",
                                                    "role": "missing" if turn == 1 else "worker"}])
    planner = install_planner(value, monkeypatch, decide)
    def run(worker):
        """Only the corrected authorized plan can reach this runner."""
        assert worker.record.spec.role == "worker"
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SubmitTaskResult", summary="Corrected")
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(planner.contexts) == 3
        assert len(value.multi_agent.records) == 1
        assert value.get_tool_by_name("SubAgentTool").call_count == 2
    finally:
        value._startup_cleanup.close()


def test_successive_child_stages_do_not_exhaust_failure_revisions(tmp_path, monkeypatch):
    """A Super may deliberately use separate stage scopes for more than three children."""
    value = make_agent(tmp_path, stages=[stage("group", stage=[
        stage(f"child{i}", output_files=[f"out/{i}.txt"]) for i in range(5)])])
    def decide(context, turn):
        """Choose stage scope explicitly so each genuine stage progress gets a new budget."""
        if context["workflow_complete"]:
            return AIMessage(content="Five stages passed.")
        message = plan_message(context, f"stage-{turn}", [{"id": "t", "instruction": "work"}], "stage")
        message.tool_calls[0]["args"]["scope_reason"] = "Deliberate per-step review; each worker has stage gates."
        return message
    install_planner(value, monkeypatch, decide)
    def run(worker):
        """Write only the current child's output before handing back ownership."""
        path = f"out/{worker.stage_manager.stage_index}.txt"
        tool(worker, "EditTextFile", path=path, content="evidence")
        tool(worker, "SubmitTaskResult", summary=path)
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(value.multi_agent.plans) == 5
    finally:
        value._startup_cleanup.close()


def test_cancelled_task_does_not_get_automatically_replanned(tmp_path, monkeypatch):
    """An operator cancellation pauses the orchestration loop instead of spending more model turns."""
    value = make_agent(tmp_path)
    entered, release = threading.Event(), threading.Event()
    planner = install_planner(value, monkeypatch)
    def run(worker):
        """Hold a worker until cancellation has arrived and keep its slot until it exits."""
        entered.set()
        assert release.wait(4)
    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.start_workflow()
        assert entered.wait(3)
        value.multi_agent.cancel("plan-1")
        assert value.multi_agent.status()["running"] == 1
        release.set()
        value.multi_agent.workflow_thread.join(4)
        assert value.multi_agent.workflow_state == "paused"
        assert len(planner.contexts) == 1
        assert value.is_break()
    finally:
        release.set()
        value._startup_cleanup.close()


def test_new_multi_agent_modules_are_loaded_from_target_repo_only():
    """The implementation imports no code from the sibling SubAgent project."""
    import ast
    import inspect
    from pathlib import Path
    import ucagent.core.tools.delegation as delegation
    import ucagent.core.multi_agent.service as service
    root = Path(__file__).resolve().parents[1]
    assert Path(inspect.getfile(delegation)).resolve() == root / "ucagent/core/tools/delegation.py"
    assert Path(inspect.getfile(service)).resolve() == root / "ucagent/core/multi_agent/service.py"
    for source in [root / "ucagent/core/tools/delegation.py", *(root / "ucagent/core/multi_agent").glob("*.py")]:
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                assert all("subagent" not in alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert "subagent" not in (node.module or "").lower()


def test_super_and_worker_both_use_real_independent_langchain_graphs(tmp_path, monkeypatch):
    """Exercise the full production loop with scripted providers and no substituted worker runner."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    import ucagent.core.backends.langchain.agent as backend_module
    class BoundModel(FakeMessagesListChatModel):
        """Select deterministic responses from each graph's actual capability set."""
        def bind_tools(self, tools, **kwargs):
            """Produce a plan on the Super graph and business tool calls only on the worker graph."""
            names = {item.name for item in tools}
            if "SubAgentTool" in names:
                self.responses = [AIMessage(content="", tool_calls=[{"name": "SubAgentTool", "id": "plan",
                    "args": {"plan_id": "real-graphs", "tasks": [{"id": "work", "instruction": "Write evidence"}]}}]),
                    AIMessage(content="Verified complete.")]
            else:
                assert "EditTextFile" in names and "Complete" in names
                assert not {"GoToStage", "Exit", "SubAgentTool"} & names
                self.responses = [AIMessage(content="", tool_calls=[{"name": "EditTextFile", "id": "write",
                    "args": {"path": "out/result.md", "content": "real graph evidence"}}]),
                    AIMessage(content="", tool_calls=[{"name": "SubmitTaskResult", "id": "submit",
                    "args": {"summary": "Written evidence"}}])]
            return self
        def get_num_tokens_from_messages(self, messages, tools=None):
            """Avoid network tokenizer downloads for the offline provider fixture."""
            return 20
    models = []
    def factory(*args, **kwargs):
        """Allocate genuinely different Super, worker and summary model instances."""
        model = BoundModel(responses=[AIMessage(content="unbound")])
        models.append(model)
        return model
    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    value = make_agent(tmp_path, config_overrides={"backend.key_name": "langchain"})
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert (tmp_path / "out/result.md").read_text() == "real graph evidence"
        assert len(models) == 4 and len({id(model) for model in models}) == 4
        assert value.get_tool_by_name("SubAgentTool").call_count == 1
        assert value.multi_agent.records["real-graphs/work"].rounds == 2
        assert value.backend._stat_msg_count_ai == 2
    finally:
        value._startup_cleanup.close()


def test_background_super_owns_model_slot_and_cancel_can_resume(tmp_path, monkeypatch):
    """Runtime rejects a second planner while waiting; explicit resume clears cancellation."""
    from ucagent.runtime.host import RuntimeHost
    from ucagent.runtime.control.controller import ControlError
    from ucagent.runtime.control.commands import CommandSession
    value = make_agent(tmp_path)
    entered, release = threading.Event(), threading.Event()
    planner = install_planner(value, monkeypatch)
    def run(worker):
        """Cancel the first scope and complete the freshly authorized second plan."""
        if worker.record.plan_id == "plan-1":
            entered.set()
            assert release.wait(5)
            return
        tool(worker, "EditTextFile", path="out/result.md", content="resumed evidence")
        tool(worker, "SubmitTaskResult", summary="Resumed")
    value.multi_agent.runner_factory = run
    host = RuntimeHost(value, mode="service")
    host.start()
    try:
        value.multi_agent.start_workflow()
        assert entered.wait(3)
        session = CommandSession(tmp_path)
        with pytest.raises(ControlError, match="managed Super"):
            host.registry.execute("continue", session)
        value.multi_agent.cancel("plan-1")
        release.set()
        value.multi_agent.workflow_thread.join(4)
        assert value.multi_agent.workflow_state == "paused"
        operation = host.registry.execute("continue", session).data
        outcome = host.operations.wait(operation["id"], 5)
        assert outcome["state"] == "succeeded", outcome
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(planner.contexts) == 3
    finally:
        release.set()
        host.request_shutdown()
        assert host.wait(5)["instance"] == "closed"


def test_final_child_without_task_submission_cannot_complete_workflow(tmp_path, monkeypatch):
    """Exhausting the stage list does not override a missing final worker submission."""
    value = make_agent(tmp_path, stages=[stage("group", stage=[stage("last", output_files=["out/last.txt"])])],
                       limits={"task_max_attempts": 1})
    planner = install_planner(value, monkeypatch)

    def run(worker):
        """Complete the final child, then hit the task deadline before submitting."""
        tips = worker.get_current_tips()
        tool(worker, "EditTextFile", path="out/last.txt", content="evidence")
        tool(worker, "SetCurrentStageJournal", journal="Produced the child output")
        result = tool(worker, "CompleteSubStage", step_token=tips["step_token"])
        assert result["validation"]["complete"] and result["scope_done"]
        worker.timeout()

    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.stage_manager.get_current_stage() is None
        assert value.multi_agent.workflow_state == "failed"
        assert len(planner.contexts) == 1
        assert not next(iter(value.multi_agent.plans.values()))["validation"]["complete"]
    finally:
        value._startup_cleanup.close()
