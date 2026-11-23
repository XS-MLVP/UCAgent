"""Worker-owned telemetry and message bodies across local and real MCP execution."""
import asyncio
import json
import threading
from pathlib import Path

import httpx2
import pytest
from langchain_core.messages import ToolMessage
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from test_multi_agent import make_agent, parallel_agent, parallel_plan, stage, tool, finish
from ucagent.core.multi_agent.display import tool_body
from ucagent.interfaces.server.worker_mcp import worker_endpoint
from ucagent.runtime.agent_view import LocalAgentView
from ucagent.runtime.host import RuntimeHost


@pytest.mark.parametrize("value, expected", [
    ({"context": "  exact body\n", "path": "out/a", "count": 9}, "  exact body\n"),
    ({"content": "body", "metadata": {"size": 4}}, "body"),
    ({"context": '{ "context": "literal JSON field", "n": 1 }\n'},
     '{ "context": "literal JSON field", "n": 1 }\n'),
    ({"content": [{"type": "text", "text": '{"context":"MCP body","count":1}'}]}, "MCP body"),
    (ToolMessage(content='{"context":"ToolMessage body","count":1}', tool_call_id="1"), "ToolMessage body"),
    ({"context": "partial", "error": "failed", "next_action": "retry"},
     "partial\nerror: failed\nnext_action: retry"),
    ({"passed": False, "diagnostic": {"error": "missing evidence"}},
     "passed: False\ndiagnostic:\n  error: missing evidence"),
])
def test_tool_body_preserves_literal_content_and_diagnostics(value, expected):
    """Display unwraps envelopes while preserving literal task content and errors."""
    assert tool_body(value) == expected


def test_delegated_subtree_statistics_and_final_state(tmp_path):
    """A completed worker retains only its lease, calls and files after teardown."""
    from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
    agent = make_agent(tmp_path, stages=[stage("parent", output_files=["out/0.txt"], stage=[
        stage("child0", output_files=["out/0.txt"]),
        stage("child1", output_files=["out/1.txt"])]), stage("later")])
    agent.suppress_tool_result_messages = True
    service = agent.multi_agent
    live = []
    echoes = []
    agent.message_echo = lambda text, **kwargs: echoes.append(text)

    def run(worker):
        for i in range(2):
            tips = tool(worker, "CurrentTips")
            tool(worker, "EditTextFile", path=f"out/{i}.txt", content=f"evidence {i}")
            if i == 1:
                reader = next(t for t in worker.test_tools if t.name == "ReadTextFile")
                reply = reader.invoke({"path": "out/0.txt"})
            tool(worker, "SetCurrentStageJournal", journal=f"Produced {i}.txt")
            assert tool(worker, "CompleteSubStage", step_token=tips["step_token"])["validation"]["complete"]
        backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
        backend.vagent = worker
        rendered = backend.format_message(ToolMessage(content=reply if isinstance(reply, str) else json.dumps(reply), name=reader.name, tool_call_id="read"))
        assert "evidence 0" in rendered and '"context"' not in rendered
        assert not any("Tool Call:" in text or "Tool Result:" in text for text in echoes)
        worker.display.scanned_at = 0
        live.append(service.worker_snapshots()[worker.record.key])
        tool(worker, "SubmitTaskResult", summary="Produced both delegated outputs")

    service.runner_factory = run
    try:
        service.submit({"plan_id": "scoped", "tasks": [{"id": "work", "instruction": "complete the subtree"}]})
        result = finish(service, "scoped")
        assert result["plans"]["scoped"]["state"] == "completed", json.dumps(result["events"], indent=2)
        final = service.worker_snapshots()["scoped/work"]
        assert service.records["scoped/work"].worker is None
        for snapshot in [*live, final]:
            rows = snapshot["mission"]["stages"]
            assert len(rows) == 3 and all("later" not in r["name"] for r in rows)
            assert all(r["title"] == agent.stage_manager.stages[r["index"]].title() for r in rows)
            assert {r["path"] for r in snapshot["changed_files"]} == {"out/0.txt", "out/1.txt"}
            counts = {r["name"]: r["call_count"] for r in snapshot["tools"]}
            assert counts["EditTextFile"] == 2 and counts["ReadTextFile"] == 1
            assert "SubAgentTool" not in counts
            assert snapshot["statistics"]["Tool Calls"] == sum(counts.values())
        assert all(r["is_completed"] for r in final["mission"]["stages"])
        assert not any(r["is_hot"] for r in final["tools"])
        assert final["statistics"]["Run Time"] == service.worker_snapshots()["scoped/work"]["statistics"]["Run Time"]
    finally:
        service.close(5)
        agent._startup_cleanup.close()


