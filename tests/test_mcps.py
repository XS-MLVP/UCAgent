#coding=utf-8

import asyncio
from typing import Dict, Any, Optional
from fastmcp import Client
from fastmcp import FastMCP, Context
import anyio


class FastMCPClientTestHelper:
    def __init__(self, server_url: str = "http://localhost:5000", timeout:int=500):
        self.server_url = server_url + "/mcp"
        self.client: Optional[Client] = None
        self.client = Client(self.server_url, timeout=timeout)

    async def list_tools(self) -> Dict[str, Any]:
        try:
            if not self.client:
                if not await self.initialize_client():
                    return {"error": "initialization failed"}
            async with self.client:
                return await self.client.list_tools()
        except Exception as e:
            print(f"Error listing tools: {e}")
            return None

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not self.client:
                if not await self.initialize_client():
                    return {"error": "initialization failed"}
            async with self.client:
                return await self.client.call_tool(tool_name, arguments)
        except Exception as e:
            print(f"Error calling tool {tool_name}: {e}")
            return None

mcp = FastMCP("ProgressDemo")

@mcp.tool
async def process_items(ctx: Context) -> dict:
    """Process a list of items with progress updates."""
    for i in range(60):
        if i % 2 == 0:
            try:
                await ctx.info({"msg": f"Processing item {i+1}/60"})
            except Exception as e:
                print(f"Failed to send keepalive at step {i+1}: {e}")
                return {"data": False}
        await anyio.sleep(1)
        print(f"Processing item {i+1}/60")
    try:
        await ctx.info({"msg": "Processing completed!"})
    except Exception as e:
        print(f"Failed to send completion message: {e}")
    return {"data": "success"}


async def test_fastmcp_client():
    client = FastMCPClientTestHelper("http://127.0.0.1:5000", timeout=5)
    tools = await client.list_tools()
    print("Available tools:", tools)
    data = await client.call_tool("process_items", {})
    print("Tool call result:", data)


async def test_fastmcp_call():
    client = FastMCPClientTestHelper()
    data = await client.call_tool("ReadTextFile", {"path": "unity_test/Adder_bug_analysis.md"})
    print("return:", data)


if __name__ == "__main__":
    import sys
    target = "test"
    if len(sys.argv) > 1:
        target = sys.argv[-1]
    if target == "test":
        asyncio.run(test_fastmcp_call())
    elif target == "server":
        import uvicorn
        app = mcp.streamable_http_app()
        uvicorn.run(app,
                host="127.0.0.1",
                port=5000)
    elif target == "client":
        asyncio.run(test_fastmcp_client())
    else:
        print("Unknown target. Use 'test', 'server', or 'client'.")
