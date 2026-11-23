"""On-demand Super sessions: isolation, budgets, result acceptance and conversation lifetime."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import time
import pytest
from ucagent.core.multi_agent.global_agent.session_contracts import GlobalSettings, SuperRequest, SuperSpec
from ucagent.core.multi_agent.global_agent.service import GlobalAgentService
from ucagent.core.multi_agent.global_agent.result import verify_workflow_run_result
from ucagent.core.tools.global_agent import global_tools
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.runtime.agent_sessions import AgentSessions
from ucagent.interfaces.server.super_launcher import SubprocessSuperLauncher

class Entry:
    unavailable = None
    def __init__(self, inputs=()):
        self.workflow = SimpleNamespace(inputs=dict.fromkeys(inputs, "input"), outputs={"out/result.txt": "result"})
    def describe(self): return {"inputs": self.workflow.inputs, "outputs": self.workflow.outputs}

class Launcher:
    def __init__(self):
        self.starts, self.cancelled = [], []
        self.fail = False
        self.mutate = lambda payload: None
    def start(self, spec, workspace, result_path, instruction, *, attempt=1):
        handle = dict(spec=spec, workspace=Path(workspace), result_path=Path(result_path), attempt=attempt, polls=0, pid=1234)
        self.starts.append(handle)
        return handle
    def poll(self, handle):
        handle["polls"] += 1
        if handle["polls"] < 2: return {"state": "running"}
        if self.fail: return {"state": "exited", "exit_code": 1}
        data = b"verified content"
        path = handle["workspace"] / "out/result.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        payload = dict(agent_id=handle["spec"].agent_id, workflow_ref=handle["spec"].workflow_ref,
                       attempt=handle["attempt"], status="succeeded",
                       stages=[dict(index=0, name="stage", completed=True)],
                       artifacts=[dict(path="out/result.txt", size=len(data), sha256=hashlib.sha256(data).hexdigest())])
        self.mutate(payload)
        handle["result_path"].write_text(json.dumps(payload))
        return {"state": "exited", "exit_code": 0}
    def cancel(self, handle): self.cancelled.append(handle)

@pytest.fixture
def runtime(tmp_path):
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "dut.v").write_text("module dut; endmodule")
    settings = GlobalSettings.model_validate(dict(allowed_workflows=["p:produce", "p:merge"],
        launch_profiles={"standard": {}}, max_parallel_supers=2))
    agent = SimpleNamespace(plugins=[])
    catalog = SimpleNamespace(entries={"p:produce": Entry(), "p:merge": Entry(["inputs/a.txt"])})
    service = GlobalAgentService(agent, settings, catalog=catalog)
    agent.global_service = service
    engine = AgentSessions(service, workspace, launcher=Launcher())
    service.attach_runtime(engine)
    yield engine
    engine.close()

def start(runtime, text="Make a result", request_id="request"):
    return runtime.start_super(SuperRequest(workflow_ref="p:produce", instruction=text), request_id=request_id)["agent_id"]

def complete(runtime):
    for _ in range(3): runtime.tick()

def test_idle_and_multiple_requests(runtime):
    assert not runtime.list_agents()["agents"]
    first = start(runtime)
    complete(runtime)
    assert runtime.agent_status(first)["status"] == "succeeded"
    second = start(runtime, request_id="another-user-message")
    assert second != first
    complete(runtime)
    assert runtime.agent_status(second)["status"] == "succeeded"
    assert not runtime.closed

def test_idempotent_launch_and_isolation(runtime):
    first = start(runtime)
    assert start(runtime) == first
    other = start(runtime, "Make another result")
    runtime.tick()
    a, b = runtime.launcher.starts
    assert a["workspace"] != b["workspace"]
    assert (a["workspace"] / "dut.v").is_file()
    assert not (a["workspace"] / ".ucagent").exists()
    assert len(runtime.list_agents()["agents"]) == 2

@pytest.mark.parametrize("parallel", [1, 2])
def test_concurrency_limit(runtime, parallel):
    runtime.settings.max_parallel_supers = parallel
    for i in range(3): start(runtime, str(i))
    runtime.tick()
    assert len(runtime.handles) == parallel

def test_profile_resource_capacity(runtime):
    runtime.settings.resources = {"sim": 1}
    runtime.settings.launch_profiles["standard"].resources = ["sim"]
    start(runtime, "a"); start(runtime, "b")
    runtime.tick()
    assert len(runtime.handles) == 1

def test_request_budget(runtime):
    runtime.settings.max_runs_per_request = 1
    start(runtime)
    with pytest.raises(ValueError, match="budget"): start(runtime, "another")
    assert start(runtime, "another", request_id="new")

def test_result_driven_followup_and_readonly_inputs(runtime):
    producer = start(runtime)
    with pytest.raises(ValueError, match="not succeeded"):
        runtime.start_super(SuperRequest(workflow_ref="p:merge", instruction="merge", inputs={
            "inputs/a.txt": {"agent_id": producer, "attempt": 1, "path": "out/result.txt"}}))
    complete(runtime)
    consumer = runtime.start_super(SuperRequest(workflow_ref="p:merge", instruction="merge", inputs={
        "inputs/a.txt": {"agent_id": producer, "attempt": 1, "path": "out/result.txt"}}))["agent_id"]
    runtime.tick()
    path = Path(runtime.agent_status(consumer)["workspace"]) / "inputs/a.txt"
    assert path.read_bytes() == b"verified content"
    assert path.stat().st_mode & 0o222 == 0

def test_artifact_read_limit_and_tamper(runtime):
    agent_id = start(runtime); complete(runtime)
    assert runtime.read_agent_artifact(agent_id, 1, "out/result.txt", 4)["truncated"]
    path = Path(runtime.agent_status(agent_id)["workspace"]) / "out/result.txt"
    path.write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        runtime.read_agent_artifact(agent_id, 1, "out/result.txt")

@pytest.mark.parametrize("field,value", [("agent_id", "wrong"), ("workflow_ref", "p:wrong"), ("attempt", 2),
    ("status", "failed"), ("artifacts", []), ("stages", [{"index": 0, "name": "stage", "completed": False}])])
def test_reject_invalid_receipt(runtime, field, value):
    runtime.launcher.mutate = lambda payload: payload.update({field: value})
    agent_id = start(runtime); complete(runtime)
    assert runtime.agent_status(agent_id)["status"] == "failed"

def test_failed_retry_preserves_attempt_and_fences_replays(runtime):
    runtime.launcher.fail = True
    agent_id = start(runtime); complete(runtime)
    before = runtime.agent_status(agent_id)["workspace"]
    runtime.launcher.fail = False
    assert runtime.retry_super(agent_id, 1)["attempt"] == 2
    assert runtime.retry_super(agent_id, 1)["attempt"] == 2
    complete(runtime)
    row = runtime.agent_status(agent_id)
    assert row["status"] == "succeeded" and row["workspace"] != before
    assert row["attempts"][0]["status"] == "failed" and Path(before).exists()

def test_cancel_queued_and_active(runtime):
    queued = start(runtime)
    runtime.cancel_super(queued)
    assert not runtime.launcher.starts
    active = start(runtime, "second")
    runtime.tick(); runtime.cancel_super(active)
    assert len(runtime.launcher.cancelled) == 1
    assert runtime.agent_status(active)["status"] == "cancelled"

def test_source_boundaries(runtime, tmp_path):
    with pytest.raises(ValueError, match="workspace roots"):
        runtime.start_super(SuperRequest(workflow_ref="p:produce", instruction="go", source_workspace=str(tmp_path)))

def test_tools_are_direct_and_mcp_convertible(runtime):
    tools = global_tools(runtime.service.agent)
    assert len(tools) == 9
    from ucagent.interfaces.server.api_mcp import _collect_mcp_tools
    runtime.service.agent.test_tools = tools
    assert _collect_mcp_tools(runtime.service.agent, False) == tools
    assert "SubmitMissionPlan" not in {t.name for t in tools}
    for tool in tools:
        assert to_mcp_tool(tool)
    result = next(t for t in tools if t.name == "StartSuper").invoke({"workflow_ref": "p:produce", "instruction": "go"})
    assert result["status"] == "queued"

def test_launcher_uses_exact_running_package_and_ephemeral_port(runtime):
    launcher = SubprocessSuperLauncher(runtime.settings, runtime.root, runtime.workspace)
    launcher._backend_traits_for = lambda *args: (False, False)
    spec = SuperSpec(agent_id="super-1", workflow_ref="p:produce", instruction="go")
    argv = launcher.build_command(spec, runtime.workspace, runtime.root / "receipt.json", "go")
    import ucagent
    assert argv[1] == str(Path(ucagent.__file__).with_name("__main__.py"))
    assert argv[argv.index("--mcp-server-port") + 1] == "0"
    assert "agent_run.id=super-1" in argv

def test_global_inbox_serializes_and_stays_alive(runtime, tmp_path):
    from test_runtime_host import make_host
    from ucagent.runtime.agent_events import GlobalInbox
    host, _ = make_host(tmp_path / "host", mode="once")
    host.agent_sessions = runtime
    runtime.host = host
    runtime.inbox = GlobalInbox(host, runtime.root, runtime.events)
    seen = []
    def one_loop(text=None):
        seen.append(text)
        if text == "start": start(runtime)
    host.agent.one_loop = one_loop
    host.start(); host.startup.release()
    try:
        runtime.submit_input("start")
        runtime.submit_input("status question")
        deadline = time.monotonic() + 3
        while len(seen) < 3 or runtime.inbox.pending():
            runtime.tick()
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert seen[:2] == ["start", "status question"]
        assert "Super finished" in seen[2]
        assert host.snapshot()["instance"] == "ready"
        runtime.submit_input("another request")
        while seen[-1] != "another request":
            runtime.tick(); time.sleep(.01)
            assert time.monotonic() < deadline
    finally:
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


def test_large_verified_manifest_has_a_bounded_completion_event(runtime):
    """Thousands of outputs cannot turn successful acceptance into a failed inbox delivery."""
    from ucagent.runtime.agent_events import GlobalInbox
    import threading
    runtime.inbox = GlobalInbox(SimpleNamespace(_wake=threading.Event()), runtime.root, runtime.events)
    agent_id = start(runtime)
    artifacts = {f"out/{n}.txt": {"path": f"out/{n}.txt", "size": 1, "sha256": "a" * 64} for n in range(2000)}
    runtime.runs[agent_id]["artifacts"] = artifacts
    runtime._finish(runtime.runs[agent_id], "succeeded")
    event = runtime.events.read()["events"][-1]
    assert event["payload"]["artifact_count"] == 2000 and event["payload"]["artifacts_truncated"]
    assert len(runtime.inbox.items) == 1 and len(runtime.inbox.items[0]["text"]) < 20000
    assert runtime.agent_status(agent_id)["artifacts"] == artifacts
    assert json.loads((runtime.root / "session.json").read_text())["agents"][agent_id]["artifacts"] == artifacts


@pytest.mark.parametrize("kind", ["outside", "cycle", "ignored", "file"])
def test_source_copy_handles_links_without_traversing_generated_state(runtime, tmp_path, kind):
    """Unsafe links fail clearly; ignored runtime trees and safe file links do not recurse."""
    source = runtime.workspace
    if kind == "outside": (source / "link").symlink_to(tmp_path)
    elif kind == "cycle": (source / "link").symlink_to(source)
    elif kind == "ignored":
        (source / ".venv").mkdir()
        (source / ".venv/link").symlink_to(tmp_path)
    else: (source / "link").symlink_to(source / "dut.v")
    agent_id = start(runtime); runtime.tick()
    row = runtime.agent_status(agent_id)
    if kind in {"outside", "cycle"}:
        assert row["status"] == "failed" and "symlink" in row["error"]
        assert not runtime.launcher.starts
    else:
        assert row["status"] == "running"
        assert not (Path(row["workspace"]) / ".venv").exists()
        if kind == "file": assert (Path(row["workspace"]) / "link").read_text() == (source / "dut.v").read_text()


@pytest.mark.parametrize("failed,exit_after", [(False, False), (False, True), (True, True)])
def test_direct_task_waits_for_result_and_global_reply(runtime, tmp_path, failed, exit_after):
    """Exact startup tasks share result delivery and keep the requested lifetime semantics."""
    from test_runtime_host import make_host
    from ucagent.runtime.agent_events import GlobalInbox
    host, _ = make_host(tmp_path / "host", mode="console")
    host.exit_on_completion = exit_after
    host.agent_sessions = runtime
    runtime.host = host
    runtime.inbox = GlobalInbox(host, runtime.root, runtime.events)
    runtime.launcher.fail = failed
    seen = []
    host.agent.one_loop = lambda text=None: seen.append(text)
    host.start(); host.startup.release()
    try:
        result = runtime.start_initial_task(workflow_ref="p:produce", dut_name="DUT", instruction="Exact request")
        assert not seen and not runtime.inbox.items
        assert runtime.runs[result["agent_id"]]["spec"]["instruction"] == "Exact request"
        deadline = time.monotonic() + 4
        while not seen or runtime.inbox.pending() or runtime.has_active():
            runtime.tick()
            assert time.monotonic() < deadline
            time.sleep(.01)
        runtime.tick()
        assert len(seen) == 1 and "Super finished" in seen[0]
        assert "Exact request" in seen[0]
        if exit_after:
            assert host.wait(3)["exit_code"] == int(failed)
        else:
            assert host.snapshot()["instance"] == "ready"
            runtime.submit_input("Next user request")
            while len(seen) < 2:
                runtime.tick()
                assert time.monotonic() < deadline
                time.sleep(.01)
            assert seen[-1] == "Next user request"
    finally:
        host.request_shutdown(); host.wait(3)
