"""Multi-agent mode, real stage gates, scoped tools, queues and bounded execution."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from pathlib import Path

import pytest

from multi_agent_fakes import install_planner
from ucagent import VerifyAgent
from ucagent.core.multi_agent.contracts import Settings, load_settings
from ucagent.core.backends.langchain.middleware.execution import ExecutionBudget
from ucagent.core.multi_agent.service import MultiAgentService
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.interfaces.server.api_mcp import _collect_mcp_tools
from ucagent.util.config import Config


def stage(name, **extra):
    """Build a real stage with a deterministic gate and no external dependencies."""
    return dict(name=name, desc="Produce evidence", task=["Write the assigned output and submit"], **extra)


def make_agent(tmp_path, *, stages=None, multi=True, config_overrides=None, **settings):
    """Use production construction with framework-only resources in a temporary workspace."""
    cfg = {
        "workflow": None, "backend.key_name": "blank", "langfuse.enable": False,
        "skill.use_skill": False, "runtime_options.multi_agent_enabled": multi,
        "output": "out", "write_dirs": ["out"], "un_write_dirs": [], "template": None,
        "stage": stages or [stage("one", output_files=["out/result.md"])],
        "vmanager.llm_suggestion.check_fail_refinement.enable": False,
        "vmanager.llm_suggestion.check_pass_refinement.enable": False,
    }
    cfg.update({"multi_agent." + key: value for key, value in settings.items()})
    cfg.update(config_overrides or {})
    if cfg["backend.key_name"] == "blank":
        if "multi_agent.roles" in cfg:
            cfg["multi_agent.roles"] = {name: {"backend": "langchain", **role}
                                       for name, role in cfg["multi_agent.roles"].items()}
        else:
            cfg["multi_agent.roles.worker.backend"] = "langchain"
    config_file = tmp_path / "test-launch.yaml"
    config_file.write_text("workflow: null\n")
    agent = VerifyAgent(str(tmp_path), "DUT", None, config_file=str(config_file), cfg_override=cfg,
                        no_embed_tools=True, no_history=True)
    return agent


@pytest.fixture
def agent(tmp_path):
    """Close all worker ownership before restoring prepared resources."""
    value = make_agent(tmp_path)
    yield value
    assert value.multi_agent.close(5)["closed"]
    value._startup_cleanup.close()


def tool(worker, name, **kwargs):
    """Invoke an actual bound tool, retaining its schema and capability checks."""
    return next(item for item in worker.test_tools if item.name == name).invoke(kwargs)


def finish(service, plan_id, timeout=5):
    """Require terminal plan state within a bounded test deadline."""
    result = service.wait(plan_id, timeout)
    assert result["plans"][plan_id]["state"] != "running", result
    return result


def test_single_mode_and_configuration_validation(tmp_path):
    """Default/single construction never reads unused role files or creates workers."""
    cfg = Config({"runtime_options": {"multi_agent_enabled": False},
                  "multi_agent": {"roles": {"bad": {"system_file": "missing"}}}})
    assert load_settings(cfg, tmp_path) is None
    cfg.set_value("runtime_options.multi_agent_enabled", "false")
    with pytest.raises(ValueError, match="boolean"):
        load_settings(cfg, tmp_path)
    single = make_agent(tmp_path, multi=False, max_workers=0)
    try:
        assert not hasattr(single, "multi_agent")
        assert "Complete" in {t.name for t in single.test_tools}
    finally:
        single._startup_cleanup.close()
    with pytest.raises(ValueError):
        Settings.model_validate({"max_workers": 0, "roles": {}})


def test_cli_override_and_max_limit(tmp_path):
    """Mode has one resolved source and explicit concurrency cannot be ignored in single mode."""
    from ucagent.interfaces.cli.arguments import get_args
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent.application.preparation import prepare_launch
    from ucagent.application.plan import LaunchRequest
    config = tmp_path / "launch.yaml"
    config.write_text("workflow: null\nbackend: {key_name: blank}\nruntime_options: {multi_agent_enabled: true}\nmulti_agent: {roles: {worker: {backend: langchain}}}\n")
    args = get_args([str(tmp_path), "DUT", "--config", str(config), "--agent-mode", "single"])
    prepared, _, _ = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    assert prepared.cfg.get_value("runtime_options.multi_agent_enabled") is False
    args = get_args([str(tmp_path), "DUT", "--config", str(config), "--max-subagents", "2"])
    prepared, _, _ = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    assert prepared.cfg.get_value("multi_agent.max_workers") == 2
    args = get_args([str(tmp_path), "DUT", "--agent-mode", "single", "--max-subagents", "2"])
    with pytest.raises(ValueError, match="multi mode"):
        parse_launch_options(args)


def test_delegate_submission_freezes_tools_and_preserves_gate(agent):
    """A real worker writes, reports once, and cannot mutate after relinquishing its lease."""
    workers = []
    def run(worker):
        """Produce the required artifact through the worker's managed write tool."""
        workers.append(worker)
        names = {t.name for t in worker.test_tools}
        assert not names & {"GoToStage", "Exit", "SubAgentTool"}
        assert next(t for t in worker.test_tools if t.name == "Complete").worker is worker
        tool(worker, "EditTextFile", path="out/result.md", content="real evidence")
        tool(worker, "SubmitTaskResult", summary="Created result.md")
        with pytest.raises(PermissionError, match="stopped"):
            tool(worker, "EditTextFile", path="out/result.md", content="late write")
    service = agent.multi_agent
    service.runner_factory = run
    service.submit({"plan_id": "one", "tasks": [{"id": "work", "instruction": "write evidence"}]})
    result = finish(service, "one")
    assert result["plans"]["one"]["state"] == "completed", result
    assert (Path(agent.workspace) / "out/result.md").read_text() == "real evidence"
    assert result["tasks"][0]["summary"] == "Created result.md"
    assert workers[0].closed
    assert service.status()["workflow_state"] == "waiting_plan"
    assert "EditTextFile" not in {t.name for t in agent.test_tools}
    assert {t.name for t in _collect_mcp_tools(agent, False)} == {t.name for t in agent.test_tools}
    for entry in agent.test_tools:
        assert to_mcp_tool(entry).parameters is not None
    with pytest.raises(PermissionError):
        agent.stage_manager.complete(1)


