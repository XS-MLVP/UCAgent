"""Worker tracing, recoverable lifecycle feedback and continuous subtree acceptance."""

import json
import threading
from typing import Any
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from multi_agent_fakes import install_planner
from test_multi_agent import make_agent, stage, tool, finish
from ucagent.core.multi_agent.worker import WorkerSession


class ContextModel(BaseChatModel):
    """Execute caller-defined decisions while retaining real graph callback dispatch."""

    choose: Any
    names: set[str] = Field(default_factory=set)
    seen: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        """Identify the offline provider without importing any network model."""
        return "worker-context-test"

    def bind_tools(self, tools, **kwargs):
        """Retain the production capability set for each test decision."""
        self.names = {item.name for item in tools}
        return self

    def get_num_tokens_from_messages(self, messages, tools=None):
        """Avoid optional tokenization downloads during graph execution."""
        return 20

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Record actual model inputs and supply usage for callback assertions."""
        self.seen.append(list(messages))
        message = self.choose(self, messages)
        message.usage_metadata = {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
        return ChatResult(generations=[ChatGeneration(message=message)])


def call(name, **args):
    """Produce one tool call for the actual LangChain dispatcher."""
    return AIMessage(content="", tool_calls=[{"id": name, "name": name, "args": args}])


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_langfuse_context_is_independent_correlated_and_drained(tmp_path, monkeypatch, enabled):
    """Trace parallel models, tools and summaries without an exporter or shared callback maps."""
    import langfuse.langchain as tracing
    import ucagent.core.agent.construction as construction
    import ucagent.core.backends.langchain.agent as backend_module
    callbacks, workers, models, roots = [], [], [], []
    client = Mock()
    client.auth_check.return_value = True
    client_factory = Mock(return_value=client)
    monkeypatch.setattr(construction, "Langfuse", client_factory)

    class RecordingCallback(BaseCallbackHandler):
        """Spy on the same public events consumed by the Langfuse integration."""

        run_inline = True

        def __init__(self, *, public_key):
            """Keep independent model/run state and assert resolved project selection."""
            assert public_key == "test-project"
            self.inputs, self.outputs, self.errors, self.tools = [], [], [], []
            callbacks.append(self)

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            """Retain root names and metadata for the Super and worker traces."""
            if parent_run_id is None:
                roots.append((kwargs.get("name"), kwargs.get("metadata", {})))

        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            """Capture exact prompts, conversation state and task correlation."""
            self.inputs.append((messages[0], dict(kwargs.get("metadata", {}))))

        def on_llm_end(self, response, *, run_id, **kwargs):
            """Capture generated content and usage through ordinary provider callbacks."""
            self.outputs.append(response.generations[0][0].message)

        def on_tool_end(self, output, *, run_id, **kwargs):
            """Prove final submission results are delivered before the graph closes."""
            self.tools.append(output)

        def on_chain_error(self, error, *, run_id, **kwargs):
            """Record premature generator closure or other unexpected trace failures."""
            self.errors.append(error)

    monkeypatch.setattr(construction, "CallbackHandler", RecordingCallback)
    monkeypatch.setattr(tracing, "CallbackHandler", RecordingCallback)
    barrier = threading.Barrier(2)

    def decide(model, messages):
        """Plan two independent workers, then exercise tools and context compression."""
        if not model.names:
            return AIMessage(content="Retain the authorized task and continue its remaining tools.")
        if "SubAgentTool" in model.names:
            context = json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))
            if context["workflow_complete"]:
                return AIMessage(content="Both artifacts passed the original Checker.")
            return call("SubAgentTool", plan_id="traced", scope="task", tasks=[
                {"id": str(i), "instruction": f"Write out/{i}.txt", "outputs": [f"out/{i}.txt"]}
                for i in range(2)])
        turn = len(model.seen)
        if turn == 1:
            barrier.wait(5)
            return call("CurrentTips")
        if turn == 2:
            instruction = next(m.content for m in model.seen[0] if isinstance(m, HumanMessage))
            path = instruction.splitlines()[0].removeprefix("Write ")
            return call("EditTextFile", path=path, content="trace evidence")
        assert turn == 3
        return call("SubmitTaskResult", summary="Wrote traced evidence")

    def factory(cfg, handlers, **kwargs):
        """Keep provider-local callbacks alongside inherited tracing callbacks."""
        model = ContextModel(choose=decide, callbacks=handlers)
        models.append(model)
        return model

    original_run = WorkerSession.run

    def run(worker, runner_factory=None):
        """Retain worker identities while executing their unmodified production graph."""
        workers.append(worker)
        return original_run(worker, runner_factory)

    monkeypatch.setattr(WorkerSession, "run", run)
    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    value = make_agent(tmp_path, max_workers=2,
        stages=[stage("parallel", output_files=["out/0.txt", "out/1.txt"])],
        config_overrides={"langfuse.enable": enabled, "langfuse.public_key": "test-project",
                          "langfuse.secret_key": "test-secret", "langfuse.base_url": "http://unused.invalid",
                          "conversation_summary.max_keep_msgs": 4, "conversation_summary.tail_keep_msgs": 2,
                          "conversation_summary.max_tokens": 0})
    value.backend = backend_module.UCAgentLangChainBackend(value, value.cfg)
    value.backend.init()
    value._startup_cleanup.callback(value.backend.exit)
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(workers) == 2 and all(w.closed for w in workers)
        assert len({w.thread_id for w in workers}) == 2
        assert all(w.record.attempt == 1 for w in workers)
        if enabled:
            assert len(callbacks) == 3
            assert client_factory.call_count == 1
            assert len({id(w.langfuse_handler) for w in workers}) == 2
            for worker in workers:
                handler = worker.langfuse_handler
                assert handler is not value.langfuse_handler
                assert len(handler.inputs) == len(handler.outputs) >= 4  # main + summary
                assert not handler.errors
                assert any("Summarize the conversation" in str(m.content)
                           for messages, _ in handler.inputs for m in messages)
                assert any(isinstance(m, ToolMessage) for messages, _ in handler.inputs for m in messages)
                assert worker.record.spec.instruction in handler.inputs[0][0][-1].content
                for _, metadata in handler.inputs:
                    assert metadata["langfuse_session_id"] == value.session_id.hex
                    assert metadata["ucagent_task_id"] == worker.record.key
                    assert metadata["ucagent_attempt"] == 1
                    assert metadata["ucagent_worker_session_id"] == worker.session_id.hex
                    assert metadata["ucagent_role"] == "worker"
                assert all(m.usage_metadata["total_tokens"] == 15 for m in handler.outputs)
                assert any("submitted" in str(result) for result in handler.tools)
            assert any(name == "Super-Agent" for name, _ in roots)
            assert sum(name.startswith("Sub-Agent:") for name, _ in roots) == 2
            client.shutdown.assert_not_called()
        else:
            assert callbacks == []
            client_factory.assert_not_called()
            assert all("callbacks" not in w.backend.get_work_config() for w in workers)
    finally:
        value._startup_cleanup.close()
    if enabled:
        client.shutdown.assert_called_once()


@pytest.mark.parametrize("group", [True, False])
def test_real_worker_repairs_lifecycle_errors_without_returning_to_super(tmp_path, monkeypatch, group):
    """Early result, ordinary text, failed gate and stale token keep 3.1/3.2 in one session."""
    import ucagent.core.backends.langchain.agent as backend_module
    children = [stage("first", output_files=["out/first.txt"]), stage("second", output_files=["out/second.txt"])]
    value = make_agent(tmp_path, stages=[stage("root", stage=children,
        **({} if group else {"output_files": ["out/second.txt"]})), stage("next", output_files=["out/next.txt"])])
    planner = install_planner(value, monkeypatch)
    workers = []
    state = {}

    def decide(model, messages):
        """Read real tool feedback before each corrective call and assert unchanged ownership."""
        worker = workers[-1]
        if worker.record.lease.steps:
            assert len(planner.contexts) == 1
            assert len(workers) == 1 and worker.record.attempt == 1
            turn = len(model.seen)
            last = messages[-1]
            if turn == 1:
                context = json.loads(last.content.split("\n", 1)[1])
                state["token"] = context["step_token"]
                assert len(context["remaining_substages"]) == 2
                return call("SubmitTaskResult", summary="Only starting; deliberately premature")
            if turn == 2:
                assert json.loads(last.content)["error_code"] == "SUBSTAGES_REMAIN"
                assert worker.record.result is None
                return AIMessage(content="A status update, without submitting the subtree.")
            if turn == 3:
                assert isinstance(last, HumanMessage) and "Continue in this session" in last.content
                return call("CompleteSubStage", step_token=state["token"])
            if turn == 4:
                result = json.loads(last.content)
                assert not result["validation"].get("complete")
                state["token"] = result["step_token"]
                return call("EditTextFile", path="out/first.txt", content="first evidence")
            if turn == 5:
                return call("SetCurrentStageJournal", journal="First step produced evidence")
            if turn == 6:
                return call("CompleteSubStage", step_token=state["token"])
            if turn == 7:
                result = json.loads(last.content)
                assert result["validation"]["complete"] and not result["scope_done"]
                assert result["remaining_substages"] == ["1.2-second"]
                return call("CompleteSubStage", step_token=state["token"])
            if turn == 8:
                result = json.loads(last.content)
                assert result["error_code"] == "STALE_STEP_TOKEN"
                state["token"] = result["step_token"]
                return call("EditTextFile", path="out/second.txt", content="second evidence")
            if turn == 9:
                return call("SetCurrentStageJournal", journal="Second step produced evidence")
            if turn == 10:
                return call("CompleteSubStage", step_token=state["token"])
            assert turn == 11
            assert json.loads(last.content)["scope_done"]
            assert "out/next.txt" not in last.content
        else:
            if len(model.seen) == 1:
                return call("EditTextFile", path="out/next.txt", content="next evidence")
        return call("SubmitTaskResult", summary="All authorized work passed")

    worker_models = []

    def run(worker):
        """Bind a fresh provider while preserving the worker graph and tool lifecycle."""
        workers.append(worker)
        worker.run_backend()

    def factory(cfg, handlers, **kwargs):
        """Reuse the installed planner only for its own first two provider allocations."""
        if not value.backend.agent:
            return planner
        model = ContextModel(choose=decide, callbacks=handlers)
        worker_models.append(model)
        return model

    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(workers) == 2 and workers[0].thread_id != workers[1].thread_id
        assert len(planner.contexts) == 3  # root, next, final summary
        assert [c["stage_name"] for c in planner.contexts] == ["first", "next", None]
        assert len(planner.contexts[0]["delegation"]["remaining_substages"]) == 2
        assert workers[0].record.rounds == 11
        assert all(s.is_completed() for s in value.stage_manager.stages)
    finally:
        value._startup_cleanup.close()


@pytest.mark.parametrize("scope", ["stage", "task"])
def test_narrow_subtree_requires_explicit_reason_without_starting_worker(tmp_path, scope):
    """An accidental leaf/file plan can be corrected before consuming worker attempts."""
    value = make_agent(tmp_path, stages=[stage("root", stage=[stage("first"), stage("second")])])
    plan = {"plan_id": "narrow", "scope": scope, "tasks": [{"id": "t", "instruction": "Work"}]}
    try:
        context = value.multi_agent.planning_context()["delegation"]
        assert context["root"] == "1-root" and context["narrow_scope_requires_reason"]
        with pytest.raises(ValueError, match="scope_reason"):
            value.multi_agent.submit(plan)
        assert value.multi_agent.records == {} and value.multi_agent.driver.active_lease is None
        assert value.multi_agent.status()["metrics"]["worker_starts"] == 0

        def run(worker):
            """Explicit narrowing still supports a deliberate file or single-step task."""
            tool(worker, "EditTextFile", path="out/narrow.txt", content="evidence")
            tool(worker, "SubmitTaskResult", summary="Explicitly bounded work")

        value.multi_agent.runner_factory = run
        plan["scope_reason"] = "Intentional single-step delivery; this stage has no Skill or reference gates."
        if scope == "task":
            plan["tasks"][0]["outputs"] = ["out/narrow.txt"]
        value.multi_agent.submit(plan)
        assert finish(value.multi_agent, "narrow")["plans"]["narrow"]["state"] == "completed"
        assert value.stage_manager.get_current_stage().name == "second"
    finally:
        value._startup_cleanup.close()


def test_langfuse_shutdown_waits_for_active_worker(tmp_path, monkeypatch):
    """Shared telemetry outlives a cancelled worker's final callback and resource teardown."""
    import langfuse.langchain as tracing
    import ucagent.core.agent.construction as construction
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    client = Mock()
    client.auth_check.return_value = True
    client.shutdown.side_effect = lambda: closed.set()
    monkeypatch.setattr(construction, "Langfuse", Mock(return_value=client))
    monkeypatch.setattr(construction, "CallbackHandler", Mock())
    monkeypatch.setattr(tracing, "CallbackHandler", Mock())
    value = make_agent(tmp_path, config_overrides={"langfuse.enable": True})

    def run(worker):
        """Keep an in-flight worker alive until its final trace is allowed to finish."""
        entered.set()
        assert release.wait(5)
        assert not closed.is_set()

    value.multi_agent.runner_factory = run
    value.multi_agent.submit({"plan_id": "live", "tasks": [{"id": "t", "instruction": "Wait"}]})
    assert entered.wait(3)
    cleanup = threading.Thread(target=value._startup_cleanup.close)
    cleanup.start()
    try:
        assert value.multi_agent.records["live/t"].cancel.wait(3)
        assert not closed.is_set()
    finally:
        release.set()
        cleanup.join(5)
    assert not cleanup.is_alive() and closed.is_set()
    client.shutdown.assert_called_once()


