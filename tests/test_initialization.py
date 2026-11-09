"""Startup contracts shared by the CLI and direct Agent construction.

The baseline fixes public argument semantics and externally observable ordering.
Later batches add final-config validation, failed-start cleanup, and lazy models;
known eager-model/service-autostart behavior is deliberately not frozen here.
"""

from ucagent.application.plan import LaunchRequest
import argparse
import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from ucagent.interfaces.cli.arguments import get_args
from ucagent.application.entry import run
from ucagent.util.config import get_config


def parse_arguments(*arguments):
    """Parse a caller-owned argument vector without changing the real process."""
    with mock.patch("sys.argv", ["ucagent", *arguments]):
        return get_args()


def argument_contract():
    """Capture the public parser schema, excluding presentation and version text."""
    captured = []
    original = argparse.ArgumentParser.parse_args

    def capture(parser, *args, **kwargs):
        """Record the parser used by the actual public entrypoint."""
        captured.append(parser)
        return original(parser, *args, **kwargs)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", capture):
        parse_arguments("workspace", "DUT")
    return {
        action.dest: {
            "options": action.option_strings,
            "default": action.default,
            "const": action.const,
            "nargs": action.nargs,
            "type": getattr(action.type, "__name__", None),
            "choices": action.choices,
            "required": action.required,
            "hidden": action.help == argparse.SUPPRESS,
        }
        for action in captured[0]._actions
    }


def test_public_argument_contract():
    """Moving parser code preserves aliases, defaults, arity, types and choices."""
    expected = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "cli_argument_contract.json").read_text())
    assert argument_contract() == expected


@pytest.mark.parametrize("options, explicit, enabled", [
    ([], False, True), (["--use-skill"], True, True),
    (["--no-use-skill"], True, False),
    (["--no-use-skill", "--use-skill"], True, True),
])
def test_skill_explicitness(options, explicit, enabled):
    """An omitted flag leaves configuration authority intact."""
    args = parse_arguments("workspace", "DUT", *options)
    assert args._use_skill_explicit is explicit
    assert args.use_skill is enabled


@pytest.mark.parametrize("options, expected", [
    ([], None), (["--as-master"], ""), (["--as-master", "127.0.0.1:8800"], "127.0.0.1:8800"),
])
def test_master_optional_address(options, expected):
    """Missing, bare and addressed Master flags have distinct meanings."""
    assert parse_arguments(*options).as_master == expected


def test_repeated_options_keep_order_and_last_scalar():
    """Repeated overrides and commands retain the ordering chosen by the caller."""
    args = parse_arguments("workspace", "DUT", "--override", "seed=1,seed=2",
        "--override", "seed=3", "--seed", "4", "--seed", "5",
        "--icmd", "pwd", "--icmd", "status", "--plugin", "one", "--plugin", "two",
        "--meta", "label=one", "--meta", "label=two", "-s", "-hm", "-l", "-eoc")
    assert args.override == [{"seed": 1}, {"seed": 2}, {"seed": 3}]
    assert args.icmd == ["pwd", "status"]
    assert args.plugin == ["one", "two"]
    assert args.meta == {"label": "two"}
    assert args.seed == 5
    assert args.stream_output and args.human and args.loop and args.exit_on_completion


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_embedding_boolean_syntax(value):
    """Explicit false values retain embedded tools using the existing syntax."""
    assert parse_arguments("workspace", "DUT", "--no-embed-tools", value).no_embed_tools is False


def test_invalid_interaction_choice_is_rejected():
    """Invalid choices fail at the parser boundary."""
    with pytest.raises(SystemExit) as error:
        parse_arguments("workspace", "DUT", "--interaction-mode", "invalid")
    assert error.value.code == 2


