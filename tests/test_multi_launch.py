"""Public multi startup and real Global/Super/Sub process integration."""
from pathlib import Path
import json
import subprocess
import sys
import uuid
import pytest
import yaml

from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.application.plan import LaunchRequest
from ucagent.application.preparation import prepare_launch
from ucagent.core.multi_agent.mode import agent_role
from ucagent.core.multi_agent.global_agent.session_contracts import load_global_settings, SuperSpec
from ucagent.interfaces.server.super_launcher import SubprocessSuperLauncher

ROOT = Path(__file__).resolve().parents[1]


def request(tmp_path, *flags, config=None):
    """Use isolated explicit configuration without changing operator settings."""
    file = tmp_path / "launch.yaml"
    file.write_text(yaml.safe_dump(config or {"backend": {"key_name": "langchain"}}))
    return LaunchRequest(**parse_launch_options(get_args([str(tmp_path), *flags, "--config", str(file)])))


@pytest.mark.parametrize("source", ["cli", "config", "workspace"])
def test_idle_multi_has_global_only_and_no_business_resources(tmp_path, source):
    """Resolve every public mode source into an idle, isolated Global."""
    config = {"backend": {"key_name": "langchain"}, "stage": [{"name": "must-not-run"}]}
    flags = ["--agent-mode", "multi"] if source == "cli" else []
    if source == "config": config["runtime_options"] = {"agent_mode": "multi"}
    if source == "workspace":
        (tmp_path / ".ucagent").mkdir()
        (tmp_path / ".ucagent/setting.yaml").write_text("runtime_options: {agent_mode: multi}\n")
    launch = request(tmp_path, *flags, config=config)
    prepared, plan, _ = prepare_launch(launch)
    assert agent_role(prepared.cfg) == "global"
    assert plan.interface == "tui" and not plan.default_model and not plan.model_requested
    assert prepared.initial_workflow is None and not prepared.plugins
    assert prepared.cfg.get_value("stage") == [] and prepared.template_dir is None
    assert "unittest:unittest" in load_global_settings(prepared.cfg).allowed_workflows


def test_exact_task_keeps_constraints_and_separate_child_role(tmp_path):
    """Preserve explicit task constraints while launching a non-recursive Super."""
    launch = request(tmp_path, "Adder", "--agent-mode", "multi", "--backend", "codex",
                     "--plugin-workflow", "unittest:unittest", "--max-subagents", "3",
                     "--loop-msg", "Keep exact instruction", "--output", "verification",
                     "--override", "multi_agent.limits.worker_tool_calls=17", "--no-use-skill")
    prepared, plan, _ = prepare_launch(launch)
    assert prepared.initial_workflow == "unittest:unittest"
    assert launch.initial_instruction == "Keep exact instruction"
    assert not any(c.startswith(("chat ", "loop")) for c in plan.commands)
    settings = load_global_settings(prepared.cfg)
    assert settings.launch_profiles["standard"].backend == "codex"
    assert settings.launch_profiles["standard"].max_subagents == 3
    assert prepared.output == "mission" and "mcp" in plan.services
    child = tmp_path / "child"
    child.mkdir()
    launcher = SubprocessSuperLauncher(settings, tmp_path, tmp_path, config_file=str(tmp_path / "launch.yaml"))
    spec = SuperSpec(agent_id="super-one", workflow_ref=prepared.initial_workflow,
                     dut_name="Adder", instruction=launch.initial_instruction)
    argv = launcher.build_command(spec, child, tmp_path / "result.json", spec.instruction)
    assert "--internal-super" in argv and "--agent-mode" not in argv
    child_launch = LaunchRequest(**parse_launch_options(get_args(argv[2:])))
    child_prepared, child_plan, _ = prepare_launch(child_launch)
    assert agent_role(child_prepared.cfg) == "super" and child_prepared.initial_workflow is None
    assert child_prepared.plugin_workflow == "unittest:unittest" and child_prepared.dut_name == "Adder"
    assert child_prepared.output == "verification"
    assert child_prepared.cfg.get_value("multi_agent.max_workers") == 3
    assert child_prepared.cfg.get_value("multi_agent.limits.worker_tool_calls") == 17
    assert child_prepared.cfg.get_value("skill.use_skill") is False
    assert child_plan.interface == "none" and "loop 'Keep exact instruction'" in child_plan.commands


