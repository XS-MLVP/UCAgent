"""H2 real Super tool decisions after authoritative business stage acceptance."""

import time
import pytest
from langchain_core.messages import AIMessage

from multi_agent_fakes import install_planner
from test_multi_agent import make_agent, tool
from test_workflow_contracts import catalog
from ucagent.core.tools.delegation import supervisor_tools
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.core.workflow.chain import WorkflowChain, HandoffDecision
from ucagent.core.workflow.contracts import NextWorkflow


def setup_agent(tmp_path, monkeypatch, action="next"):
    """Attach a chain to real stage/worker tools and a deterministic Super provider."""
    value = make_agent(tmp_path)
    chain = WorkflowChain(catalog(tmp_path), "fixture:a", tmp_path, goal="Produce the final result")
    value.workflow_handoff_settings = chain.settings
    value.multi_agent.handoff = HandoffDecision(chain, chain.current)
    value.test_tools = supervisor_tools(value)

    def decide(context, turn):
        """Select only through real planning and handoff tools, never through runtime defaults."""
        if context.get("phase") == "handoff":
            if action == "text":
                return AIMessage(content="I suggest B")
            args = {"transition_token": context["handoff"]["transition_token"],
                    "reason": "Advance the goal", "summary": "A accepted"}
            name = "CompleteWorkflowChain"
            if action == "next":
                name = "RequestNextWorkflow"
                args.update(workflow_ref="fixture:b", inputs={"inputs/a.json": "out/result.md"})
            if action == "pause":
                name, args = "PauseWorkflow", {"reason": "Need a decision", "planning_token": context["planning_token"]}
        else:
            name, args = "SubAgentTool", {"plan_id": f"plan-{turn}", "planning_token": context["planning_token"],
                "tasks": [{"id": "write", "instruction": "Write evidence"}]}
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{turn}"}])

    planner = install_planner(value, monkeypatch, decide)

    def worker_run(worker):
        """Pass the real stage checker and ensure workers have no handoff authority."""
        assert not {"RequestNextWorkflow", "CompleteWorkflowChain"} & {t.name for t in worker.test_tools}
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SubmitTaskResult", summary="Evidence created")

    value.multi_agent.runner_factory = worker_run
    return value, chain, planner


@pytest.mark.parametrize("action", ["next", "complete", "pause", "text"])
def test_handoff_is_explicit_and_does_not_exit_instance(tmp_path, monkeypatch, action):
    """After business completion only a tool decision can queue a peer or end the chain."""
    agent, chain, planner = setup_agent(tmp_path, monkeypatch, action)
    try:
        agent.one_loop()
        assert agent.stage_manager._compute_all_completed()
        assert chain.current["business_status"] == "completed"
        assert agent._is_exit is False
        transition = chain.current["transition"]
        if action in {"next", "complete"}:
            assert transition["kind"] == action
            assert transition["status"] == "accepted"
            assert len(chain.state["runs"]) == 1
        else:
            assert transition is None
            assert chain.state["status"] == "paused"
        assert any(c["phase"] == "handoff" for c in planner.contexts)
        for entry in agent.test_tools:
            assert to_mcp_tool(entry).parameters is not None
    finally:
        agent._startup_cleanup.close()


def test_no_handoff_before_real_acceptance(tmp_path, monkeypatch):
    """A failed stage or stale token cannot acquire workflow switching authority."""
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    try:
        with pytest.raises(PermissionError):
            agent.multi_agent.request_next_workflow(workflow_ref="fixture:b", reason="skip", summary="skip",
                inputs={"inputs/a.json": "out/result.md"}, transition_token="stale")
        agent.multi_agent.runner_factory = lambda worker: tool(worker, "SubmitTaskResult", summary="No artifact")
        agent.one_loop()
        assert chain.current["business_status"] == "pending"
        assert chain.current["transition"] is None
        assert not agent.stage_manager._compute_all_completed()
    finally:
        agent._startup_cleanup.close()