@pytest.mark.parametrize("group", [False, True])
def test_subtree_continuous_scope_and_automatic_workflow(tmp_path, group, monkeypatch):
    """One session completes descendants, rejects stale tokens and never enters the next root."""
    children = [stage(f"child{i}", output_files=[f"out/{i}.txt"]) for i in range(3)]
    root = stage("parent", stage=children, **({} if group else {"output_files": ["out/0.txt"]}))
    value = make_agent(tmp_path, stages=[root, stage("next", output_files=["out/next.txt"])])
    install_planner(value, monkeypatch)
    sessions, visited = [], []
    def run(worker):
        """Exercise real Complete gates, including a failing descendant before repair."""
        sessions.append(worker.thread_id)
        if worker.record.lease.steps:
            for i in range(3):
                current = tool(worker, "CurrentTips")
                visited.append(worker.stage_manager.stage_index)
                if i == 1:
                    failed = tool(worker, "CompleteSubStage", step_token=current["step_token"])
                    assert not failed["validation"].get("complete")
                    assert worker.stage_manager.stage_index == 1
                    current = tool(worker, "CurrentTips")
                tool(worker, "EditTextFile", path=f"out/{i}.txt", content=f"evidence{i}")
                tool(worker, "SetCurrentStageJournal", journal=f"Created {i}.txt")
                outcome = tool(worker, "CompleteSubStage", step_token=current["step_token"])
                assert outcome["validation"]["complete"], outcome
                stale = tool(worker, "CompleteSubStage", step_token=current["step_token"])
                assert stale["error_code"] == "STALE_STEP_TOKEN"
                assert not stale["validation"]["complete"]
            assert outcome["scope_done"]
            with pytest.raises(PermissionError):
                tool(worker, "CompleteSubStage", step_token=worker.record.lease.token)
            with pytest.raises(PermissionError):
                tool(worker, "EditTextFile", path="out/next.txt", content="too early")
        else:
            tool(worker, "EditTextFile", path="out/next.txt", content="next")
        tool(worker, "SubmitTaskResult", summary="Authorized scope done")
    value.multi_agent.runner_factory = run
    try:
        value.one_loop()
        assert value.multi_agent.workflow_state == "completed", json.dumps(value.multi_agent.status(), indent=2, default=str)
        assert visited == [0, 1, 2]
        assert len(sessions) == 2 and len(set(sessions)) == 2
        assert all(s.is_completed() for s in value.stage_manager.stages)
    finally:
        value._startup_cleanup.close()


