"""Offline public CLI protocol fixture; all stage decisions go through real MCP tools."""

import asyncio
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


SESSION = None


def emit(kind, **data):
    """Expose distinct CLI output dialects through configured event fields."""
    if "--dialect-simple" in sys.argv:
        if kind == "thread.started":
            event = {"event": "start", "conversation": data["thread_id"]}
        elif kind == "item.completed":
            event = {"event": "message", "body": data["item"]}
        else:
            event = {"event": "done"}
    elif "--format" in sys.argv:
        if kind == "thread.started":
            event = {"type": "step_start", "sessionID": data["thread_id"]}
        elif kind == "item.completed":
            item = data["item"]
            event = {"type": "text" if item["type"] == "agent_message" else "tool_use",
                     "sessionID": SESSION, "part": item}
        else:
            event = {"type": "step_finish", "sessionID": SESSION, "part": {"reason": "stop"}}
    else:
        event = {"type": kind, **data}
    print(json.dumps(event), flush=True)


async def main():
    """Exercise managed Super/Sub identity, tools, and explicit continuation."""
    global SESSION
    if sys.argv[-3:] == ["mcp", "list", "--json"]:
        owned = next((arg.split(".")[1] for arg in sys.argv if arg.startswith("mcp_servers.ucagent_")), None)
        servers = [{"name": "other_agent", "enabled": owned is None}]
        if owned is not None:
            assert 'mcp_servers={"other_agent"={enabled=false}}' in sys.argv
            servers.append({"name": owned, "enabled": True})
        print(json.dumps(servers))
        return
    if sys.argv[-2:] == ["debug", "config"]:
        result = {"mcp": {"other_agent": {"enabled": True}}}
        if "OPENCODE_CONFIG" in os.environ:
            result = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
        print(json.dumps(result))
        return
    options = sys.argv[1:]
    assert "--last" not in options and "--continue" not in options
    if "--dialect-simple" in options:
        resumed = "--resume-id" in options
        session_id = options[options.index("--resume-id") + 1] if resumed else "conversation-" + uuid4().hex
    elif "--format" in options:
        cfg = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
        name = options[options.index("--agent") + 1]
        assert cfg["mcp"]["other_agent"] == {"enabled": False}
        assert cfg["agent"][name]["permission"] == {"*": "deny", name + "_*": "allow"}
        assert cfg["mcp"][name]["url"] == os.environ["UCAGENT_WORKER_MCP_URL"]
        assert cfg["mcp"][name]["headers"]["Authorization"] == "Bearer {env:UCAGENT_WORKER_MCP_TOKEN}"
        resumed = "--session" in options
        session_id = options[options.index("--session") + 1] if resumed else "ses_" + uuid4().hex
    else:
        assert 'mcp_servers={"other_agent"={enabled=false}}' in options
        assert 'features.shell_tool=false' in options and 'sandbox_mode="read-only"' in options
        assert any('approval_mode="approve"' in arg for arg in options)
        resumed = "resume" in options
        session_id = options[options.index("resume") + 1] if resumed else str(uuid4())
    SESSION = session_id
    emit("thread.started", thread_id=session_id)
    directory = Path(os.environ["UCAGENT_WORKER_SESSION_DIR"])
    with (directory / "invocations.jsonl").open("a") as stream:
        stream.write(json.dumps({"session_id": session_id, "pid": os.getpid(), "resumed": resumed}) + "\n")
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + os.environ["UCAGENT_WORKER_MCP_TOKEN"]}) as client:
        async with streamable_http_client(os.environ["UCAGENT_WORKER_MCP_URL"], http_client=client) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                await session.initialize()
                catalog = (await session.list_tools()).tools
                names = {t.name for t in catalog}
                if "SubAgentTool" in names:
                    schema = next(t.input_schema for t in catalog if t.name == "SubAgentTool")
                    tasks = schema["properties"]["tasks"]["items"]
                    assert tasks["type"] == "object" and {"id", "instruction"} <= set(tasks["required"])

                async def call(name, **arguments):
                    """Require real tool acceptance and expose its public completion event."""
                    result = await session.call_tool(name, arguments)
                    assert not result.is_error, result
                    emit("item.completed", item={"type": "mcp_tool_call", "tool": name})
                    try:
                        return json.loads(result.content[0].text)
                    except json.JSONDecodeError:
                        return result.content[0].text

                tips = await call("CurrentTips")
                if "SubAgentTool" in names:
                    assert not names & {"EditTextFile", "Complete", "SubmitTaskResult"}
                    if tips["stage"] is not None:
                        await call("SubAgentTool", plan_id=f"cli-{tips['stage_index']}",
                                   planning_token=tips["planning_token"],
                                   tasks=[{"id": "work", "instruction": "Complete the authorized stage"}])
                else:
                    assert "SubmitTaskResult" in names and "SubAgentTool" not in names
                    if "Check" not in names:
                        for path in tips["task"]["inputs"]:
                            assert "evidence" in await call("ReadTextFile", path=path)
                        for path in tips["task"]["outputs"]:
                            await call("EditTextFile", path=path, content="evidence")
                        await call("SubmitTaskResult", summary="Produced task output")
                        emit("turn.completed", usage={"input_tokens": 10, "output_tokens": 4})
                        return
                    while not tips["scope_done"]:
                        paths = set(re.findall(r'out/[A-Za-z0-9_.-]+', json.dumps(tips)))
                        assert paths, tips
                        for path in paths:
                            await call("EditTextFile", path=path, content="evidence")
                        await call("SetCurrentStageJournal", journal="Produced required evidence")
                        if tips["next_action"] != "CompleteSubStage":
                            break
                        tips = await call("CompleteSubStage", step_token=tips["step_token"])
                        assert tips["validation"]["complete"], tips
                        if not resumed and not tips["scope_done"]:
                            # A plain assistant reply must cause SAME-session continuation.
                            emit("item.completed", item={"type": "agent_message", "text": "First child complete."})
                            emit("turn.completed", usage={"input_tokens": 10, "output_tokens": 4})
                            return
                    await call("SubmitTaskResult", summary="Completed all authorized steps")
    emit("item.completed", item={"type": "agent_message", "text": "Turn complete."})
    emit("turn.completed", usage={"input_tokens": 10, "output_tokens": 4})


if __name__ == "__main__":
    asyncio.run(main())
