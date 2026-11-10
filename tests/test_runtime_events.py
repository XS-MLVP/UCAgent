"""Exercise classified output at real producer boundaries, including cursor and ownership limits."""

import asyncio
import logging
import sys

import pytest

from test_runtime_host import make_host
from ucagent.runtime.events import EventBuffer
from ucagent.runtime.output import OUTPUT_OWNER, ServiceLogHandler
from ucagent.util.log import info, warning
from ucagent.util.output import OUTPUT_SINK, output_context


def test_independent_budgets_partial_lines_restart_and_pagination():
    """HTTP floods cannot evict activity; partial text, byte limits and lost history are explicit."""
    events = EventBuffer(max_records=3, max_bytes=32)
    events.append("half", source="model")
    first = events.read("activity")
    assert first["data"][0]["text"] == "half"
    for index in range(10):
        events.append(f"GET {index}\n", view="system", source="http")
    assert events.read("activity")["data"] == first["data"]
    events.append(" line\n", source="model")
    assert events.read("activity", after=first["cursor"])["data"][0]["text"] == " line\n"
    page = events.read("system", after=0, limit=2)
    assert page["gap"] and page["has_more"] and len(page["data"]) == 2
    assert len(events.read("system", after=page["cursor"])["data"]) == 1
    reset = events.read("activity", after=999, generation="old-process")
    assert reset["reset"] and len(reset["data"]) == 2
    tail = events.read("activity", tail=True)
    assert tail["data"] == [] and tail["cursor"] == reset["cursor"]
    events.append("界" * 100, source="tool")
    large = events.read("activity")["data"][-1]
    assert large["truncated"] and len(large["text"].encode()) <= 32
    # Callers cannot mutate retained records.
    large["text"] = "mutated"
    assert events.read("activity")["data"][-1]["text"] != "mutated"


@pytest.mark.parametrize("view,after,limit", [("unknown", None, 10), ("raw", -1, 10), ("raw", None, 0)])
def test_invalid_event_queries_fail(view, after, limit):
    """Reject invalid cursors and page budgets rather than silently skipping output."""
    with pytest.raises(ValueError):
        EventBuffer().read(view, after=after, limit=limit)


def test_model_echo_once_with_and_without_tui_and_real_log_metadata(tmp_path):
    """Web retains messages through TUI changes; stage INFO and unknown warnings remain distinguishable."""
    host, _ = make_host(tmp_path)
    host.start()
    try:
        host.message_echo("model says INFO GET /api/status", end="")
        host.attach_control("tui-test", messages=True)
        host.message_echo(" while attached")
        host.detach_control("tui-test")
        host.message_echo("after detach")
        owner = OUTPUT_OWNER.set(host.output)
        try:
            with output_context(source="stage"):
                info("Checking stage")
            warning("Unknown diagnostic")
        finally:
            OUTPUT_OWNER.reset(owner)
        activity = host.events.read("activity")["data"]
        model = "".join(row["text"] for row in activity if row["source"] == "model")
        assert model == "model says INFO GET /api/status while attached\nafter detach\n"
        assert any(row["source"] == "stage" and row["level"] == "INFO" and "Checking stage" in row["text"] for row in activity)
        system = host.events.read("system")
        assert not any("model says" in row["text"] for row in system["data"])
        assert system["system_notice"]["level"] == "WARNING"
        assert "while attached" in "".join(host.messages.get_lines())
    finally:
        host.request_shutdown()
        host.wait(3)


def test_service_records_are_owned_classified_once_and_handlers_restored(tmp_path):
    """A service record and its terminal echo produce one classified record in the right instance."""
    logger = logging.getLogger("uvicorn.access")
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    original_level = logger.level
    # Install a terminal handler before acquiring the bridge, matching service logging setup.
    logger.handlers = [logging.StreamHandler(sys.stderr)]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    saved = list(logger.handlers)
    first, _ = make_host(tmp_path / "first")
    second, _ = make_host(tmp_path / "second")
    first.start()
    second.start()
    try:
        # Point the retained handler at the live bridge to exercise echo suppression.
        saved[0].stream = sys.stderr
        owner = OUTPUT_OWNER.set(first.output)
        try:
            logger.info('GET /api/status 200')
        finally:
            OUTPUT_OWNER.reset(owner)
        rows = first.events.read("system")["data"]
        hits = [row for row in rows if "GET /api/status" in row["text"]]
        assert len(hits) == 1 and hits[0]["source"] == "http" and hits[0]["scope"] == "instance"
        assert not second.events.read("system")["data"]
        assert not first.events.read("activity")["data"]
        logger.warning("unowned process log")
        assert second.events.read("system")["data"][-1]["scope"] == "process"
        with output_context(source="stage"):
            print("unowned stage diagnostic")
        assert any("unowned stage" in row["text"] for row in second.events.read("system")["data"])
        assert not second.events.read("activity")["data"]
        assert second.events.read("raw")["data"][-1]["scope"] == "process"
        first.request_shutdown()
        first.wait(3)
        assert ServiceLogHandler.installed
    finally:
        second.request_shutdown()
        second.wait(3)
        assert not ServiceLogHandler.installed
        assert logger.handlers == saved and logger.propagate is False
        logger.handlers = original_handlers
        logger.propagate = original_propagate
        logger.setLevel(original_level)