def test_parallel_mcp_workers_keep_tools_files_and_logs_separate(tmp_path):
    """Real concurrent HTTP tool calls route detail and Console events to their own Sub."""
    roles = {name: {"backend": "codex", "system": name + " task", "allowed_tools": ["ReadTextFile", "EditTextFile"]}
             for name in ("author", "reviewer")}
    agent = parallel_agent(tmp_path, count=2, roles=roles,
                           config_overrides={"agent_run": {"id": "super-a", "attempt": 1}})
    host = RuntimeHost(agent)
    host.start()
    host.attach_control("test-display", messages=True)
    view = LocalAgentView(host, tmp_path / "session", "super-a")
    barrier = threading.Barrier(2)
    returns = {}

    def run(worker):
        task = worker.record.spec.id
        original = worker.invoke
        def logged(action, delegate, arguments):
            host.service_message(f"MCP execution {task}")
            return original(action, delegate, arguments)
        worker.invoke = logged
        barrier.wait(timeout=5)
        async def exercise(endpoint):
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + endpoint["token"]}) as http:
                async with streamable_http_client(endpoint["url"], http_client=http) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=10) as session:
                        await session.initialize()
                        path = worker.record.spec.outputs[0]
                        result = await session.call_tool("EditTextFile", {"path": path, "content": "evidence " + task})
                        assert not result.is_error, result
                        result = await session.call_tool("ReadTextFile", {"path": path})
                        assert not result.is_error, result
                        returns[task] = result.content[0].text
                        result = await session.call_tool("SubmitTaskResult", {"summary": "Produced " + task})
                        assert not result.is_error, result
        with worker_endpoint(worker.test_tools, worker.cfg) as endpoint:
            asyncio.run(exercise(endpoint))

    agent.multi_agent.runner_factory = run
    plan = parallel_plan(count=2)
    plan["tasks"][1].update(depends_on=[], inputs=[])
    try:
        host.service_message("SUPER DIAGNOSTIC")
        agent.multi_agent.submit(plan)
        result = finish(agent.multi_agent, "parallel", 20)
        assert result["plans"]["parallel"]["state"] == "completed", result
        snapshot = view.snapshot()
        events = view.events_since()["events"]
        super_logs = "".join(e["payload"]["text"] for e in events if e["kind"] == "console" and e["agent_id"] == "super-a")
        assert "SUPER DIAGNOSTIC" in super_logs and "MCP execution" not in super_logs
        for i, child in enumerate(sorted(snapshot["children"], key=lambda r: r["task_id"])):
            task = f"t{i}"
            assert child["backend"] == "codex"
            assert {row["path"] for row in child["changed_files"]} == {f"out/{i}.txt"}
            counts = {r["name"]: r["call_count"] for r in child["tools"]}
            assert counts["ReadTextFile"] == counts["EditTextFile"] == counts["SubmitTaskResult"] == 1
            rows = [e for e in events if e["agent_id"] == child["agent_id"]]
            assert rows and all(e["payload"]["worker_attempt"] == 1 for e in rows)
            logs = "".join(e["payload"]["text"] for e in rows if e["kind"] == "console")
            assert f"MCP execution {task}" in logs and f"MCP execution t{1-i}" not in logs
            assert "SUPER DIAGNOSTIC" not in logs
            details = [e["payload"]["text"] for e in rows if e["kind"] == "tool_detail"]
            read_result = next(text for text in details if "Tool Result: ReadTextFile" in text)
            assert "evidence " + task in read_result
            assert '"context"' not in read_result and "count:" not in read_result
            assert read_result.rstrip().endswith(returns[task].rstrip())  # Actual tool reply remains unchanged.
    finally:
        agent.multi_agent.close(10)
        view.close()
        host.request_shutdown()
        assert host.wait(10)["instance"] == "closed"