def test_recoverable_submission_errors_still_exhaust_model_budget(tmp_path, monkeypatch):
    """A worker cannot evade finite budgets by repeatedly requesting an early submission."""
    import ucagent.core.backends.langchain.agent as backend_module
    models = []

    def factory(cfg, handlers, **kwargs):
        """Always request premature submission through the real graph and tool boundary."""
        model = ContextModel(choose=lambda model, messages: call("SubmitTaskResult", summary="Too soon"))
        models.append(model)
        return model

    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    value = make_agent(tmp_path, stages=[stage("root", stage=[stage("first"), stage("second")])],
                       limits={"worker_model_rounds": 2})
    try:
        value.multi_agent.submit({"plan_id": "bounded", "tasks": [{"id": "t", "instruction": "Work"}]})
        result = finish(value.multi_agent, "bounded")
        assert result["tasks"][0]["state"] == "cancelled"
        assert "model-round budget" in result["tasks"][0]["error"]
        assert result["metrics"]["worker_starts"] == 1
        assert value.stage_manager.stage_index == 0 and len(models[0].seen) == 2
    finally:
        value._startup_cleanup.close()


def test_explicit_stage_overrides_subtree_default_for_leaf(tmp_path):
    """Planning previews cannot invalidate an explicit scope on a standalone stage."""
    value = make_agent(tmp_path, delegation_scope="subtree")

    def run(worker):
        """Produce a standalone artifact using the explicitly selected single-stage scope."""
        tool(worker, "EditTextFile", path="out/result.md", content="evidence")
        tool(worker, "SubmitTaskResult", summary="Standalone work")

    value.multi_agent.runner_factory = run
    try:
        assert value.multi_agent.planning_context()["delegation"]["remaining_substages"] == []
        with pytest.raises(ValueError, match="no subtree"):
            value.multi_agent.submit({"plan_id": "auto", "tasks": [{"id": "t", "instruction": "Work"}]})
        value.multi_agent.submit({"plan_id": "leaf", "scope": "stage", "tasks": [{"id": "t", "instruction": "Work"}]})
        assert finish(value.multi_agent, "leaf")["plans"]["leaf"]["state"] == "completed"
    finally:
        value._startup_cleanup.close()