@pytest.mark.parametrize("flags, configured, expected", [
    ([], False, False), ([], True, True),
    (["--no-embed-tools"], False, True), (["--no-embed-tools", "false"], True, False),
])
def test_explicit_profile_backend_and_worker_limit(tmp_path, flags, configured, expected):
    """Apply only explicit CLI embedding choices to independently configured child backends."""
    launch = request(tmp_path, "--agent-mode", "multi", "--backend", "codex", "--max-subagents", "4", *flags,
        config={"global_agent": {"launch_profiles": {"special": {
            "backend": "langchain", "no_embed_tools": configured}}}})
    prepared, _, _ = prepare_launch(launch)
    profiles = load_global_settings(prepared.cfg).launch_profiles
    assert profiles["standard"].backend == "codex" and profiles["special"].backend == "langchain"
    assert profiles["special"].no_embed_tools is expected
    assert all(p.max_subagents == 4 for p in profiles.values())


@pytest.mark.parametrize("flags,error", [
    (["--agent-mode", "multi", "--plugin-workflow", "unittest:unittest"], "DUT name"),
    (["DUT", "--agent-mode", "single", "--max-subagents", "2"], "multi mode"),
    (["--agent-mode", "multi", "--max-subagents", "129"], "1..128"),
    (["DUT", "--internal-super"], "agent_run.id"),
    (["--agent-mode", "multi", "--as-master"], "Master"),
])
def test_invalid_launch_fails_before_execution(tmp_path, flags, error):
    """Reject incomplete or conflicting launch requests before starting agents."""
    with pytest.raises(ValueError, match=error): request(tmp_path, *flags)


def test_global_is_not_a_public_mode():
    """Expose only single and three-layer multi as public modes."""
    with pytest.raises(SystemExit): get_args(["workspace", "--agent-mode", "global"])


def test_global_cannot_enable_internal_handoff(tmp_path):
    """Prevent the public root from enabling a second workflow orchestrator."""
    launch = request(tmp_path, "--agent-mode", "multi",
                     config={"runtime_options": {"workflow_handoff_enabled": True}})
    with pytest.raises(ValueError, match="belongs to Global"): prepare_launch(launch)


@pytest.mark.parametrize("key", ["multi_agent_enabled", "global_agent_enabled"])
@pytest.mark.parametrize("value", [True, False, None])
def test_replaced_mode_fields_are_rejected(tmp_path, key, value):
    """Reject superseded keys even when their values are false or null."""
    with pytest.raises(ValueError, match="remove runtime_options\\." + key):
        request(tmp_path, "--agent-mode", "multi", config={"runtime_options": {key: value}})


@pytest.mark.parametrize("allowed", ["unittest:unittest", ["unittest:incremental"]])
def test_startup_workflow_obeys_catalog_policy(tmp_path, allowed):
    """Reject malformed policy and exact startup tasks outside the allowed catalog."""
    launch = request(tmp_path, "Adder", "--agent-mode", "multi", "--plugin-workflow", "unittest:unittest",
                     config={"global_agent": {"allowed_workflows": allowed}})
    with pytest.raises(ValueError, match="global_agent.allowed_workflows"):
        prepare_launch(launch)