def parallel_plan(count=5, plan_id="parallel", offset=0):
    """Build disjoint tasks with a real dependency and trusted contract references."""
    return {"plan_id": plan_id, "scope": "task", "tasks": [
        {"id": f"t{i}", "instruction": f"write {i}", "role": "author" if i % 2 == 0 else "reviewer",
         "contract": f"c{i}", "outputs": [f"out/{i}.txt"],
         "depends_on": [f"t{offset}"] if i == offset + count - 1 and count > 1 else [],
         "inputs": [f"out/{offset}.txt"] if i == offset + count - 1 and count > 1 else []}
        for i in range(offset, offset + count)]}


def parallel_agent(tmp_path, count=5, **settings):
    """Provide role-specific prompts and independent file contracts."""
    roles = {name: {"system": prompt, "allowed_tools": ["ReadTextFile", "EditTextFile"]}
             for name, prompt in [("author", "author prompt"), ("reviewer", "review prompt")]}
    roles.update(settings.pop("roles", {}))
    contracts = {f"c{i}": {"rules": [{"path": f"out/{i}.txt", "contains": ["evidence"]}]}
                 for i in range(count)}
    return make_agent(tmp_path, stages=[stage("parallel", output_files=[f"out/{i}.txt" for i in range(count)])],
                      max_workers=2, default_role="author", roles=roles, task_contracts=contracts, **settings)


def test_bounded_queue_roles_dependencies_idempotency_and_tools(tmp_path):
    """Five logical tasks run without truncation and dependencies unlock only on validation."""
    value = parallel_agent(tmp_path)
    running = peak = 0
    lock = threading.Lock()
    release = threading.Event()
    sessions, prompts = [], set()
    def run(worker):
        """Keep the first pair live long enough to observe the shared concurrency cap."""
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            sessions.append(worker)
            prompts.add(worker.record.role.system)
        assert release.wait(4)
        assert not {"Check", "CompleteSubStage"} & {t.name for t in worker.test_tools}
        if worker.record.spec.depends_on:
            assert value.multi_agent.records["parallel/t0"].state == "verified"
        with pytest.raises(PermissionError):
            tool(worker, "EditTextFile", path="out/other.txt", content="illegal")
        tool(worker, "EditTextFile", path=worker.record.spec.outputs[0], content="evidence")
        tool(worker, "SubmitTaskResult", summary="Produced evidence")
        with lock:
            running -= 1
    value.multi_agent.runner_factory = run
    plan = parallel_plan()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(value.multi_agent.submit, [plan, plan]))
        assert len(value.multi_agent.records) == 5
        release.set()
        result = finish(value.multi_agent, "parallel")
        assert result["plans"]["parallel"]["state"] == "completed", result
        assert peak == 2 and len(sessions) == 5
        assert prompts == {"author prompt", "review prompt"}
        assert len({id(s.test_tools[0]) for s in sessions}) == 5
        assert len({s.thread_id for s in sessions}) == 5
    finally:
        release.set()
        value._startup_cleanup.close()


@pytest.mark.parametrize("fault", ["role", "cycle", "output", "dependency", "path"])
def test_plan_validation_rejects_unsafe_work_before_start(tmp_path, fault):
    """Malformed plans never acquire a lease or leave partially admitted tasks."""
    value = parallel_agent(tmp_path)
    plan = parallel_plan()
    if fault == "role":
        plan["tasks"][0]["role"] = "unknown"
    elif fault == "cycle":
        plan["tasks"][0]["depends_on"] = ["t4"]
    elif fault == "output":
        plan["tasks"][1]["outputs"] = ["out/0.txt"]
    elif fault == "dependency":
        plan["tasks"][1]["inputs"] = ["out/0.txt"]
    else:
        plan["tasks"][0]["inputs"] = ["../escape"]
    try:
        with pytest.raises((ValueError, PermissionError)):
            value.multi_agent.submit(plan)
        assert not value.multi_agent.records
        assert value.multi_agent.driver.active_lease is None
    finally:
        value._startup_cleanup.close()


