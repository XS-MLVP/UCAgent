"""MCP SDK conversion and HTTP client tests using an isolated local server."""

import asyncio
import builtins
import json
import socket
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from ucagent.server.api_mcp import PdbMcpServer
from ucagent.tools.uctool import UCTool, to_mcp_tool
from ucagent.util.config import Config


class EchoArgs(BaseModel):
    """Strict arguments shared by local and MCP echo invocations."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(description="Text to echo")
    count: int = Field(default=1, ge=1, le=3, description="Number of repetitions")


class EchoTool(UCTool):
    """Return structured output through the normal UCAgent dispatch path."""

    name: str = "Echo"
    description: str = "Repeat text up to three times."
    args_schema: type[BaseModel] = EchoArgs

    def _run(self, text: str, count: int = 1) -> dict:
        """Echo the validated input without external files or services."""
        return {"text": text * count}


@pytest.fixture
def mcp_server():
    """Start a real MCP HTTP endpoint on a temporary loopback port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    agent = SimpleNamespace(
        tool_list_base=[EchoTool()],
        tool_list_task=[],
        tool_list_ext=[],
        tool_list_file=[],
        cfg=Config({"mcp_server": {"init_prompt": "MCP test"}, "tools": {}}),
    )
    server = PdbMcpServer(SimpleNamespace(agent=agent), host="127.0.0.1", port=port)
    ok, message = server.start(timeout=5)
    assert ok, message
    try:
        yield server
    finally:
        ok, message = server.stop()
        assert ok, message


def test_mcp_http_discovery_and_call(mcp_server):
    """The SDK client must discover the exact schema and execute a UCAgent tool."""
    async def exercise():
        """Initialize a client session and check both valid and invalid requests."""
        async with streamable_http_client(mcp_server.url() + "/mcp") as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ["Echo"]
                assert tools.tools[0].input_schema == to_mcp_tool(EchoTool()).parameters

                result = await session.call_tool("Echo", {"text": "hello", "count": 2})
                assert not result.is_error
                assert json.loads(result.content[0].text) == {"text": "hellohello"}

                invalid = await session.call_tool("Echo", {"text": "hello", "count": 0})
                assert invalid.is_error
                assert "count" in invalid.content[0].text

    asyncio.run(exercise())


def test_mcp_conversion_preserves_local_defaults_and_validation():
    """Converted tools must preserve defaults, constraints, and strict arguments."""
    tool = EchoTool()
    converted = to_mcp_tool(tool)
    assert tool.invoke({"text": "hello"}) == {"text": "hello"}
    assert asyncio.run(converted.run({"text": "hello"}, context=None)) == {
        "text": "hello",
    }
    for arguments in ({}, {"text": "hello", "typo": True}, {"text": "hello", "count": 4}):
        with pytest.raises(ToolError):
            asyncio.run(converted.run(arguments, context=None))


def test_mcp_conversion_keeps_additional_arguments():
    """Schemas allowing extra arguments must pass them through MCP validation."""
    class FlexibleArgs(BaseModel):
        """Arguments whose additional fields are intentionally part of the input."""
        model_config = ConfigDict(extra="allow")
        text: str = Field(description="Text to echo")

    def echo(text: str, **kwargs) -> dict:
        """Return every received argument for the conversion assertion."""
        return {"text": text, **kwargs}

    tool = StructuredTool.from_function(echo, args_schema=FlexibleArgs)
    converted = to_mcp_tool(tool)
    arguments = {"text": "hello", "details": {"items": [1, 2]}}
    assert converted.parameters["additionalProperties"] is True
    assert asyncio.run(converted.run(arguments, context=None)) == tool.invoke(arguments)


@pytest.mark.parametrize("args_schema", [None, {"type": "object", "properties": {}}])
def test_mcp_conversion_rejects_non_model_schema(args_schema):
    """A missing or dictionary schema must fail with an actionable contract error."""
    class InvalidTool(BaseTool):
        """Minimal tool exposing an unsupported schema for conversion."""
        name: str = "Invalid"
        description: str = "Unsupported schema"

        def _run(self, **kwargs):
            """Provide a callable body without affecting schema validation."""
            return kwargs

    with pytest.raises(ValueError, match="pydantic.BaseModel"):
        to_mcp_tool(InvalidTool(args_schema=args_schema))


def test_mcp_conversion_rejects_injected_arguments():
    """Hidden LangChain arguments must not silently disappear during conversion."""
    class InjectedArgs(BaseModel):
        """Input with a value that requires LangChain injection."""
        text: str = Field(description="Visible text")
        secret: Annotated[str, InjectedToolArg] = Field(description="Injected value")

    def echo(text: str, secret: str) -> str:
        """Return a string only after the runtime has injected the hidden value."""
        return text + secret

    tool = StructuredTool.from_function(echo, args_schema=InjectedArgs)
    with pytest.raises(NotImplementedError, match="injected arguments"):
        to_mcp_tool(tool)


def test_mcp_server_reports_missing_sdk(monkeypatch):
    """A missing current SDK must identify the dependency and installation command."""
    original_import = builtins.__import__

    def without_mcp(name, *args, **kwargs):
        """Simulate a missing SDK without changing the installed environment."""
        if name == "mcp.server.mcpserver":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_mcp)
    with pytest.raises(ImportError, match="mcp>=2.3.0,<3.0"):
        PdbMcpServer(SimpleNamespace())