@pytest.fixture
def process_fixture(tmp_path):
    """Create a temporary workflow with a real artifact Checker and an offline CLI backend."""
    plugin = tmp_path / "plugin"
    module = "multi_launch_" + uuid.uuid4().hex
    package = plugin / "src" / module
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('''
from pathlib import Path
from ucagent.core.plugins import Plugin, PluginWorkflow
from ucagent.core.checkers.base import Checker
class EvidenceChecker(Checker):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
    def do_check(self, **kwargs):
        """Require the actual delegated evidence file."""
        path = Path(self.workspace) / "out/result.txt"
        return (path.is_file() and path.read_text() == "evidence"), "Write evidence to out/result.txt"
def get_plugin():
    root = Path(__file__).parent
    return Plugin(name="multi-evidence", version="1.0", description="Startup evidence", root=root,
        checkers=(EvidenceChecker,), workflows=(PluginWorkflow(name="verify", config_file=root / "workflow.yaml",
        purpose="Verify launch evidence", outputs={"out/result.txt": "Checked evidence"}),))
''')
    (plugin / "ucagent-plugin.toml").write_text(f'schema_version = 1\nname = "multi-evidence"\nentry = "{module}:get_plugin"\npython_path = "src"\n')
    (package / "workflow.yaml").write_text(yaml.safe_dump({
        "output": "out", "write_dirs": ["out"], "un_write_dirs": [], "template": None,
        "skill": {"use_skill": False}, "manager_tools": [],
        "stage": [{"name": "evidence", "desc": "Produce evidence", "task": ["Write out/result.txt, journal, Check, submit"],
                   "output_files": ["out/result.txt"], "checker": [{"name": "evidence", "clss": "EvidenceChecker", "args": {}}]}]}))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"backend": {"key_name": "fixture_multi", "fixture_multi": {
        "clss": "ucagent.core.backends.cmdline.SessionCommandBackend", "args": {
        "argv": [sys.executable, str(ROOT / "tests/helpers/session_cli.py"), "--dialect-simple"],
        "resume_args": ["--resume-id", "{{ session_id }}"],
        "output": {"format": "jsonl", "events": [{"match": {"event": "start"}, "session": "conversation"},
                    {"match": {"event": "message"}, "text": "body.text"}, {"match": {"event": "done"}, "done": True}]}}}},
        "langfuse": {"enable": False}, "vmanager": {"llm_suggestion": {
            "check_fail_refinement": {"enable": False}, "check_pass_refinement": {"enable": False}}}}))
    return workspace, plugin, config


@pytest.mark.parametrize("direct", [False, True])
def test_real_cli_global_super_sub_completion(process_fixture, direct):
    """Use real processes, MCP, delegation, Checker receipts and final Global delivery."""
    workspace, plugin, config = process_fixture
    command = [sys.executable, str(ROOT / "ucagent.py"), str(workspace), "DUT", "--agent-mode", "multi",
        "--plugin", str(plugin), "--config", str(config), "--exit-on-completion", "--no-embed-tools", "--no-history"]
    command += ["--plugin-workflow", "multi-evidence:verify"] if direct else ["--loop-msg", "Verify DUT using the evidence workflow"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-6000:]
    sessions = list((workspace / ".ucagent/global/sessions").glob("*/session.json"))
    assert len(sessions) == 1
    state = json.loads(sessions[0].read_text())
    assert state["closed"] and len(state["agents"]) == 1
    run = next(iter(state["agents"].values()))
    assert run["role"] == "super" and run["status"] == "succeeded" and run["workflow_ref"] == "multi-evidence:verify"
    child = Path(run["workspace"])
    assert (child / "out/result.txt").read_text() == "evidence"
    assert len(list(child.glob(".ucagent/multi_agent/**/invocations.jsonl"))) == 2
    assert not (child / ".ucagent/global").exists()
    global_turns = [json.loads(line) for f in workspace.glob(".ucagent/cli/*/invocations.jsonl") for line in f.read_text().splitlines()]
    assert len(global_turns) == (1 if direct else 2)
    inbox = json.loads(sessions[0].with_name("inbox.json").read_text())
    assert all(item["state"] == "delivered" for item in inbox)