def test_cancel_retains_slot_and_late_result_is_rejected(agent):
    """Cancellation is acknowledged only after the actual runner has returned."""
    entered, release = threading.Event(), threading.Event()
    def run(worker):
        """Represent a network call that cannot be interrupted instantly."""
        entered.set()
        assert release.wait(4)
        with pytest.raises(PermissionError):
            tool(worker, "SubmitTaskResult", summary="late")
    service = agent.multi_agent
    service.runner_factory = run
    service.submit({"plan_id": "cancel", "tasks": [{"id": "t", "instruction": "wait"}]})
    assert entered.wait(3)
    service.cancel("cancel")
    assert service.status()["running"] == 1
    assert not service.close(0)["closed"]
    release.set()
    result = finish(service, "cancel")
    assert result["tasks"][0]["state"] == "cancelled"
    assert not agent.stage_manager.stages[0].is_completed()


def test_budget_and_constructor_failure_release_capacity(agent, monkeypatch):
    """Logical budgets do not reset on retries; early errors cannot leak worker slots."""
    service = agent.multi_agent
    service.settings.limits.worker_tool_calls = 1
    def loop(worker):
        """Exhaust the tool budget on harmless reads."""
        tool(worker, "CurrentTips")
        tool(worker, "CurrentTips")
    service.runner_factory = loop
    service.submit({"plan_id": "budget", "tasks": [{"id": "t", "instruction": "loop"}]})
    result = finish(service, "budget")
    assert result["tasks"][0]["attempt"] == 1
    assert result["tasks"][0]["state"] == "cancelled"
    assert service.status()["running"] == 0
    def broken(*args):
        """Fail before any runner cleanup object exists."""
        raise RuntimeError("construction failed")
    monkeypatch.setattr("ucagent.core.multi_agent.worker.WorkerSession", broken)
    service.submit({"plan_id": "broken", "tasks": [{"id": "t", "instruction": "run"}]})
    result = finish(service, "broken")
    assert result["tasks"][0]["attempt"] == 2
    assert "construction failed" in result["tasks"][0]["error"]
    assert service.status()["running"] == 0


def test_model_budget_and_submission_stop(agent):
    """Production middleware ends submitted graphs before another model call."""
    from ucagent.core.multi_agent.worker import WorkerSession
    from ucagent.core.multi_agent.service import TaskRecord
    from ucagent.core.multi_agent.contracts import TaskSpec
    service = agent.multi_agent
    lease = service.driver.acquire("stage")
    record = TaskRecord("p/t", TaskSpec(id="t", instruction="work"), "p", lease, False,
                        service.settings.roles["worker"])
    worker = WorkerSession(service, record)
    middleware = ExecutionBudget(session=worker)
    service.settings.limits.worker_model_rounds = 1
    assert middleware.before_model({}, None) is None
    with pytest.raises(RuntimeError, match="model-round"):
        middleware.before_model({}, None)
    record.result = {"summary": "done"}
    assert middleware.before_model({}, None) == {"jump_to": "end"}
    service.driver.release(lease)


def test_real_langchain_graph_uses_independent_worker_sessions(agent, monkeypatch):
    """Run the actual LangChain graph with scripted model responses and real tools."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    import ucagent.core.backends.langchain.agent as backend_module
    class ScriptedModel(FakeMessagesListChatModel):
        """Bind tools without a network service; responses exercise the production graph."""
        def bind_tools(self, tools, **kwargs):
            """Keep the fake response sequence and accept the graph's tool contract."""
            return self
        def get_num_tokens_from_messages(self, messages, tools=None):
            """Avoid optional tokenizer downloads for the deterministic model fixture."""
            return 20
    responses = [
        AIMessage(content="", tool_calls=[{"name": "EditTextFile", "args": {"path": "out/result.md", "content": "graph evidence"}, "id": "write"}]),
        AIMessage(content="", tool_calls=[{"name": "SubmitTaskResult", "args": {"summary": "graph completed"}, "id": "submit"}]),
        AIMessage(content="SHOULD NOT EXECUTE"),
    ]
    models = []
    def model_factory(*args, **kwargs):
        """Allocate each worker/summary model separately like the provider factory."""
        model = ScriptedModel(responses=responses)
        models.append(model)
        return model
    monkeypatch.setattr(backend_module, "get_chat_model", model_factory)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    agent.multi_agent.submit({"plan_id": "graph", "tasks": [{"id": "work", "instruction": "write evidence"}]})
    result = finish(agent.multi_agent, "graph")
    assert result["plans"]["graph"]["state"] == "completed", result
    assert agent.multi_agent.records["graph/work"].rounds == 2
    assert len(models) == 2 and models[0] is not models[1]