def test_decision_replay_conflict_and_budget(tmp_path):
    """One token admits one request and retries retain the source run's startup budget."""
    chain = WorkflowChain(catalog(tmp_path), "fixture:a", tmp_path)
    run = chain.current
    run["business_status"] = "completed"
    (tmp_path / "out").mkdir()
    (tmp_path / "out/a.json").write_text("data")
    HandoffDecision(chain, run).record_artifacts()
    request = NextWorkflow(workflow_ref="fixture:b", reason="Continue", summary="A",
                           inputs={"inputs/a.json": "out/a.json"}, transition_token="t1")
    first = chain.accept(run, request)
    assert chain.accept(run, request) == first
    assert run["attempts"] == 1
    with pytest.raises(PermissionError):
        chain.accept(run, request.model_copy(update={"reason": "changed"}))
    chain.failed(run, "candidate cleaned")
    chain.accept(run, request.model_copy(update={"transition_token": "t2"}))
    chain.failed(run, "candidate cleaned again")
    with pytest.raises(ValueError, match="budget"):
        chain.accept(run, request.model_copy(update={"transition_token": "t3"}))
    for _ in range(4):
        chain.charge(run, "backend_turns")
    with pytest.raises(RuntimeError, match="budget"):
        chain.charge(run, "backend_turns")


def test_unpersisted_decision_is_not_admitted(tmp_path):
    """A failed checkpoint write cannot leave a request available for runtime consumption."""
    chain = WorkflowChain(catalog(tmp_path), "fixture:a", tmp_path)
    run = chain.current
    run["business_status"] = "completed"
    (tmp_path / "out").mkdir()
    (tmp_path / "out/a.json").write_text("data")
    HandoffDecision(chain, run).record_artifacts()
    request = NextWorkflow(workflow_ref="fixture:b", reason="Continue", summary="A",
                           inputs={"inputs/a.json": "out/a.json"}, transition_token="t")

    def unavailable(state):
        """Inject a checkpoint write failure before any request reaches the runtime."""
        raise OSError("fixture disk failure")

    chain.persist = unavailable
    with pytest.raises(OSError):
        chain.accept(run, request)
    assert run["transition"] is None and run["attempts"] == 0
    assert chain.state["events"] == []


def test_handoff_cannot_copy_undeclared_configuration(tmp_path):
    """Visible configuration files cannot masquerade as verified handoff artifacts."""
    chain = WorkflowChain(catalog(tmp_path), "fixture:a", tmp_path)
    chain.current["business_status"] = "completed"
    (tmp_path / "config.yaml").write_text("private: fixture\n")
    with pytest.raises(ValueError, match="declared workflow output"):
        chain.accept(chain.current, NextWorkflow(workflow_ref="fixture:b", reason="Continue", summary="A",
            inputs={"inputs/a.json": "config.yaml"}, transition_token="t"))


def test_cli_response_replay_returns_same_transition_before_turn_drains(tmp_path, monkeypatch):
    """CLI yield signals do not turn an exact in-flight retry into another start or a false rejection."""
    import time
    agent, chain, _ = setup_agent(tmp_path, monkeypatch)
    try:
        agent.one_loop()
        transition = chain.current["transition"]
        agent.multi_agent.planning = {"token": transition["token"], "handoff": True, "submitted": transition["transition_id"],
            "blocked": None, "stage_index": agent.stage_manager.stage_index, "deadline": time.monotonic() + 10}
        monkeypatch.setattr(agent.backend, "requires_mcp", True)
        arguments = {**transition["request"], "transition_token": transition["token"]}
        result = agent.multi_agent.request_next_workflow(**arguments)
        assert result["transition_id"] == transition["transition_id"]
        assert chain.current["attempts"] == 1
        with pytest.raises(PermissionError):
            agent.multi_agent.request_next_workflow(**{**arguments, "summary": "conflicting"})
        agent.multi_agent.planning = None
        with pytest.raises(PermissionError):
            agent.multi_agent.request_next_workflow(**arguments)
    finally:
        agent.multi_agent.planning = None
        agent._startup_cleanup.close()