def test_final_config_keeps_workspace_file_and_override_precedence(tmp_path, monkeypatch):
    """Workflow defaults remain below workspace, explicit-file and CLI values."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    settings = tmp_path / ".ucagent"
    settings.mkdir()
    (settings / "setting.yaml").write_text("seed: 2\n")
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("seed: 1\n")
    config = tmp_path / "config.yaml"
    config.write_text("seed: 3\n")
    cfg = get_config(str(config), [{"seed": 4}], str(tmp_path), workflow_config_file=str(workflow))
    assert cfg.seed == 4
    assert get_config(str(config), None, str(tmp_path), workflow_config_file=str(workflow)).seed == 3


@pytest.mark.parametrize("options, mode", [
    ([], "once"), (["--human"], "console"), (["--tui"], "console"),
    (["--mcp-server"], "service"), (["--export-cmd-api"], "service"),
    (["--as-master"], "master"),
])
def test_startup_modes_preserve_initial_command_order(tmp_path, cli_runtime, options, mode):
    """Services start before ordered user commands and configuration commands."""
    config = tmp_path / "launch.yaml"
    config.write_text(yaml.safe_dump({"workflow": None, "backend": {"key_name": "blank"}}))
    with mock.patch("sys.argv", ["ucagent", str(tmp_path), "DUT", "--config", str(config),
        *options, "--icmd", "pwd", "--icmd", "status"]), \
         mock.patch("ucagent.VerifyAgent") as factory, \
         mock.patch("ucagent.interfaces.terminal.tui.enter_tui", return_value=""):
        factory.return_value.cfg.get_value.side_effect = lambda key, default=None: ["config-tail"] if key == "init_cmds" else default
        factory.return_value.cfg.backend.key_name = "blank"
        factory.return_value.emulate_config.return_value = None
        cli_runtime.registry.execute.return_value.data = {"ok": True}
        run()
    assert cli_runtime.startup.start.call_args.args[0] == ["logo_and_version", "pwd", "status", "config-tail"]
    factory.return_value.pre_run.assert_called_once()
    from ucagent.runtime.host import RuntimeHost
    assert RuntimeHost.call_args.kwargs["mode"] == mode


def test_failed_service_start_stops_startup_and_shuts_down(tmp_path, cli_runtime):
    """A failed listener never reaches model/user commands and is cleaned up."""
    with mock.patch("sys.argv", ["ucagent", str(tmp_path), "DUT", "--mcp-server"]), \
         mock.patch("ucagent.VerifyAgent"):
        cli_runtime.services.start_mcp.return_value = {"ok": False, "message": "listener failed"}
        with pytest.raises(RuntimeError, match="listener failed"):
            run()
    cli_runtime.startup.start.assert_not_called()
    cli_runtime.request_shutdown.assert_called_once_with("startup_or_runtime_failure", exit_code=1)
    cli_runtime.wait.assert_called_once_with(cli_runtime.shutdown_timeout)


def test_emulation_traverses_agent_checks(tmp_path, cli_runtime):
    """Configuration emulation runs stage validation rather than only loading YAML."""
    config = tmp_path / "launch.yaml"
    config.write_text("workflow: null\n")
    with mock.patch("sys.argv", ["ucagent", "--config", str(config), "--emulate-config"]), \
         mock.patch("ucagent.VerifyAgent") as factory:
        run()
    factory.return_value.emulate_config.assert_called_once()
    cli_runtime.startup.start.assert_not_called()
    cli_runtime.request_shutdown.assert_called_once_with("emulation_finished")


@pytest.mark.parametrize("option", ["--version", "--list-plugins"])
def test_management_does_not_construct_agent(option):
    """Task-free management succeeds without a workspace or Agent constructor."""
    with mock.patch("sys.argv", ["ucagent", option]), \
         mock.patch("ucagent.VerifyAgent") as factory, \
         mock.patch("ucagent.core.plugins.available_plugin_names", return_value=[]):
        if option == "--version":
            with pytest.raises(SystemExit) as error:
                run()
            assert error.value.code == 0
        else:
            run()
    factory.assert_not_called()


def test_grouped_help_covers_public_options_and_hides_internal_transport():
    """Every public parameter has one help group; internal options remain invisible."""
    from ucagent.interfaces.cli.arguments import build_argument_parser
    parser = build_argument_parser()
    groups = {group.title: group for group in parser._action_groups}
    expected = {
        "Task and workspace": {"workspace", "dut", "workspace_base", "output"},
        "Configuration and workflows": {"config", "override", "plugin", "plugin_workflow"},
        "Execution and models": {"backend", "loop", "loop_msg", "interaction_mode", "icmd", "exit_on_completion", "seed", "sys_tips"},
        "Interface and display": {"human", "tui", "stream_output", "web_console", "web_terminal"},
        "Stages and history": {"force_stage_index", "skip", "unskip", "ref", "no_history"},
        "Documents, templates and file protection": {"template_dir", "template_overwrite", "template_cfg_override", "guid_doc_path", "gen_instruct_file", "no_write"},
        "Tools and skills": {"ex_tools", "no_embed_tools", "use_skill", "extra_skill_path", "use_todo_tools", "force_todo", "enable_context_manage_tools", "append_py_path"},
        "MCP and HTTP services": {"mcp_server", "mcp_server_no_file_tools", "mcp_server_host", "mcp_server_port", "export_cmd_api"},
        "Master management and connections": {"as_master", "as_master_key", "as_master_password", "as_master_persist", "master", "client_id"},
        "Logs and recording": {"log", "log_file", "msg_file"},
        "Checks and management": {"version", "check", "upgrade", "list_plugins", "validate_plugin", "emulate_config", "hook_message"},
    }
    for title, names in expected.items():
        assert {action.dest for action in groups[title]._group_actions} == names
    help_text = parser.format_help()
    for option in ("--meta", "--web-console-session-host", "--web-console-session-port", "--web-console-capture-path"):
        assert option not in help_text
    assert "Examples:" in help_text


def test_parser_accepts_explicit_vector_without_reading_process_argv():
    """Library callers can parse arguments without mutating global process state."""
    with mock.patch("sys.argv", ["ucagent", "--invalid-process-option"]):
        args = get_args(["workspace", "DUT", "--seed", "12"])
    assert args.workspace == "workspace" and args.seed == 12


def test_workflow_selection_keeps_only_selected_resources(tmp_path):
    """Two workflows in one plugin preserve their own document/template pairing."""
    from ucagent.core.agent.configuration import resolve_task_configuration
    from ucagent.core.plugins import LoadedPlugin, Plugin, PluginWorkflow
    workflows = []
    for name in ("alpha", "beta"):
        root = tmp_path / name
        root.mkdir()
        config = root / "workflow.yaml"
        config.write_text(f"output: {name}\n")
        docs = root / "docs"
        docs.mkdir()
        template = root / "template"
        template.mkdir()
        workflows.append(PluginWorkflow(name=name, config_file=config, guide_doc_paths=(docs,), template_dir=template))
    loaded = LoadedPlugin(Plugin(name="probe", version="1.0", description="Preparation probe", root=tmp_path,
        workflows=tuple(workflows)), selector="probe", source="test")
    config = tmp_path / "launch.yaml"
    config.write_text("workflow: null\nbackend:\n  key_name: blank\n")
    results = [resolve_task_configuration(str(tmp_path), "DUT", config_file=str(config), plugins=[loaded],
        plugin_workflow=f"probe:{name}") for name in ("alpha", "beta")]
    for result, name in zip(results, ("alpha", "beta")):
        assert result.output == name
        assert result.guide_doc_paths == (str(tmp_path / name / "docs"),)
        assert result.template_dir == str(tmp_path / name)
        assert result.workflow_config_file == str(tmp_path / name / "workflow.yaml")


def test_cli_prepared_configuration_is_reused_by_direct_construction(tmp_path):
    """Constructing from a prepared launch never reloads configuration or resources."""
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    args = get_args([str(tmp_path), "empty", "--config", "master.yaml", "--no-history", "--as-master"])
    prepared, plan, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    with mock.patch("ucagent.core.agent.configuration.get_config", side_effect=AssertionError("duplicate config load")):
        agent = VerifyAgent(**options)
    assert agent.cfg is prepared.cfg
    assert agent.workflow_config_file == (prepared.workflow_config_file or "")
    assert plan.backend == "blank"
    agent.backend.exit()


def test_final_config_backend_override_determines_dependency(tmp_path):
    """An explicit local backend override supersedes a configured MCP backend."""
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    config = tmp_path / "launch.yaml"
    config.write_text("workflow: null\nbackend:\n  key_name: codex\n")
    args = get_args([str(tmp_path), "DUT", "--config", str(config), "--backend", "blank"])
    prepared, plan, _ = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    assert prepared.cfg.backend.key_name == plan.backend == "blank"
    assert "mcp" not in plan.services


def test_resource_failure_restores_exact_original_document_modes(tmp_path):
    """A failure after making runtime docs writable restores their original modes."""
    import stat
    from ucagent.core.agent.configuration import resolve_task_configuration
    from ucagent.core.workspace.assets import prepare_resources
    docs = tmp_path / "Guide_Doc"
    docs.mkdir()
    document = docs / "existing.md"
    document.write_text("existing task document")
    document.chmod(0o440)
    prepared = resolve_task_configuration(str(tmp_path), "DUT", config_file="master.yaml",
        cfg_override=[{"backend.key_name": "blank"}])
    with mock.patch("ucagent.core.workspace.assets.copy_skill_files", side_effect=RuntimeError("skill copy failed")):
        with pytest.raises(RuntimeError, match="skill copy failed"):
            prepare_resources(prepared)
    assert stat.S_IMODE(document.stat().st_mode) == 0o440
    assert document.read_text() == "existing task document"


def test_partial_protection_failure_restores_permissions(tmp_path):
    """A permission operation failing partway through cannot leave protected files."""
    import stat
    from ucagent.core.workspace.permissions import PermissionChanges, apply_file_protection
    from ucagent.util.config import Config
    target = tmp_path / "input.txt"
    target.write_text("input")
    target.chmod(0o640)
    permissions = PermissionChanges(str(tmp_path))
    cfg = Config({"un_write_dirs": ["input.txt"], "write_dirs": []})

    def fail_after_chmod(*args, **kwargs):
        """Simulate a filesystem failure after one successful chmod."""
        target.chmod(0o444)
        raise OSError("protection failed")

    with mock.patch("ucagent.core.workspace.permissions.fc.chmode_ro_by_pattern", side_effect=fail_after_chmod):
        with pytest.raises(OSError, match="protection failed"):
            apply_file_protection(cfg, str(tmp_path), None, permissions)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    permissions.restore()
    assert not permissions.modes


def test_disabled_skills_need_no_skill_directory_or_config_reload(tmp_path):
    """Resource preparation consumes final config and honors a disabled skill setting."""
    from ucagent.core.agent.configuration import resolve_task_configuration
    from ucagent.core.workspace.assets import prepare_resources
    prepared = resolve_task_configuration(str(tmp_path), "DUT", config_file="master.yaml",
        cfg_override=[{"skill.use_skill": False}])
    with mock.patch("ucagent.core.agent.configuration.get_config", side_effect=AssertionError("duplicate config load")), \
         mock.patch("ucagent.core.workspace.assets.copy_skill_files", side_effect=AssertionError("disabled skills copied")):
        resources = prepare_resources(prepared)
    assert not (tmp_path / ".ucagent/skills").exists()
    resources.permissions.restore()


def test_instruction_destination_rejects_workspace_escape(tmp_path):
    """Instruction generation cannot write into the workspace parent."""
    from ucagent.core.workspace.assets import generate_instruction_file
    with pytest.raises(ValueError, match="inside the workspace"):
        generate_instruction_file(str(tmp_path), "DUT", "task", "../outside.md")


def blank_launch_args(tmp_path, *options):
    """Build a deterministic task with one protected input and no model integrations."""
    target = tmp_path / "input.txt"
    target.write_text("preserved input")
    target.chmod(0o640)
    config = tmp_path / "launch.yaml"
    config.write_text(yaml.safe_dump({
        "workflow": None, "backend": {"key_name": "blank"}, "langfuse": {"enable": False},
        "skill": {"use_skill": False}, "un_write_dirs": ["input.txt"],
        "vmanager": {"llm_suggestion": {"check_fail_refinement": {"enable": False},
                                        "check_pass_refinement": {"enable": False}}},
        "stage": [{"name": "probe", "desc": "Probe", "task": ["Inspect evidence"], "checker": []}],
    }))
    return get_args([str(tmp_path), "DUT", "--config", str(config), "--no-history", *options])


@pytest.mark.parametrize("boundary", ["tools", "backend", "stage"])
def test_component_failure_restores_prepared_permissions(tmp_path, boundary):
    """Failures after resource preparation restore input modes and close created backends."""
    import stat
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    args = blank_launch_args(tmp_path)
    _, _, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    targets = {"tools": "ucagent.core.agent.construction.create_plugin_tools",
               "backend": "ucagent.core.backends.blank.BlankBackend.init",
               "stage": "ucagent.core.stage.StageManager.init_stage"}
    with mock.patch(targets[boundary], side_effect=RuntimeError("injected failure")), \
         mock.patch("ucagent.core.backends.blank.BlankBackend.exit") as close:
        with pytest.raises(RuntimeError, match="injected failure"):
            VerifyAgent(**options)
    assert stat.S_IMODE((tmp_path / "input.txt").stat().st_mode) == 0o640
    assert close.call_count == (0 if boundary == "tools" else 1)


@pytest.mark.parametrize("boundary", ["host", "session", "start", "mcp", "command"])
def test_application_failure_releases_resources_and_host_threads(tmp_path, boundary):
    """Failures before and after Host ownership leave no runtime thread or permission changes."""
    import stat
    import threading
    from ucagent.application.launch import run_application
    from ucagent.interfaces.cli.options import parse_launch_options
    options = ["--mcp-server"] if boundary == "mcp" else ["--icmd", "quit"]
    if boundary == "command":
        options = ["--icmd", "unknown_initialization_command"]
    args = blank_launch_args(tmp_path, *options)
    targets = {"host": "ucagent.runtime.host.RuntimeHost.__init__",
               "session": "ucagent.runtime.session.RuntimeSession.__init__",
               "start": "ucagent.runtime.output.OutputBuffer.install",
               "mcp": "ucagent.runtime.services.ServiceManager.start_mcp"}
    from contextlib import nullcontext
    injection = mock.patch(targets[boundary], side_effect=RuntimeError("injected failure")) if boundary != "command" else nullcontext()
    before = {thread.ident for thread in threading.enumerate()}
    with injection, mock.patch("ucagent.core.backends.blank.BlankBackend.exit") as close:
        with pytest.raises(RuntimeError if boundary != "command" else SystemExit):
            run_application(LaunchRequest(**parse_launch_options(args)))
    assert close.call_count == 1
    assert stat.S_IMODE((tmp_path / "input.txt").stat().st_mode) == 0o640
    leaked = [thread for thread in threading.enumerate()
              if thread.ident not in before and thread.name.startswith("ucagent-")]
    for thread in leaked:
        thread.join(timeout=2)
    assert not [thread.name for thread in leaked if thread.is_alive()]


def test_host_takes_constructor_cleanup_once(tmp_path):
    """A directly constructed Agent transfers backend and exact permission cleanup to Host."""
    import stat
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent.runtime.host import RuntimeHost
    from ucagent import VerifyAgent
    _, _, options = prepare_launch(LaunchRequest(**parse_launch_options(blank_launch_args(tmp_path))))
    with mock.patch("ucagent.core.backends.blank.BlankBackend.exit") as close:
        agent = VerifyAgent(**options)
        host = RuntimeHost(agent)
        agent._startup_cleanup.close()
        close.assert_not_called()
        host.start()
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"
        host.request_shutdown()
    close.assert_called_once()
    assert stat.S_IMODE((tmp_path / "input.txt").stat().st_mode) == 0o640


@pytest.mark.parametrize("options, automatic, requested", [
    ([], True, True), (["--human"], False, False), (["--tui"], False, False),
    (["--mcp-server"], False, False), (["--mcp-server", "--loop"], False, True),
    (["--mcp-server", "--icmd", "nr"], False, True),
    (["--export-cmd-api"], False, False), (["--web-terminal"], False, False),
])
def test_model_launch_policy_requires_explicit_service_work(tmp_path, options, automatic, requested):
    """A service or view alone never schedules an internal model operation."""
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    args = blank_launch_args(tmp_path, *options, "--backend", "langchain")
    _, plan, _ = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    assert plan.default_model is automatic
    assert plan.model_requested is requested


def test_model_free_queries_and_first_work_prepare_once(tmp_path):
    """Status, messages and context tools stay local; first work prepares one model pair."""
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    args = blank_launch_args(tmp_path, "--mcp-server", "--backend", "langchain", "--enable-context-manage-tools")
    prepared, _, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    model = SimpleNamespace(model_name="test-model", temperature=0)
    graph = mock.Mock()
    graph.stream.return_value = []
    with mock.patch("ucagent.core.backends.langchain.agent.negotiate_openai_api_mode", return_value="responses") as probe, \
         mock.patch("ucagent.core.backends.langchain.agent.get_chat_model", return_value=model) as create_model, \
         mock.patch("ucagent.core.backends.langchain.agent.create_agent", return_value=graph) as create_graph:
        agent = VerifyAgent(**options)
        assert agent.cfg is prepared.cfg
        for _ in range(3):
            agent.status_info()
            assert agent.messages_get_raw() == []
            assert agent.message_info()["count"] == 0
            agent.get_messages_cfg([])
            agent.message_summary()
        tool = agent.get_tool_by_name("ArbitContextSummary")
        assert "successfully" in tool.invoke({"message": "Local summary"})
        probe.assert_not_called()
        create_model.assert_not_called()
        create_graph.assert_not_called()
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: agent.backend.prepare(), range(4)))
        agent.backend.do_work_values({}, {})
        agent.backend.do_work_stream({}, {})
        assert probe.call_count == 1 and create_model.call_count == 2 and create_graph.call_count == 1
        assert agent.message_manage_node.model is model
        agent._startup_cleanup.close()


def test_invalid_model_config_fails_only_when_model_is_requested(tmp_path):
    """An invalid model setup never blocks deterministic state access or silently degrades."""
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    args = blank_launch_args(tmp_path, "--mcp-server", "--backend", "langchain")
    _, _, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    with mock.patch("ucagent.core.backends.langchain.agent.negotiate_openai_api_mode", side_effect=ValueError("invalid model configuration")) as probe, \
         mock.patch("ucagent.core.backends.langchain.agent.get_chat_model") as create:
        agent = VerifyAgent(**options)
        assert agent.backend.messages_get_raw() == []
        probe.assert_not_called()
        for _ in range(2):
            with pytest.raises(ValueError, match="invalid model configuration"):
                agent.backend.do_work_values({}, {})
        probe.assert_called_once()
        create.assert_not_called()
        assert agent.cfg.backend.key_name == "langchain"
        agent._startup_cleanup.close()


@pytest.mark.parametrize("capability", ["embedding", "check_fail_refinement", "check_pass_refinement"])
def test_optional_model_capabilities_keep_their_own_dependency_gate(tmp_path, capability):
    """Explicit embedding/review requirements cannot be silently disabled by MCP startup."""
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    options = ["--mcp-server", "--backend", "langchain"]
    if capability == "embedding":
        options += ["--no-embed-tools", "false"]
    else:
        options += ["--override", f"vmanager.llm_suggestion.{capability}.enable=True"]
    args = blank_launch_args(tmp_path, *options)
    _, plan, constructor = prepare_launch(LaunchRequest(**parse_launch_options(args)))

    def review_gate(cfg, *args):
        """Expose only the explicitly enabled review dependency failure."""
        if cfg.enable:
            raise RuntimeError("review dependency unavailable")
        return None

    target = "ucagent.core.agent.construction.SemanticSearchInGuidDoc" if capability == "embedding" else "ucagent.core.stage.vmanager.get_llm_check_instance"
    failure = RuntimeError("embedding dependency unavailable") if capability == "embedding" else review_gate
    with mock.patch(target, side_effect=failure), \
         mock.patch("ucagent.core.backends.langchain.agent.get_chat_model") as main_model:
        with pytest.raises(RuntimeError, match="dependency unavailable"):
            VerifyAgent(**constructor)
        main_model.assert_not_called()
    assert not plan.default_model and not plan.model_requested


def test_live_mcp_tool_call_needs_no_main_model(tmp_path):
    """An actual MCP client discovers tools and reads a file without model preparation."""
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from ucagent.runtime.host import RuntimeHost
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent import VerifyAgent
    args = blank_launch_args(tmp_path, "--mcp-server", "--mcp-server-port", "0", "--backend", "langchain")
    _, plan, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    with mock.patch("ucagent.core.backends.langchain.agent.negotiate_openai_api_mode", side_effect=AssertionError("unexpected probe")) as probe, \
         mock.patch("ucagent.core.backends.langchain.agent.get_chat_model", side_effect=AssertionError("unexpected model")) as create:
        agent = VerifyAgent(**options)
        host = RuntimeHost(agent, mode=plan.mode)
        host.start()
        try:
            from ucagent.application.launch import configure_services
            configure_services(host.services)
            result = host.services.start_mcp(host="127.0.0.1", port=0)
            assert result["ok"], result
            server = host.services.get("mcp")

            async def exercise():
                """Use the real SDK transport against the runtime-owned endpoint."""
                async with streamable_http_client(server.url() + "/mcp") as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=5) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert "ReadTextFile" in {tool.name for tool in tools.tools}
                        result = await session.call_tool("ReadTextFile", {"path": "input.txt"})
                        assert not result.is_error
                        assert "preserved input" in str(result)

            asyncio.run(exercise())
            probe.assert_not_called()
            create.assert_not_called()
        finally:
            host.request_shutdown()
            assert host.wait(5)["instance"] == "closed"


def test_initialization_imports_are_explicit_and_not_exception_fallbacks():
    """Startup and model setup use exact imports, with no wildcard or try-import paths."""
    import ast
    root = Path(__file__).resolve().parents[1]
    files = [*root.joinpath("ucagent/application").rglob("*.py"),
             *root.joinpath("ucagent/core/workspace").rglob("*.py"),
             *root.joinpath("ucagent/core/agent/interaction").rglob("*.py"),
             root / "ucagent/__main__.py", root / "ucagent/core/agent/execution.py",
             root / "ucagent/core/backends/langchain/agent.py", root / "ucagent/util/models.py"]
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert all(name.name != "*" for name in node.names), path
            if isinstance(node, ast.Try):
                imports = [child for statement in node.body for child in ast.walk(statement)
                           if isinstance(child, (ast.Import, ast.ImportFrom))]
                assert not imports, (path, [child.lineno for child in imports])


@pytest.mark.parametrize("language", ["", ".en"])
def test_option_reference_lists_each_public_parameter_once(language):
    """The maintained option tables cover the actual public parser without hidden fields."""
    import re
    from ucagent.interfaces.cli.arguments import build_argument_parser
    root = Path(__file__).resolve().parents[1]
    text = (root / f"docs/content/02_usage/03_option{language}.md").read_text()
    keys = re.findall(r"^\|\s*(--[a-z][\w-]*)", text, re.MULTILINE)
    parser = build_argument_parser()
    expected = {action.option_strings[0] for action in parser._actions
                if action.option_strings and action.dest != "help" and action.help != argparse.SUPPRESS}
    assert len(keys) == len(set(keys))
    assert set(keys) == expected


@pytest.mark.parametrize("pattern", ["Adder", "Adder/xspcomm/_pyxspcomm.so"])
def test_file_protection_accepts_workspace_shared_library_links(tmp_path, pattern):
    """Protect picker-style library links and restore their real target's exact mode."""
    import stat
    from ucagent.core.workspace.permissions import PermissionChanges, apply_file_protection
    from ucagent.util.config import Config
    package = tmp_path / "Adder/xspcomm"
    package.mkdir(parents=True)
    library = package / "_pyxspcomm.so.0.0.1"
    library.write_bytes(b"shared library fixture")
    library.chmod(0o750)
    alias = package / "_pyxspcomm.so"
    alias.symlink_to(library.name)
    permissions = PermissionChanges(str(tmp_path))
    cfg = Config({"un_write_dirs": [pattern], "write_dirs": []})
    try:
        protected = apply_file_protection(cfg, str(tmp_path), None, permissions)
        assert str(alias) in protected
        assert stat.S_IMODE(library.stat().st_mode) == 0o554
        assert alias.is_symlink() and alias.read_bytes() == b"shared library fixture"
        assert permissions.modes[str(library)] == 0o750
    finally:
        permissions.restore()
    assert stat.S_IMODE(library.stat().st_mode) == 0o750
    assert alias.is_symlink() and alias.readlink() == Path(library.name)