def test_human_review_and_resume_with_runtime_coordinator(tmp_path, monkeypatch):
    """A real host accepts review only after writers stop, then resumes the same stage gate."""
    from ucagent.runtime.host import RuntimeHost
    from ucagent.runtime.control.commands import CommandSession
    value = make_agent(tmp_path, stages=[stage("human", need_human_check=True, output_files=["out/result.md"])])
    install_planner(value, monkeypatch)
    def run(worker):
        """Produce evidence but leave human approval to the existing control surface."""
        tool(worker, "EditTextFile", path="out/result.md", content="human evidence")
        tool(worker, "SubmitTaskResult", summary="Ready for review")
    value.multi_agent.runner_factory = run
    host = RuntimeHost(value, mode="service")
    host.attach_control("test")
    host.start()
    try:
        session = CommandSession(tmp_path)
        operation = host.registry.execute("continue", session).data
        result = host.operations.wait(operation["id"], 5)
        assert result["state"] == "succeeded", result
        assert value.multi_agent.workflow_state == "waiting_human", value.multi_agent.status()
        assert not value.stage_manager.stages[0].is_completed()
        snapshot = host.controller.stage_state()
        host.controller.review_stage(0, snapshot["control_revision"], True, "Evidence accepted")
        operation = host.registry.execute("continue", session).data
        result = host.operations.wait(operation["id"], 5)
        assert result["state"] == "succeeded", result
        assert value.multi_agent.workflow_state == "completed", value.multi_agent.status()
    finally:
        host.request_shutdown()
        assert host.wait(5)["instance"] == "closed"


def test_two_plans_share_capacity_and_output_ownership(tmp_path):
    """Separate simultaneous submissions join one lease and never get separate slot limits."""
    value = parallel_agent(tmp_path, count=4)
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    running = peak = 0
    def run(worker):
        """Hold two running writers while a second plan is admitted."""
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            if running == 2:
                entered.set()
        assert release.wait(4)
        tool(worker, "EditTextFile", path=worker.record.spec.outputs[0], content="evidence")
        tool(worker, "SubmitTaskResult", summary="done")
        with lock:
            running -= 1
    value.multi_agent.runner_factory = run
    first = parallel_plan(count=2, plan_id="first")
    second = parallel_plan(count=2, plan_id="second", offset=2)
    for plan in [first, second]:
        for task in plan["tasks"]:
            task["depends_on"], task["inputs"] = [], []
    try:
        value.multi_agent.submit(first)
        assert entered.wait(3)
        value.multi_agent.submit(second)
        assert value.multi_agent.status()["running"] == 2
        conflict = parallel_plan(count=1, plan_id="conflict")
        with pytest.raises(ValueError, match="conflict"):
            value.multi_agent.submit(conflict)
        release.set()
        for name in ["first", "second"]:
            assert finish(value.multi_agent, name)["plans"][name]["state"] == "completed"
        assert peak == 2 and len(value.multi_agent.records) == 4
    finally:
        release.set()
        value._startup_cleanup.close()