def test_mcp_tool_results_are_activity_without_a_model_cli_transcript():
    """An external MCP client still exposes tool start/result through the injected runtime sink."""
    from pydantic import BaseModel
    from ucagent.core.tools.uctool import UCTool, to_mcp_tool

    class Arguments(BaseModel):
        """Minimal tool request used without an external model."""
        value: str

    class Echo(UCTool):
        """Return explicit tool output for the MCP conversion boundary."""
        name: str = "event_echo"
        description: str = "Echo a value"
        args_schema: type[BaseModel] = Arguments

        def _run(self, value, **kwargs):
            """Preserve a model-visible value."""
            return value

    events = EventBuffer()
    sink = OUTPUT_SINK.set(events.append)
    try:
        # Call the SDK function directly to exercise conversion without network/model use.
        result = asyncio.run(to_mcp_tool(Echo()).fn(value="tool result"))
        assert result == "tool result"
    finally:
        OUTPUT_SINK.reset(sink)
    rows = events.read("activity")["data"]
    assert [row["kind"] for row in rows] == ["call", "result"]
    assert all(row["source"] == "tool" for row in rows)
    assert "tool result" in rows[-1]["text"]


def test_real_http_access_records_stay_with_their_runtime(tmp_path):
    """Live listener requests retain instance ownership without inheriting a launching operation."""
    import httpx
    from ucagent.interfaces.server.api_cmd import ControlApiServer

    first, runtime = make_host(tmp_path / "http")
    second, _ = make_host(tmp_path / "other")
    runtime.agent.cfg.set_value("cmd_api", {"xpra": {}, "waveform_viewers": {}})
    logger = logging.getLogger("uvicorn.access")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    first.start()
    second.start()
    server = ControlApiServer(first.controller, registry=first.registry, operations=first.operations,
                              services=first.services, host_control=first, port=0, sock="")
    try:
        with output_context(source="command", operation_id="launch-only"):
            assert first.services.start("cmd", lambda: server)["ok"]
        response = httpx.get(server.url() + "/api/events", timeout=3)
        assert response.status_code == 200
        hits = [row for row in first.events.read("system")["data"] if row["source"] == "http"]
        assert hits and any("/api/events" in row["text"] for row in hits)
        assert all(row["scope"] == "instance" and row["operation_id"] is None for row in hits)
        assert not any(row["source"] == "http" for row in second.events.read("system")["data"])
        assert not any("GET /api/events" in row["text"] for row in first.events.read("activity")["data"])
    finally:
        first.request_shutdown()
        first.wait(3)
        second.request_shutdown()
        second.wait(3)
        logger.setLevel(previous_level)


@pytest.mark.parametrize("streaming", [False, True])
def test_langchain_output_distinguishes_model_messages_from_tool_results(streaming):
    """Long answers remain model messages; empty tool-call text never creates fake tool activity."""
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage, ToolMessage
    from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
    from ucagent.util.output import OUTPUT_METADATA

    captured = []

    def echo(text, end="\n"):
        """Observe real backend output metadata without constructing a model client."""
        captured.append({**OUTPUT_METADATA.get(), "text": text + end})

    answer = AIMessage(content="answer " * 300)
    result = ToolMessage(content="tool result", tool_call_id="tool-id")
    values = [("values", {"messages": [answer]}), ("values", {"messages": [answer, result]})]
    frames = [("messages", (answer, {})), *values] if streaming else values
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.vagent = SimpleNamespace(message_echo=echo, is_break=lambda: False)
    backend.agent = SimpleNamespace(stream=lambda *args, **kwargs: iter(frames))
    backend.prepare = lambda: None
    backend.state_record_mesg = lambda message: None
    backend.check_tool_call_error = lambda message: None
    if streaming:
        backend.do_work_stream({}, {})
    else:
        backend.do_work_values({}, {})
    assert any(row["source"] == "model" and row["kind"] == "message" and "answer " in row["text"] for row in captured)
    assert any(row["source"] == "tool" and row["kind"] == "result" and "tool result" in row["text"] for row in captured)
    assert not any(row["kind"] == "call" for row in captured)
