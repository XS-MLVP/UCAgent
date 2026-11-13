"""Real subprocess fixture: consume a scoped MCP endpoint without a LangChain loop."""

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    """Verify task scope, write the private artifact, and submit through HTTP MCP."""
    prompt = Path(os.environ["UCAGENT_WORKER_PROMPT_FILE"]).read_text()
    assert sys.argv[1] in prompt
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + os.environ["UCAGENT_WORKER_MCP_TOKEN"]}) as client:
        async with streamable_http_client(os.environ["UCAGENT_WORKER_MCP_URL"], http_client=client) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert not names & {"Complete", "GoToStage", "SubAgentTool", "Exit", "Check"}
                invalid = await session.call_tool("SubmitTaskResult", {"summary": "forged", "task_id": "other"})
                assert invalid.is_error
                outside = await session.call_tool("EditTextFile", {"path": "out/other.txt", "content": "forged"})
                assert outside.is_error
                target = Path(sys.argv[2])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("evidence " + sys.argv[1])
                Path("unpublished.txt").write_text("private output only")
                result = await session.call_tool("SubmitTaskResult", {"summary": "command " + sys.argv[1]})
                assert not result.is_error, result
                assert json.loads(result.content[0].text)["submitted"]


if __name__ == "__main__":
    asyncio.run(main())
