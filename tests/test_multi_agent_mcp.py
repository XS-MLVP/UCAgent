"""Real HTTP MCP and command-process acceptance of the shared multi-agent contracts."""

import asyncio
import json
from pathlib import Path
import sys
import threading
import time

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ucagent.interfaces.server.api_mcp import McpServer, _collect_mcp_tools
from ucagent.interfaces.server.worker_mcp import worker_endpoint
from ucagent.core.multi_agent.worker import WorkerSession
from test_multi_agent import make_agent, parallel_agent, parallel_plan, tool, finish


def test_http_supervisor_queues_five_tasks_with_same_permissions(tmp_path):
    """An external planner uses the production MCP schemas and the same bounded queue."""
    agent = parallel_agent(tmp_path)
    lock, release = threading.Lock(), threading.Event()
    running = peak = 0
    def run(worker):
        """Produce deterministic business work behind the actual HTTP submission path."""
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        assert release.wait(5)
        tool(worker, "EditTextFile", path=worker.record.spec.outputs[0], content="evidence")
        tool(worker, "SubmitTaskResult", summary="HTTP delegate finished")
        with lock:
            running -= 1
    agent.multi_agent.runner_factory = run
    server = McpServer(_collect_mcp_tools(agent, False), cfg=agent.cfg, port=0)
    async def exercise():
        """Discover, submit, repeat idempotently and wait through a real client."""
        async with streamable_http_client(server.url() + "/mcp") as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=10) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {t.name for t in agent.test_tools}
                assert not {"Complete", "EditTextFile", "RunTestCases"} & {t.name for t in tools.tools}
                plan = parallel_plan()
                first = await session.call_tool("SubAgentTool", plan)
                assert not first.is_error, first
                duplicate = await session.call_tool("SubAgentTool", plan)
                assert not duplicate.is_error
                assert len(agent.multi_agent.records) == 5
                release.set()
                result = await session.call_tool("WaitTasks", {"plan_id": "parallel", "timeout": 5})
                assert not result.is_error, result
                data = json.loads(result.content[0].text)
                assert data["plans"]["parallel"]["state"] == "completed", data
                assert data["workflow_state"] == "waiting_plan"
    try:
        ok, msg = server.start()
        assert ok, msg
        asyncio.run(exercise())
        assert peak == 2
    finally:
        release.set()
        assert server.stop()[0]
        agent._startup_cleanup.close()


def test_command_workers_are_parallel_isolated_and_never_use_langchain(tmp_path, monkeypatch):
    """Two real child processes receive different prompts, credentials and private workspaces."""
    helper = Path(__file__).parent / "helpers" / "multi_agent_worker.py"
    roles = {name: {"backend": "command", "system": name + " command prompt",
                    "allowed_tools": ["ReadTextFile", "EditTextFile"],
                    "command": [sys.executable, str(helper), name, f"out/{i}.txt"]}
             for i, name in enumerate(["author", "reviewer"])}
    agent = parallel_agent(tmp_path, count=2, roles=roles)
    agent.multi_agent.endpoint_factory = worker_endpoint
    def forbidden(*args):
        """Make an implicit LangChain worker fallback a hard test failure."""
        raise AssertionError("Command workers must not call LangChain")
    from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
    monkeypatch.setattr(UCAgentLangChainBackend, "prepare", forbidden)
    plan = parallel_plan(count=2)
    plan["tasks"][1]["depends_on"] = []
    plan["tasks"][1]["inputs"] = []
    try:
        agent.multi_agent.submit(plan)
        result = finish(agent.multi_agent, "parallel", 15)
        assert result["plans"]["parallel"]["state"] == "completed", result
        for i, role in enumerate(["author", "reviewer"]):
            assert (tmp_path / f"out/{i}.txt").read_text() == "evidence " + role
            directory = tmp_path / f".ucagent/multi_agent/{agent.session_id.hex}/parallel/t{i}/1"
            assert role + " command prompt" in (directory / "prompt.txt").read_text()
            assert (directory / "workspace/unpublished.txt").exists()
        assert not (tmp_path / "unpublished.txt").exists()
        assert result["tasks"][0]["summary"] != result["tasks"][1]["summary"]
        assert not (tmp_path / ".ucagent/cmdline.txt").exists()
    finally:
        agent._startup_cleanup.close()