def test_batch_gate_remains_in_same_stage(tmp_path):
    """Delegation retains the original Checker batch owner until every batch passes."""
    from test_runtime_stage_control import build_runtime
    runtime = build_runtime(tmp_path, batch=True)
    agent = runtime.agent
    agent.cfg.set_value("write_dirs", ["out"])
    agent.cfg.set_value("tools", {})
    agent.cfg.set_value("conversation_summary", {})
    agent.dut_name = "DUT"
    agent.plugins = []
    agent.message_echo = lambda *args, **kwargs: None
    runtime.manager.stages[0].do_set_hmcheck_needed(False)
    settings = Settings.model_validate({"roles": {"worker": {"system": "work", "allowed_tools": []}}})
    service = MultiAgentService(agent, settings)
    agent.multi_agent = service
    observed = []
    def run(worker):
        """Consume the real batch feedback and repair the next required batch."""
        observed.append(runtime.manager.stage_index)
        runtime.gate.generated = ["a"] if worker.record.attempt == 1 else ["a", "b"]
        tool(worker, "SetCurrentStageJournal", journal="Processed batch evidence")
        tool(worker, "SubmitTaskResult", summary="batch ready")
    service.runner_factory = run
    try:
        service.submit({"plan_id": "batch", "scope": "stage", "tasks": [{"id": "t", "instruction": "batch"}]})
        result = finish(service, "batch")
        assert result["plans"]["batch"]["state"] == "completed", json.dumps(result, indent=2)
        assert observed == [0, 0]
        assert runtime.manager.stage_index == 1
    finally:
        assert service.close(3)["closed"]
        assert runtime.owner.close(3)["closed"]


def test_new_plan_id_cannot_refresh_exhausted_logical_budget(agent):
    """Renaming a failed delegation leaves the same target's model/tool/time budget spent."""
    service = agent.multi_agent
    service.settings.limits.worker_tool_calls = 1
    def run(worker):
        """Consume the target budget without a successful result."""
        tool(worker, "CurrentTips")
        tool(worker, "CurrentTips")
    service.runner_factory = run
    for name in ["first", "renamed"]:
        service.submit({"plan_id": name, "tasks": [{"id": name, "instruction": "same target"}]})
        result = finish(service, name)
        assert result["tasks"][0]["state"] == "cancelled"
    first, second = service.records.values()
    assert first.budget is second.budget
    assert first.deadline == second.deadline
    assert first.calls == 3


def test_role_files_and_model_overrides_are_resolved_without_widening_policy(tmp_path):
    """Relative role prompts resolve in the workspace and model overrides cannot edit policy."""
    from ucagent.core.multi_agent.contracts import Role
    (tmp_path / "role.md").write_text("custom role prompt")
    cfg = Config({"runtime_options": {"multi_agent_enabled": True}, "multi_agent": {
        "roles": {"worker": {"system_file": "role.md"}}}})
    assert load_settings(cfg, tmp_path).roles["worker"].system == "custom role prompt"
    with pytest.raises(ValueError, match="model_overrides"):
        Role(system="role", model_overrides={"write_dirs": ["."]})


def test_background_driver_survives_mcp_client_turn_and_host_shutdown(tmp_path, monkeypatch):
    """A managed driver keeps host ownership until the actual background writer exits."""
    from ucagent.runtime.host import RuntimeHost
    value = make_agent(tmp_path)
    install_planner(value, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def run(worker):
        """Retain a non-interruptible task until the test acknowledges cancellation."""
        entered.set()
        assert release.wait(5)
    value.multi_agent.runner_factory = run
    host = RuntimeHost(value, mode="service", shutdown_timeout=0.01)
    host.start()
    try:
        value.get_tool_by_name("StartWorkflow").invoke({})
        assert entered.wait(3)
        assert host.snapshot()["instance"] == "ready"
        host.request_shutdown()
        assert host.wait(0.05)["instance"] == "closing"
        assert value.multi_agent.status()["running"] == 1
        release.set()
        assert host.wait(5)["instance"] == "closed"
    finally:
        release.set()
        host.request_shutdown()
        host.wait(5)


@pytest.mark.parametrize("use_skill", [False, True])
def test_worker_skill_evidence_uses_original_stage_gate(tmp_path, use_skill):
    """Skill-disabled tasks need no files; enabled tasks retain real list/read/check evidence."""
    if use_skill:
        skill = tmp_path / ".ucagent/skills/probe/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: probe\ndescription: Verify evidence.\n---\nRead the assigned input.\n")
    value = make_agent(tmp_path, stages=[stage("skill", skill_list=["probe"], output_files=["out/result.md"])],
                       config_overrides={"skill.use_skill": use_skill})
    seen = []
    def run(worker):
        """Exercise forced skill rejection first, then record only actual tool evidence."""
        tool(worker, "EditTextFile", path="out/result.md", content="skill evidence")
        names = {t.name for t in worker.test_tools}
        if use_skill:
            assert "ListSkill" in names
            if worker.record.attempt > 1:
                tool(worker, "ListSkill")
                tool(worker, "ReadTextFile", path=".ucagent/skills/probe/SKILL.md")
                tool(worker, "Check")
                tool(worker, "SetSkillUsage", skill_usage={"probe": {
                    "list": True, "read": True, "use": False, "reason": "No applicable object in this stage"}})
            seen.append(dict(worker.stage_manager.get_current_stage().skill_list))
        else:
            assert not names & {"ListSkill", "SetSkillUsage", "RunSkillScript"}
        tool(worker, "SubmitTaskResult", summary="evidence ready")
    value.multi_agent.runner_factory = run
    try:
        value.multi_agent.submit({"plan_id": "skill", "tasks": [{"id": "t", "instruction": "work"}]})
        result = finish(value.multi_agent, "skill")
        assert result["plans"]["skill"]["state"] == "completed", result
        if use_skill:
            assert len(seen) == 2
            assert seen[0]["probe"] == [False, False, False]
            assert seen[1]["probe"][:2] == [True, True]
    finally:
        value._startup_cleanup.close()


