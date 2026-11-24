#!/usr/bin/env python3
"""Minimal MCP client for the official UCAgent MCP server (no tool bypass).

Every call goes through the server's own registered tools, so stage state,
reference-file registration, Check/Complete and plugin automation stay
authoritative on the server side.

Usage:
    python3 mcp_client.py list
    python3 mcp_client.py call CurrentTips '{}'
    python3 mcp_client.py call ReadTextFile '{"path": "ut_project/README.md"}'
    python3 mcp_client.py tools-schema

A JSON body can be given as '-' to read stdin (for long payloads).
UCA_MCP_CALL_TIMEOUT_SECONDS sets one bounded 1..15000 second call/read budget;
the default is 3600. It does not change the server or builder budget.
"""

import asyncio
import json
import os
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ENDPOINT = os.environ.get("UCA_MCP_URL", "http://127.0.0.1:5010/mcp")


def _render(result):
    """Flatten an MCP CallToolResult into text for logs."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(json.dumps({"type": getattr(item, "type", "unknown")}, ensure_ascii=False))
    if getattr(result, "structuredContent", None):
        parts.append(json.dumps(result.structuredContent, ensure_ascii=False))
    return "\n".join(parts) if parts else json.dumps({"isError": getattr(result, "isError", False)})


async def main():
    """Validate one bounded caller budget before using the official MCP transport/session."""
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    command = sys.argv[1]
    if command not in {"list", "tools-schema", "call"}:
        print(f"unknown command: {command}")
        return 2
    raw_timeout = os.environ.get("UCA_MCP_CALL_TIMEOUT_SECONDS", "3600")
    if not raw_timeout.isdecimal() or len(raw_timeout) > 5 or not 1 <= int(raw_timeout) <= 15000:
        print("UCA_MCP_CALL_TIMEOUT_SECONDS must be an integer in 1..15000")
        return 2
    timeout = int(raw_timeout)
    if command == "call":
        if len(sys.argv) < 3:
            print("call requires a tool name")
            return 2
        name = sys.argv[2]
        raw = sys.argv[3] if len(sys.argv) > 3 else "{}"
        try:
            payload = json.loads(sys.stdin.read() if raw == "-" else raw)
            if not isinstance(payload, dict):
                raise ValueError("tool arguments must be a JSON object")
        except ValueError as error:
            print(f"invalid tool arguments: {error}")
            return 2
    async with (
        httpx2.AsyncClient(timeout=httpx2.Timeout(30.0, read=timeout)) as client,
        streamable_http_client(ENDPOINT, http_client=client) as streams,
    ):
        read, write = streams[0], streams[1]
        async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
            await session.initialize()
            if command == "list":
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(tool.name)
                return 0
            if command == "tools-schema":
                tools = await session.list_tools()
                wanted = sys.argv[2:]
                for tool in tools.tools:
                    if wanted and tool.name not in wanted:
                        continue
                    print(tool.name)
                    print(json.dumps(tool.input_schema, ensure_ascii=False, indent=2))
                return 0
            if command == "call":
                result = await session.call_tool(name, payload, read_timeout_seconds=timeout)
                print(_render(result))
                if getattr(result, "isError", False):
                    return 1
                return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
