"""Malformed tool JSON must yield bounded feedback without bypassing tool execution."""

import asyncio
import json

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from test_multi_agent import make_agent
from test_multi_agent_worker_context import ContextModel, call
from test_langchain_message_accounting import _middleware, _FakeSummaryModel
from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend


def assert_error_call_protocol(messages):
    """Verify rejected calls retain exactly one matching result in both provider encodings."""
    from langchain_openai.chat_models.base import _construct_responses_api_input, _convert_message_to_dict

    responses = _construct_responses_api_input(messages)
    chat = [_convert_message_to_dict(message) for message in messages]
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.invalid_tool_calls:
            calls = [item for item in responses if item.get("type") == "function_call" and item["call_id"] == call["id"]]
            results = [item for item in responses if item.get("type") == "function_call_output" and item["call_id"] == call["id"]]
            assert len(calls) == len(results) == 1
            assert calls[0]["arguments"] == call["args"]
            assert len([item for item in chat if item.get("role") == "tool" and item["tool_call_id"] == call["id"]]) == 1
            assert any(tc["id"] == call["id"] and tc["function"]["arguments"] == call["args"]
                       for item in chat for tc in item.get("tool_calls", []))


@pytest.mark.parametrize("streaming", [False, True])
def test_super_and_worker_correct_json_in_the_same_session(tmp_path, monkeypatch, streaming):
    """Real graphs repair the logged invalid escape; only corrected plans/writes execute once."""
    import ucagent.core.backends.langchain.agent as backend_module

    models = []
    value = make_agent(tmp_path)
    value.stream_output = streaming
    rendered = []
    value.set_message_echo_handler(lambda text, end: rendered.append(text + end))
    expected = r"literal \{cout,sum\}=a+b+cin"

    def choose(model, messages):
        """Read error results before resending valid JSON without changing literal backslashes."""
        assert_error_call_protocol(messages)
        if "SubAgentTool" in model.names:
            context = json.loads(next(msg.content for msg in reversed(messages) if isinstance(msg, HumanMessage)))
            if context["workflow_complete"]:
                return AIMessage(content="Verified.")
            args = {"plan_id": "recover", "planning_token": context["planning_token"],
                    "tasks": [{"id": "write", "instruction": expected}]}
            if len(model.seen) == 1:
                raw = json.dumps(args).replace("\\\\{", "\\{")
                return AIMessage(content="", invalid_tool_calls=[
                    {"name": "SubAgentTool", "id": "bad-plan", "args": raw, "error": None}])
            errors = [msg for msg in messages if isinstance(msg, ToolMessage) and msg.tool_call_id == "bad-plan"]
            assert len(errors) == 1 and errors[0].status == "error"
            assert "INVALID_TOOL_ARGUMENTS" in errors[0].content
            assert "Invalid \\escape" in errors[0].content
            failed = next(msg for msg in messages if isinstance(msg, AIMessage) and msg.invalid_tool_calls)
            assert failed.invalid_tool_calls[0]["args"] == json.dumps(args).replace("\\\\{", "\\{")
            assert value.multi_agent.records == {}
            return call("SubAgentTool", **args)
        if len(model.seen) == 1:
            args = {"path": "out/result.md", "content": expected}
            return AIMessage(content="", invalid_tool_calls=[{"name": "EditTextFile", "id": "bad-write",
                "args": json.dumps(args).replace("\\\\{", "\\{"), "error": None}])
        if len(model.seen) == 2:
            assert isinstance(messages[-1], ToolMessage) and messages[-1].status == "error"
            assert messages[-1].tool_call_id == "bad-write"
            assert not (tmp_path / "out/result.md").exists()
            return call("EditTextFile", path="out/result.md", content=expected)
        return call("SubmitTaskResult", summary="Wrote the required artifact")

    def factory(*args, **kwargs):
        """Use independent scripted models behind the production backend and tool pipeline."""
        model = ContextModel(choose=choose)
        models.append(model)
        return model

    monkeypatch.setattr(backend_module, "get_chat_model", factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda *args, **kwargs: None)
    value.backend = UCAgentLangChainBackend(value, value.cfg)
    value.backend.init()
    value._startup_cleanup.callback(value.backend.exit)
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert (tmp_path / "out/result.md").read_text().strip() == expected
        assert value.get_tool_by_name("SubAgentTool").call_count == 1
        record = value.multi_agent.records["recover/write"]
        assert record.attempt == 1 and record.calls == 2
        assert value.multi_agent.status()["metrics"]["worker_starts"] == 1
        assert len([model for model in models if model.seen]) == 2
        assert "INVALID_TOOL_ARGUMENTS" in "".join(rendered)
        assert value._tool__call_error == []
    finally:
        value._startup_cleanup.close()