def test_file_protection_records_children_of_selected_directory_link(tmp_path):
    """A selected directory link snapshots every file the chmod traversal will touch."""
    import stat
    from ucagent.core.workspace.permissions import PermissionChanges, apply_file_protection
    from ucagent.util.config import Config
    actual = tmp_path / "actual"
    nested = actual / "nested"
    nested.mkdir(parents=True)
    library = nested / "library.so"
    library.write_bytes(b"library")
    library.chmod(0o640)
    actual.chmod(0o750)
    nested.chmod(0o700)
    alias = tmp_path / "linked"
    alias.symlink_to(actual.name, target_is_directory=True)
    permissions = PermissionChanges(str(tmp_path))
    cfg = Config({"un_write_dirs": ["linked"], "write_dirs": []})
    try:
        apply_file_protection(cfg, str(tmp_path), None, permissions)
        assert stat.S_IMODE(library.stat().st_mode) == 0o444
        assert permissions.modes[str(library)] == 0o640
    finally:
        permissions.restore()
    assert stat.S_IMODE(library.stat().st_mode) == 0o640
    assert stat.S_IMODE(actual.stat().st_mode) == 0o750
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    assert alias.is_symlink()


@pytest.mark.parametrize("directory", [False, True])
def test_file_protection_rejects_link_targets_outside_workspace(tmp_path, directory):
    """A linked external target must never have its permissions changed."""
    import stat
    from ucagent.core.workspace.permissions import PermissionChanges, apply_file_protection
    from ucagent.util.config import Config
    workspace = tmp_path / "workspace"
    dut = workspace / "Adder"
    dut.mkdir(parents=True)
    external = tmp_path / "external"
    if directory:
        external.mkdir()
        (external / "library.so").write_bytes(b"outside")
    else:
        external.write_bytes(b"outside")
    external.chmod(0o750)
    alias = dut / "linked"
    alias.symlink_to(external, target_is_directory=directory)
    permissions = PermissionChanges(str(workspace))
    cfg = Config({"un_write_dirs": ["Adder"], "write_dirs": []})
    with pytest.raises(ValueError, match="must remain inside the workspace"):
        apply_file_protection(cfg, str(workspace), None, permissions)
    assert stat.S_IMODE(external.stat().st_mode) == 0o750
    assert alias.is_symlink()
    permissions.restore()


