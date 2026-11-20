"""Plain context bodies, readable streamed output and stage-boundary history retention."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from test_langchain_message_accounting import _FakeSummaryModel, _middleware
from test_multi_agent_worker_context import ContextModel
from ucagent.core.agent.execution import VerifyAgent
from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
from ucagent.core.backends.langchain.content import content_text, format_message
from ucagent.core.backends.langchain.middleware.messages import summarize_messages
from ucagent.core.multi_agent.worker import WorkerSession
import ucagent.util.log as log_util


def provider_blocks(text="first\nsecond"):
    """Reproduce nested text and opaque fields from the observed Responses output."""
    return [{"type": "reasoning", "id": "opaque-item", "status": "completed",
             "encrypted_content": "opaque-secret", "summary": [],
             "content": [{"type": "reasoning_text", "text": text}]},
            {"type": "function_call", "id": "opaque-call-item", "name": "Read",
             "arguments": '{"text":"not-body-text"}'}]


def test_text_extraction_keeps_newlines_and_drops_envelopes():
    """Only text leaves enter display bodies; unknown metadata is never stringified."""
    assert content_text(provider_blocks()) == "first\nsecond"
    assert content_text({"type": "unknown", "secret": "never-text"}) == ""
    result = format_message(AIMessage(content=provider_blocks(), tool_calls=[
        {"name": "Read", "id": "call-1", "args": {"instruction": "one\ntwo"}}]))
    assert "first\nsecond" in result
    assert "instruction: one\n        two" in result
    assert "opaque" not in result and "encrypted_content" not in result
    assert result.count("Tool Calls:") == 1
    assert "not-body-text" not in result


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_graph_replays_only_text_with_tool_linkage(asynchronous):
    """Main model inputs and checkpoint history omit block metadata in both graph modes."""
    body = json.dumps({"complete": False, "next_action": "repair", "items": [1, 2]})

    @tool
    def Read():
        """Return a textual tool result with transport-only annotations."""
        return [{"type": "text", "text": body, "id": "opaque-tool-item", "annotations": ["opaque"]}]

    def choose(model, messages):
        """Check actual model input after a real tool execution."""
        if len(model.seen) == 1:
            return AIMessage(content=provider_blocks(), tool_calls=[{"name": "Read", "id": "call-1", "args": {}}])
        assert isinstance(messages[-1], ToolMessage) and messages[-1].content == body
        assert messages[-1].tool_call_id == "call-1"
        previous = next(m for m in messages if isinstance(m, AIMessage))
        assert previous.content == "first\nsecond"
        assert previous.tool_calls[0]["id"] == "call-1"
        assert previous.usage_metadata["total_tokens"] == 15
        from langchain_openai.chat_models.base import _construct_responses_api_input
        payload = _construct_responses_api_input(messages)
        assert "opaque" not in json.dumps(payload)
        assert any(item.get("type") == "function_call" and item["call_id"] == "call-1" for item in payload)
        return AIMessage(content=[{"type": "text", "text": "done", "id": "opaque-final"}])

    model = ContextModel(choose=choose)
    graph = create_agent(model, tools=[Read], middleware=[_middleware(_FakeSummaryModel())])
    inputs = {"messages": [SystemMessage(content="system"), HumanMessage(content="read")]}
    if asynchronous:
        import asyncio
        result = asyncio.run(graph.ainvoke(inputs))
    else:
        result = graph.invoke(inputs)
    assert result["messages"][-1].content == "done"
    assert len(model.seen) == 2


def test_summary_input_and_output_use_the_same_text_policy():
    """Context compression cannot reintroduce opaque fields via its input or response."""
    model = _FakeSummaryModel(content=provider_blocks("compact"))
    summary = summarize_messages([AIMessage(content=provider_blocks())], 1000, model)
    assert summary.content == "compact"
    assert "opaque" not in str([m.content for m in model.calls[0][0]])
    assert any(m.content == "first\nsecond" for m in model.calls[0][0])


def test_stage_completion_retains_history_but_manual_reset_still_works():
    """Completing a stage neither clears history nor requests a summary model call."""
    model = _FakeSummaryModel()
    middleware = _middleware(model)
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.message_manage_node = middleware
    messages = [SystemMessage(content="system"), HumanMessage(content="keep context"), AIMessage(content="progress")]
    backend.on_stage_complete(SimpleNamespace(name="3.1"))
    assert not middleware._is_reset_chat
    assert middleware.before_model({"messages": messages}) == {}
    assert model.calls == []
    backend.reset_chat(force=True)
    assert middleware._is_reset_chat and middleware._is_reset_force


@pytest.fixture
def message_log(tmp_path, monkeypatch):
    """Create an isolated log sink and restore global logging state after the test."""
    previous = log_util.get_msg_logger()
    path = tmp_path / "messages.log"
    monkeypatch.setattr(log_util, "__silent__", False)
    log_util.init_msg_logger(name="text-output-test", log_file=str(path))
    try:
        yield path
    finally:
        for handler in log_util.get_msg_logger().handlers:
            handler.close()
        log_util.get_msg_logger().handlers.clear()
        log_util.__msg_logger__ = previous


@pytest.mark.parametrize("custom_handler", [False, True])
def test_file_output_preserves_exact_stream_endings(message_log, capsys, custom_handler):
    """CLI and custom frontend paths record the same text without token or blank-line splits."""
    output = io.StringIO()
    owner = SimpleNamespace(message_echo_handler=(lambda text, end: output.write(text + end)) if custom_handler else None)
    echo = MethodType(VerifyAgent.message_echo, owner)
    echo("header")
    echo("first", end="")
    echo(" second", end="")
    echo("")
    echo("\nnext")
    expected = "header\nfirst second\n\nnext\n"
    assert message_log.read_text() == expected
    assert (output.getvalue() if custom_handler else capsys.readouterr().out) == expected


def test_parallel_worker_blocks_do_not_share_partial_buffers(message_log):
    """Task tags stay on headers and complete worker blocks remain independently readable."""
    owner = SimpleNamespace(message_echo_handler=lambda text, end: None)
    owner.message_echo = MethodType(VerifyAgent.message_echo, owner)

    def emit(index):
        """Write a complete task message through the actual worker and agent log path."""
        worker = WorkerSession.__new__(WorkerSession)
        worker.parent, worker.record = owner, SimpleNamespace(key=f"plan/task-{index}")
        worker.message_echo(format_message(AIMessage(content=f"body-{index}\nend-{index}")))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(emit, range(20)))
    text = message_log.read_text()
    for index in range(20):
        header = f"\n[plan/task-{index}]\n" + " AI Message ".center(80, "=")
        assert header + f"\n\nbody-{index}\nend-{index}\n" in text


def make_output_backend(events, output):
    """Use deterministic graph events with the production backend output methods."""
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.vagent = SimpleNamespace(is_break=lambda: False, message_echo=lambda text, end="\n": output.write(text + end))
    backend.prepare = lambda: None
    backend.agent = SimpleNamespace(stream=lambda *args, **kwargs: iter(events))
    backend.state_record_mesg = lambda msg: None
    backend.check_tool_call_error = lambda msg: None
    return backend


def test_stream_has_one_header_per_response_and_preserves_all_tool_results():
    """Multiple responses, batched tools and summary fragments cannot merge message boundaries."""
    human = HumanMessage(content="start", id="h")
    ai = AIMessage(content=provider_blocks("first line"), id="a", tool_calls=[
        {"name": "Read", "id": "c1", "args": {}}, {"name": "Read", "id": "c2", "args": {}}])
    tools = [ToolMessage(content=f"result-{i}", name="Read", tool_call_id=f"c{i}", id=f"t{i}") for i in (1, 2)]
    final = AIMessage(content="second line", id="b")
    events = [("values", {"messages": [human]}),
              ("messages", (AIMessageChunk(content="first ", id="a"), {"langgraph_node": "model"})),
              ("messages", (AIMessageChunk(content="line", id="a"), {"langgraph_node": "model"})),
              ("values", {"messages": [human, ai]}),
              ("values", {"messages": [human, ai, *tools]}),
              ("messages", (AIMessageChunk(content="internal-summary", id="summary"), {"langgraph_node": "before_model"})),
              ("messages", (AIMessageChunk(content="second line", id="b"), {"langgraph_node": "model"})),
              ("values", {"messages": [human, ai, *tools, final]})]
    output = io.StringIO()
    make_output_backend(events, output).do_work_stream({}, {})
    text = output.getvalue()
    assert text.count(" AI Message ") == 2
    assert text.count(" Tool Message ") == 2
    assert "first line\n\nTool Calls:" in text
    assert text.endswith("second line\n")
    assert "internal-summary" not in text and "opaque" not in text
    assert all(text.count(f"result-{i}") == 1 for i in (1, 2))


def test_value_output_keeps_each_tool_result_and_deduplicates_updated_ids():
    """A body-normalization event does not print a duplicate, and no batched result is lost."""
    human = HumanMessage(content="start", id="h")
    ai = AIMessage(content=provider_blocks(), id="a")
    tools = [ToolMessage(content=[{"type": "text", "text": f"result-{i}", "id": "opaque"}], tool_call_id=str(i), id=f"t{i}") for i in (1, 2)]
    events = [("values", {"messages": [human]}), ("values", {"messages": [human, ai]}),
              ("values", {"messages": [human, ai.model_copy(update={"content": "first\nsecond"})]}),
              ("values", {"messages": [human, ai, *tools]})]
    output = io.StringIO()
    make_output_backend(events, output).do_work_values({}, {})
    text = output.getvalue()
    assert text.count("first\nsecond") == 1 and "opaque" not in text
    assert text.count(" Tool Message ") == 2
    assert all(text.count(f"result-{i}") == 1 for i in (1, 2))


@pytest.mark.parametrize("body", ["", "first line"])
@pytest.mark.parametrize("chunk_id", [None, "different-id", "final-id"])
def test_stream_titles_follow_committed_turns_not_chunk_ids(body, chunk_id):
    """Empty chunks, ID replacement and text/tool responses each produce one useful heading."""
    human = HumanMessage(content="start", id="human")
    reply = AIMessage(content=body, id="final-id", tool_calls=[{"name": "Read", "args": {}, "id": "c"}])
    events = [("values", {"messages": [human]}),
              ("messages", (AIMessageChunk(content="", id="empty-id"), {"langgraph_node": "model"})),
              ("messages", (AIMessageChunk(content=body[:5], id=chunk_id), {"langgraph_node": "model"})),
              ("messages", (AIMessageChunk(content=body[5:], id="tail-id"), {"langgraph_node": "model"})),
              ("values", {"messages": [human, reply]}),
              ("messages", (reply, {"langgraph_node": "model"})),
              ("values", {"messages": [human, reply]})]
    output = io.StringIO()
    make_output_backend(events, output).do_work_stream({}, {})
    rendered = output.getvalue()
    assert rendered.count(" AI Message ") == 1
    assert rendered.count("Tool Calls:") == 1
    assert rendered.count("Read (c)") == 1
    if body:
        assert rendered.count(body) == 1
        assert "=" * 10 + "\n\n" + body + "\n\nTool Calls:" in rendered


def test_empty_response_does_not_leave_orphan_title_and_prefix_is_completed():
    """An empty response stays invisible; partial streaming retains the final body tail."""
    human = HumanMessage(content="start", id="h")
    empty = AIMessage(content="", id="empty")
    final = AIMessage(content="partial complete", id="committed")
    events = [("values", {"messages": [human]}),
              ("messages", (AIMessageChunk(content="", id="empty"), {})),
              ("values", {"messages": [human, empty]}),
              ("messages", (AIMessageChunk(content="partial", id="chunk"), {})),
              ("values", {"messages": [human, empty, final]})]
    output = io.StringIO()
    make_output_backend(events, output).do_work_stream({}, {})
    assert output.getvalue().count(" AI Message ") == 1
    assert output.getvalue().endswith("\n\npartial complete\n")


def test_interrupted_stream_closes_last_text_line():
    """Provider failures cannot concatenate the next message with a partial token line."""
    output = io.StringIO()
    backend = make_output_backend([], output)

    def fail(*args, **kwargs):
        """Interrupt between a visible token and the final graph values event."""
        yield "messages", (AIMessageChunk(content="partial", id="chunk"), {})
        raise RuntimeError("interrupted")

    backend.agent.stream = fail
    with pytest.raises(RuntimeError, match="interrupted"):
        backend.do_work_stream({}, {})
    backend.echo_message(ToolMessage(content="cancelled", name="Read", tool_call_id="c"))
    assert "partial\n\n" + " Tool Message ".center(80, "=") in output.getvalue()


def test_nested_task_arguments_have_literal_newlines():
    """Task instruction lists are readable without escaped newline sequences or duplicate call IDs."""
    reply = AIMessage(content="", tool_calls=[{"name": "SubAgentTool", "id": "call-id", "args": {
        "tasks": [{"id": "one", "instruction": "first\n\nsecond", "outputs": ["out/one"]}]}}])
    rendered = format_message(reply)
    assert "\\n" not in rendered
    assert "instruction: first\n            \n            second" in rendered
    assert rendered.count("call-id") == 1


@pytest.mark.parametrize("view_attached", [False, True])
@pytest.mark.parametrize("custom_sink", [False, True])
def test_runtime_forwarding_records_each_message_once(message_log, capsys, view_attached, custom_sink):
    """TUI attachment and Console forwarding never double-write the Agent-owned log record."""
    import threading
    from ucagent.runtime.host import RuntimeHost
    from ucagent.runtime.output import OutputBuffer
    from ucagent.runtime.events import EventBuffer

    host = RuntimeHost.__new__(RuntimeHost)
    host._lock = threading.RLock()
    host._message_views = {"tui"} if view_attached else set()
    host.events, host.messages, host.output = EventBuffer(), OutputBuffer(), OutputBuffer()
    host._previous_message_handler = log_util.message if custom_sink else None
    owner = SimpleNamespace(message_echo_handler=host.message_echo)
    echo = MethodType(VerifyAgent.message_echo, owner)
    try:
        echo("header")
        echo("part", end="")
        echo(" two")
        expected = "header\npart two\n"
        assert message_log.read_text() == expected
        assert capsys.readouterr().out == ("" if view_attached else expected)
        assert "\n".join(host.messages.get_lines()) == expected.rstrip("\n")
    finally:
        host.messages.close()
        host.output.close()


def test_display_projection_preserves_protocol_and_user_json():
    """Only explicitly marked prompts and control tools may hide orchestration envelopes."""
    from ucagent.core.multi_agent.display import planning_message
    from ucagent.core.tools.delegation import SupervisorTool, NoArgs
    from ucagent.core.multi_agent.worker import BoundTool

    output = io.StringIO()
    backend = make_output_backend([], output)
    backend.vagent.test_tools = [
        SupervisorTool(name="CurrentTips", description="tips", args_schema=NoArgs, service=None, action="tips"),
        SupervisorTool(name="SubAgentTool", description="submit", args_schema=NoArgs, service=None, action="submit"),
        SupervisorTool(name="ReadTextFile", description="read", args_schema=NoArgs, service=None, action="read")]
    context = {"stage": "mission: example\ncurrent_stage:\n  task: write report", "planning_token": "keep-token",
               "roles": {"worker": {}}, "max_workers": 2}
    raw = json.dumps(context)
    prompt = backend.get_human_message(raw, display_text=planning_message(context))
    tips = ToolMessage(content=raw, tool_call_id="c", name="CurrentTips")
    file_body = ToolMessage(content=raw, tool_call_id="read", name="ReadTextFile")
    for msg in (prompt, tips):
        rendered = backend.format_message(msg)
        assert context["stage"] in rendered and "keep-token" not in rendered and "roles" not in rendered
        assert msg.content == raw
    assert raw in backend.format_message(file_body)
    assert raw in backend.format_message(HumanMessage(content=raw))
    worker_tips = BoundTool(name="CurrentTips", description="tips", args_schema=NoArgs, worker=None, action="tips")
    backend.vagent.test_tools = [worker_tips]
    worker_raw = json.dumps({"tips": context["stage"], "step_token": "worker-token", "budget": {"rounds": 1}})
    worker_message = ToolMessage(content=worker_raw, name="CurrentTips", tool_call_id="w")
    assert context["stage"] in backend.format_message(worker_message)
    assert "worker-token" not in backend.format_message(worker_message)
    assert worker_message.content == worker_raw
    history_owner = SimpleNamespace(backend=backend, messages_get_raw=lambda: [prompt, worker_message])
    history = VerifyAgent.message_get_str(history_owner, 0, 2)
    assert all("token" not in text for text in history)


def test_control_results_keep_failures_and_validation_details():
    """Queue summaries omit metrics/budgets while preserving outcomes and actionable diagnostics."""
    from ucagent.core.multi_agent.display import control_result

    result = {"plans": {"p": {"state": "failed", "tasks": ["p/t"], "validation": {
        "complete": False, "diagnostic": {"stage": "evidence-stage", "error": "artifact missing",
                                            "next_action": "write out/result"}}}},
        "tasks": [{"task_id": "p/t", "state": "failed", "summary": "repair needed", "artifacts": {},
                   "error": "worker stopped", "budget": {"seconds_remaining": 2}}],
        "running": 0, "max_workers": 2, "workflow_state": "failed", "metrics": {"plans": 1},
        "events": [{"event": "task_finished", "error": "tool failure"}, {"event": "plan_submitted"}]}
    rendered = control_result("status", json.dumps(result))
    assert all(text in rendered for text in ("failed", "p/t", "artifact missing", "write out/result",
                                            "repair needed", "worker stopped", "tool failure", "evidence-stage"))
    assert all(text not in rendered for text in ("budget", "metrics", "plan_submitted", "seconds_remaining"))
    rejected = {"submitted": False, "error_code": "SUBSTAGES_REMAIN", "error": "finish the substage",
                "tips": "current task\nnext step", "step_token": "hidden", "next_action": "CompleteSubStage"}
    rendered = control_result("submit", json.dumps(rejected))
    assert "SUBSTAGES_REMAIN" in rendered and "current task\nnext step" in rendered and "hidden" not in rendered
    assert control_result("tips", "plain error") == "plain error"
    assert control_result("tips", '{"stage": null}') == "No active stage."
    assert "SubmitTaskResult" in control_result("tips", '{"scope_done": true, "next_action": "SubmitTaskResult"}')
    assert control_result("check", json.dumps(result)) == json.dumps(result)


@pytest.mark.parametrize("streaming", [False, True])
def test_real_multi_messages_keep_protocol_in_model_and_render_readable_bodies(tmp_path, monkeypatch, streaming):
    """Real Super/worker graphs retain tokens and continuation context while emitting clean messages."""
    import ucagent.core.backends.langchain.agent as backend_module
    from test_multi_agent import make_agent

    models = []
    output = io.StringIO()
    instruction = "Write the evidence.\nKeep the output concise."

    def decide(model, messages):
        """Exercise current tips, delegation, worker continuation and final result feedback."""
        if "SubAgentTool" in model.names:
            context = json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))
            assert context["planning_token"]
            if context["workflow_complete"]:
                assert context["previous_result"]["plans"]["readable"]["state"] == "completed"
                return AIMessage(content="Workflow verified.")
            if len(model.seen) == 1:
                return AIMessage(content="", tool_calls=[{"name": "CurrentTips", "id": "super-tips", "args": {}}])
            tips = json.loads(messages[-1].content)
            assert tips["planning_token"] == context["planning_token"] and "roles" in tips
            return AIMessage(content="", tool_calls=[{"name": "SubAgentTool", "id": "dispatch", "args": {
                "plan_id": "readable", "planning_token": context["planning_token"],
                "tasks": [{"id": "task", "instruction": instruction}]}}])
        turn = len(model.seen)
        if turn == 1:
            assert messages[-1].content.startswith(instruction + "\n")
            assert json.loads(messages[-1].content.rsplit("\n", 1)[1])["step_token"]
            return AIMessage(content="", tool_calls=[{"name": "CurrentTips", "id": "worker-tips", "args": {}}])
        if turn == 2:
            assert json.loads(messages[-1].content)["step_token"]
            assert "budget" in json.loads(messages[-1].content)
            return AIMessage(content="Continue working in this session.")
        if turn == 3:
            assert isinstance(messages[-1], HumanMessage)
            assert "Continue in this session" in messages[-1].content
            assert json.loads(messages[-1].content.rsplit("\n", 1)[1])["step_token"]
            return AIMessage(content="", tool_calls=[{"name": "EditTextFile", "id": "write", "args": {
                "path": "out/result.md", "content": "validated evidence"}}])
        return AIMessage(content="", tool_calls=[{"name": "SubmitTaskResult", "id": "finish", "args": {
            "summary": "Wrote out/result.md"}}])

    def factory(*args, **kwargs):
        """Create isolated offline model instances using the actual graph/callback machinery."""
        model = ContextModel(choose=decide)
        models.append(model)
        return model

    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda *args, **kwargs: None)
    agent = make_agent(tmp_path)
    agent.stream_output = streaming
    agent.message_echo_handler = lambda text, end: output.write(text + end)
    agent.backend = UCAgentLangChainBackend(agent, agent.cfg)
    agent.backend.init()
    agent._startup_cleanup.callback(agent.backend.exit)
    try:
        agent.one_loop("Please verify the artifact.")
        assert agent.multi_agent.workflow_state == "completed", agent.multi_agent.status()
        rendered = output.getvalue()
        assert rendered.count(" AI Message ") == 7
        assert "[readable/task]\n" + " Human Message ".center(80, "=") + "\n\n" + instruction in rendered
        assert "Please verify the artifact." in rendered
        assert "Previous result:\nworkflow: running" in rendered
        assert "Workflow verified." in rendered
        assert all(key not in rendered for key in ('"delegation":', '"scope_root":', '"budget":', '"planning_token":'))
        assert len([model for model in models if model.seen]) == 2
    finally:
        agent._startup_cleanup.close()