def test_mixed_calls_keep_normal_tools_and_schema_validation_in_async_graph():
    """Invalid JSON executes nothing; sibling tools and later schema errors keep normal routing."""
    ran = []

    @tool
    def Read():
        """Read once without writing any data."""
        ran.append("read")
        return "input"

    @tool
    def Write(content: str):
        """Write only after JSON and argument schema are valid."""
        ran.append(content)
        return "written"

    def choose(model, messages):
        """Mix good and bad calls, then correct syntax before correcting the argument schema."""
        assert_error_call_protocol(messages)
        turn = len(model.seen)
        if turn == 1:
            return AIMessage(content="", tool_calls=[{"name": "Read", "id": "read", "args": {}}],
                             invalid_tool_calls=[{"name": "Write", "id": "bad", "args": '{"content":', "error": None}])
        errors = [msg for msg in messages if isinstance(msg, ToolMessage) and msg.tool_call_id == "bad"]
        assert len(errors) == 1 and errors[0].status == "error"
        if turn == 2:
            assert ran == ["read"]
            return call("Write", unrelated="schema must reject this")
        if turn == 3:
            assert ran == ["read"] and messages[-1].status == "error"
            return call("Write", content="valid")
        assert ran == ["read", "valid"]
        return AIMessage(content="done")

    model = ContextModel(choose=choose)
    graph = create_agent(model, tools=[Read, Write], middleware=[_middleware(_FakeSummaryModel())])
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="run")]}))
    assert result["messages"][-1].content == "done"
    assert len(model.seen) == 4


def test_repeated_invalid_plans_stop_at_existing_model_budget(tmp_path, monkeypatch):
    """Invalid calls neither start workers nor evade the managed planning round limit."""
    from multi_agent_fakes import install_planner

    value = make_agent(tmp_path, limits={"supervisor_model_rounds": 2})

    def choose(context, turn):
        """Keep emitting malformed arguments to exercise the production budget boundary."""
        return AIMessage(content="", invalid_tool_calls=[{
            "name": "SubAgentTool", "id": f"bad-{turn}", "args": "[]", "error": None}])

    model = install_planner(value, monkeypatch, choose)
    try:
        value.one_loop()
        assert len(model.contexts) == 2
        assert value.multi_agent.workflow_state == "failed"
        assert value.multi_agent.records == {}
        assert value.get_tool_by_name("SubAgentTool").call_count == 0
        assert any("budget exhausted" in event.get("error", "") for event in value.multi_agent.status()["events"])
    finally:
        value._startup_cleanup.close()


def test_missing_call_id_reports_error_without_an_orphan_tool_result():
    """Provider calls without IDs get textual feedback and cannot leak raw fallback calls."""
    from langchain_openai.chat_models.base import _construct_responses_api_input, _convert_message_to_dict

    message = AIMessage(content="", invalid_tool_calls=[{
        "name": "Write", "id": None, "args": None, "error": None}],
        additional_kwargs={"tool_calls": [{"id": None, "type": "function", "function": {
            "name": "Write", "arguments": None}}]})
    result = _middleware(_FakeSummaryModel()).after_model({"messages": [message]})
    assert result["jump_to"] == "model"
    assert isinstance(result["messages"][-1], HumanMessage)
    assert "INVALID_TOOL_ARGUMENTS" in result["messages"][-1].content
    assert not result["messages"][0].invalid_tool_calls
    assert all(item.get("type") not in {"function_call", "function_call_output"}
               for item in _construct_responses_api_input(result["messages"]))
    assert all(not _convert_message_to_dict(item).get("tool_calls") for item in result["messages"])