def test_agent_with_picker_library_link_restores_modes_on_shutdown(tmp_path):
    """Actual Agent and Host startup accept the shared-library layout reported by make."""
    import stat
    from ucagent.application.preparation import prepare_launch
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent.runtime.host import RuntimeHost
    from ucagent import VerifyAgent
    args = blank_launch_args(tmp_path, "--override", "un_write_dirs=['Adder']")
    args.dut = "Adder"
    package = tmp_path / "Adder/xspcomm"
    package.mkdir(parents=True)
    library = package / "_pyxspcomm.so.0.0.1"
    library.write_bytes(b"shared library fixture")
    library.chmod(0o750)
    alias = package / "_pyxspcomm.so"
    alias.symlink_to(library.name)
    _, _, options = prepare_launch(LaunchRequest(**parse_launch_options(args)))
    agent = VerifyAgent(**options)
    host = RuntimeHost(agent)
    try:
        host.start()
        assert host.snapshot()["instance"] == "ready"
        assert stat.S_IMODE(library.stat().st_mode) == 0o554
        assert alias.read_bytes() == b"shared library fixture"
    finally:
        host.request_shutdown()
        assert host.wait(5)["instance"] == "closed"
    assert stat.S_IMODE(library.stat().st_mode) == 0o750
    assert alias.is_symlink()