def test_worker_endpoint_requires_credential():
    """A nearby process cannot call another worker's endpoint without its bearer credential."""
    from ucagent.util.config import Config
    with worker_endpoint([], Config({})) as endpoint:
        for headers in [{}, {"Authorization": "Bearer wrong"}]:
            response = httpx2.post(endpoint["url"], json={}, headers=headers)
            assert response.status_code == 401


@pytest.mark.parametrize("mode", ["missing_result", "timeout", "cancel"])
def test_command_exit_timeout_and_cancel_are_terminal(tmp_path, mode):
    """The runner requires explicit submission and tears down timed-out process groups."""
    code = "pass" if mode == "missing_result" else "import time; time.sleep(30)"
    agent = make_agent(tmp_path, roles={"worker": {"backend": "command", "system": "worker",
                "allowed_tools": [], "command": [sys.executable, "-c", code]}},
                limits={"worker_timeout_seconds": 1 if mode == "timeout" else 15,
                        "task_max_attempts": 1})
    agent.multi_agent.endpoint_factory = worker_endpoint
    try:
        agent.multi_agent.submit({"plan_id": "process", "tasks": [{"id": "run", "instruction": "test"}]})
        if mode == "cancel":
            deadline = time.monotonic() + 5
            while not (tmp_path / f".ucagent/multi_agent/{agent.session_id.hex}/process/run/1/stdout.log").exists():
                assert time.monotonic() < deadline
                threading.Event().wait(0.01)
            agent.multi_agent.cancel("process")
        result = finish(agent.multi_agent, "process", 10)
        assert result["plans"]["process"]["state"] == "failed", result
        assert result["running"] == 0
        if mode == "missing_result":
            assert "resume_args" in result["tasks"][0]["error"]
        else:
            assert result["tasks"][0]["state"] == "cancelled"
    finally:
        agent._startup_cleanup.close()


def test_disconnected_worker_without_submission_cannot_complete(tmp_path):
    """Closing a genuine initialized MCP session without reporting remains a missing result."""
    code = '''import asyncio, os
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def run():
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + os.environ["UCAGENT_WORKER_MCP_TOKEN"]}) as client:
        async with streamable_http_client(os.environ["UCAGENT_WORKER_MCP_URL"], http_client=client) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                await session.initialize()
                await session.list_tools()
asyncio.run(run())
'''
    agent = make_agent(tmp_path, roles={"worker": {"backend": "command", "system": "disconnect",
                      "allowed_tools": [], "command": [sys.executable, "-c", code]}},
                      limits={"task_max_attempts": 1})
    agent.multi_agent.endpoint_factory = worker_endpoint
    try:
        agent.multi_agent.submit({"plan_id": "disconnect", "tasks": [{"id": "t", "instruction": "disconnect"}]})
        result = finish(agent.multi_agent, "disconnect", 10)
        assert "resume_args" in result["tasks"][0]["error"]
        assert not agent.stage_manager.stages[0].is_completed()
    finally:
        agent._startup_cleanup.close()