def test_managed_supervisor_stops_graph_after_plan_submission(tmp_path, monkeypatch):
    """The real supervisor graph delegates once and never calls a follow-up model while waiting."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    import ucagent.core.backends.langchain.agent as backend_module
    class PlannerModel(FakeMessagesListChatModel):
        """Return a structured plan through the production tool dispatch."""
        def bind_tools(self, tools, **kwargs):
            """Verify that the model cannot obtain business or navigation tools."""
            assert not {"EditTextFile", "Complete", "Exit", "RunTestCases"} & {t.name for t in tools}
            return self
        def get_num_tokens_from_messages(self, messages, tools=None):
            """Keep the test independent of downloaded tokenizers."""
            return 20
    value = make_agent(tmp_path, config_overrides={"backend.key_name": "langchain"})
    planner = PlannerModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "SubAgentTool", "args": {"plan_id": "planned", "tasks": [{"id": "t", "instruction": "write"}]},
        "id": "plan"}]), AIMessage(content="All stage checks passed.")])
    monkeypatch.setattr(backend_module, "get_chat_model", lambda *args, **kwargs: planner)
    monkeypatch.setattr(backend_module, "negotiate_openai_api_mode", lambda cfg, **kwargs: None)
    def run(worker):
        """Satisfy the declared output through the delegated worker tools."""
        tool(worker, "EditTextFile", path="out/result.md", content="delegated evidence")
        tool(worker, "SubmitTaskResult", summary="delegated")
    value.multi_agent.runner_factory = run
    try:
        value.custom_chat("Delegate the current stage")
        assert planner.i == 0  # One planning turn, then one final result summary.
        assert value.multi_agent.workflow_state == "completed"
        assert finish(value.multi_agent, "planned")["plans"]["planned"]["state"] == "completed"
    finally:
        value._startup_cleanup.close()


def test_background_failure_is_nonzero_once_host_result(tmp_path):
    """Once mode observes background task failure after the delegating main turn returned."""
    from ucagent.runtime.host import RuntimeHost
    value = make_agent(tmp_path, limits={"task_max_attempts": 1})
    release = threading.Event()
    def run(worker):
        """Fail a pending background worker after its admission operation has ended."""
        assert release.wait(5)
        raise RuntimeError("business failure")
    value.multi_agent.runner_factory = run
    host = RuntimeHost(value, mode="once")
    host.start()
    try:
        operation = host.operations.submit("test-plan", lambda ctx: value.multi_agent.submit({
            "plan_id": "failed", "tasks": [{"id": "t", "instruction": "fail"}]}), model=True)
        host.operations.wait(operation["id"], 3)
        assert host.snapshot()["instance"] == "ready"
        release.set()
        result = host.wait(5)
        assert result["instance"] == "closed", result
        assert result["exit_code"] == 1 and result["task_outcome"] == "failed"
    finally:
        release.set()
        host.request_shutdown()
        host.wait(5)