def test_mcp_start_runs_real_super_and_continues_after_client_disconnect(tmp_path, monkeypatch):
    """One real HTTP call starts model planning; no external polling drives later stages."""
    from multi_agent_fakes import install_planner
    from test_multi_agent import stage
    value = make_agent(tmp_path, stages=[stage("one", output_files=["out/one.txt"]),
                                         stage("two", output_files=["out/two.txt"])])
    planner = install_planner(value, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def run(worker):
        """Hold the first worker until the external HTTP client has disconnected."""
        entered.set()
        assert release.wait(5)
        path = f"out/{worker.stage_manager.get_current_stage().name}.txt"
        tool(worker, "EditTextFile", path=path, content="evidence")
        tool(worker, "SubmitTaskResult", summary=path)
    value.multi_agent.runner_factory = run
    server = McpServer(_collect_mcp_tools(value, False), cfg=value.cfg, port=0)
    async def start():
        """Start through the actual MCP schema and then close the initiating session."""
        async with streamable_http_client(server.url() + "/mcp") as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                await session.initialize()
                result = await session.call_tool("StartWorkflow", {"instruction": "Run both stages"})
                assert not result.is_error, result
    try:
        assert server.start()[0]
        asyncio.run(start())
        assert entered.wait(4)
        assert len(planner.contexts) == 1
        release.set()
        value.multi_agent.workflow_thread.join(5)
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
        assert len(planner.contexts) == 3
        assert value.get_tool_by_name("SubAgentTool").call_count == 2
    finally:
        release.set()
        server.stop()
        value._startup_cleanup.close()


def test_worker_http_keeps_substages_in_one_session_after_early_result(tmp_path):
    """MCP receives the same recoverable feedback and cannot submit a partial subtree."""
    from test_multi_agent import stage
    agent = make_agent(tmp_path, stages=[stage("root", stage=[
        stage("first", output_files=["out/first.txt"]), stage("second", output_files=["out/second.txt"])])])
    workers = []

    async def exercise(endpoint):
        """Finish both children through the real authenticated task endpoint."""
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + endpoint["token"]}) as client:
            async with streamable_http_client(endpoint["url"], http_client=client) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=5) as session:
                    await session.initialize()
                    result = await session.call_tool("SubmitTaskResult", {"summary": "Premature result"})
                    assert not result.is_error
                    data = json.loads(result.content[0].text)
                    assert data["error_code"] == "SUBSTAGES_REMAIN" and not data["submitted"]
                    token = data["step_token"]
                    for name in ("first", "second"):
                        result = await session.call_tool("EditTextFile", {"path": f"out/{name}.txt", "content": "evidence"})
                        assert not result.is_error
                        result = await session.call_tool("SetCurrentStageJournal", {"journal": f"Produced {name}"})
                        assert not result.is_error
                        result = await session.call_tool("Complete" if name == "first" else "CompleteSubStage",
                                                         {"step_token": token})
                        assert not result.is_error
                        data = json.loads(result.content[0].text)
                        assert data["validation"]["complete"]
                        if name == "first":
                            assert not data["scope_done"]
                            stale = await session.call_tool("CompleteSubStage", {"step_token": token})
                            assert not stale.is_error
                            data = json.loads(stale.content[0].text)
                            assert data["error_code"] == "STALE_STEP_TOKEN"
                            token = data["step_token"]
                    assert data["scope_done"]
                    result = await session.call_tool("SubmitTaskResult", {"summary": "Both children done"})
                    assert not result.is_error and json.loads(result.content[0].text)["submitted"]

    def run(worker):
        """Keep one worker and endpoint alive for the full authorized subtree."""
        workers.append(worker)
        with worker_endpoint(worker.test_tools, worker.cfg) as endpoint:
            asyncio.run(exercise(endpoint))

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "continuous", "tasks": [{"id": "t", "instruction": "Both children"}]})
        result = finish(agent.multi_agent, "continuous", 15)
        assert result["plans"]["continuous"]["state"] == "completed", result
        assert len(workers) == 1 and workers[0].record.attempt == 1
    finally:
        agent._startup_cleanup.close()


def test_worker_http_complete_submits_single_stage_for_final_validation(tmp_path):
    """A normal MCP Complete call uses the worker adapter and waits for the real stage gate."""
    agent = make_agent(tmp_path)
    seen = []

    async def exercise(endpoint):
        """Write actual evidence and finish using the familiar tool name over HTTP."""
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + endpoint["token"]}) as client:
            async with streamable_http_client(endpoint["url"], http_client=client) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=5) as session:
                    await session.initialize()
                    response = await session.call_tool("EditTextFile", {"path": "out/result.md", "content": "evidence"})
                    assert not response.is_error
                    response = await session.call_tool("SetCurrentStageJournal", {"journal": "Actual evidence produced"})
                    assert not response.is_error
                    response = await session.call_tool("Complete", {"timeout": 450, "stage_args": '{"full_output": true}'})
                    assert not response.is_error
                    data = json.loads(response.content[0].text)
                    assert data["submitted"] and data["validation_pending"] and not data["complete"]
                    assert agent.stage_manager.stage_index == 0
                    seen.append(data)

    def run(worker):
        """Keep the bound endpoint and worker alive until the submission reply is consumed."""
        with worker_endpoint(worker.test_tools, worker.cfg) as endpoint:
            asyncio.run(exercise(endpoint))

    agent.multi_agent.runner_factory = run
    try:
        agent.multi_agent.submit({"plan_id": "complete", "tasks": [{"id": "t", "instruction": "Close step"}]})
        result = finish(agent.multi_agent, "complete", 15)
        assert result["plans"]["complete"]["state"] == "completed", result
        assert len(seen) == 1
        record = agent.multi_agent.records["complete/t"]
        assert record.result["timeout"] == 450
        # MCP normalizes JSON-string arguments before dispatching the bound tool.
        assert record.result["stage_args"] == {"full_output": True}
    finally:
        agent._startup_cleanup.close()
