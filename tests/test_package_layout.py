"""Public entrypoints and architectural dependency boundaries for the package layout."""

from ucagent.application.plan import LaunchRequest
import ast
from contextlib import ExitStack
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_public_agent_export_is_the_execution_class():
    """Python callers receive the sole Agent implementation from the public package."""
    from ucagent import VerifyAgent
    from ucagent.core.agent.execution import VerifyAgent as Implementation
    assert VerifyAgent is Implementation
    assert VerifyAgent.__module__ == "ucagent.core.agent.execution"


@pytest.mark.parametrize("entry", ["module", "source", "package_file"])
def test_launch_entrypoints_work_outside_repository(tmp_path, entry):
    """Module, source-script and Master child entrypoints reach the same argument parser."""
    suffix = {"module": ["-m", "ucagent"], "source": [str(ROOT / "ucagent.py")],
              "package_file": [str(ROOT / "ucagent/__main__.py")]}[entry]
    result = subprocess.run([sys.executable, *suffix, "--help"], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Configuration and workflows" in result.stdout
    assert "MCP and HTTP services" in result.stdout


def test_console_script_metadata_resolves_to_the_public_cli():
    """Installed console scripts have an importable destination in the entrypoint package."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    path, symbol = metadata["project"]["scripts"]["ucagent"].split(":")
    assert path == "ucagent.application.entry"
    assert callable(getattr(importlib.import_module(path), symbol))


def test_shared_application_and_workspace_do_not_depend_on_cli():
    """Workspace and shared task preparation do not know argparse or CLI adapters."""
    paths = [*ROOT.joinpath("ucagent/application").glob("*.py"),
             *ROOT.joinpath("ucagent/core/workspace").glob("*.py")]
    for path in paths:
        if path.name == "entry.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(name == "argparse" or name.startswith("ucagent.interfaces.cli")
                           for name in names), (path, names)


def test_command_backend_assets_follow_the_package_root(tmp_path, monkeypatch):
    """Moving a backend or changing cwd cannot change the installed asset directory."""
    import ucagent
    from ucagent.core.backends.cmdline import UCAgentCmdLineBackend
    monkeypatch.chdir(tmp_path)
    backend = UCAgentCmdLineBackend.__new__(UCAgentCmdLineBackend)
    assets = Path(backend._get_assets_path())
    assert assets == Path(ucagent.__file__).resolve().parent / "core/backends/assets"
    assert (assets / "mcp_opencode.json").is_file()


def test_workspace_source_lifetime_is_entrypoint_independent():
    """A Python caller can acquire and release a temporary DUT workspace without CLI state."""
    from ucagent.application.workspace import prepare_workspace
    with ExitStack() as cleanup:
        workspace = Path(prepare_workspace(None, "DUT", temporary_prefix="ucagent-layout-",
                                           create_dut=True, cleanup=cleanup))
        assert (workspace / "DUT/__init__.py").is_file()
    assert not workspace.exists()


def test_self_check_uses_package_resource_paths(capsys):
    """CLI self-check locates settings under the package rather than its nested adapter directory."""
    from ucagent.interfaces.cli.actions import do_check
    with pytest.raises(SystemExit) as result:
        do_check()
    assert result.value.code == 0
    assert str(ROOT / "ucagent/setting.yaml") in capsys.readouterr().out


def test_public_package_import_does_not_load_execution_for_management():
    """Importing the package or control registry never imports the Agent implementation eagerly."""
    result = subprocess.run([sys.executable, "-c",
        "import sys; import ucagent; import ucagent.runtime.control.commands; "
        "assert 'ucagent.core.agent.execution' not in sys.modules; "
        "from ucagent import VerifyAgent; assert 'ucagent.core.agent.execution' in sys.modules"],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_python_launch_request_preserves_explicit_workflow_input(tmp_path):
    """A non-CLI caller's workflow and template context reach the shared resolver unchanged."""
    from ucagent.application.plan import LaunchRequest
    from ucagent.application.preparation import prepare_launch
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("output: generated\n")

    def template_context(cfg, values):
        """Provide a workflow-specific value from the final task context."""
        return {"TASK_LABEL": values["DUT"]}

    request = LaunchRequest(task_options={"workspace": str(tmp_path), "dut_name": "DUT", "output": None,
        "config_file": "master.yaml", "cfg_override": [{"backend.key_name": "blank"}],
        "workflow_config_file": str(workflow), "template_context_factory": template_context,
        "template_target": "rendered", "no_embed_tools": True})
    prepared, plan, options = prepare_launch(request)
    assert prepared.workflow_config_file == str(workflow)
    assert prepared.template_context == {"TASK_LABEL": "DUT"}
    assert options["template_target"] == "rendered"
    assert options["_task_configuration"] is prepared
    assert plan.backend == "blank"


def test_master_and_config_emulation_remain_independent_options():
    """Normalizing a request preserves both Master role and configuration-check intent."""
    from ucagent.interfaces.cli.arguments import get_args
    from ucagent.interfaces.cli.options import parse_launch_options
    from ucagent.application.preparation import prepare_launch
    args = get_args(["--as-master", "--emulate-config", "--config", "master.yaml"])
    request = LaunchRequest(**parse_launch_options(args))
    assert request.master and request.emulate_config
    with ExitStack() as cleanup:
        prepared, plan, options = prepare_launch(request, cleanup=cleanup)
        assert plan.mode == "master" and "master" in plan.services
        assert not plan.default_model and not plan.model_requested
        assert prepared.cfg.backend.key_name == "blank"
        assert options["dut_name"] == "DUT_TEST"
        assert (Path(options["workspace"]) / "DUT_TEST/__init__.py").is_file()


def test_launch_logging_opens_after_workspace_source_is_ready(tmp_path, monkeypatch):
    """Workspace creation/extraction precedes opening logs that may live in that workspace."""
    from ucagent.application.plan import LaunchRequest
    from ucagent.application.preparation import prepare_launch
    workspace = tmp_path / "new-workspace"
    events = []

    def open_log(**options):
        """Observe source readiness at each logging initialization boundary."""
        assert workspace.is_dir()
        events.append("log")

    monkeypatch.setattr("ucagent.application.preparation.init_log_logger", open_log)
    monkeypatch.setattr("ucagent.application.preparation.init_msg_logger", open_log)
    request = LaunchRequest(task_options={"workspace": str(workspace), "dut_name": "empty", "output": None,
        "config_file": "master.yaml", "cfg_override": [{"backend.key_name": "blank"}], "no_embed_tools": True},
        create_workspace=True, log=True)
    prepare_launch(request)
    assert events == ["log", "log"]


def test_core_locale_and_application_preset_have_distinct_owners(tmp_path, monkeypatch):
    """Locale loading and named launch presets retain their precedence at canonical paths."""
    from ucagent.util.config import get_config
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = get_config("master.yaml", [{"backend.key_name": "blank"}], str(tmp_path))
    loaded = cfg.__dict__["_loaded_config_files"]
    locale = str(ROOT / "ucagent/core/locales/zh.yaml")
    preset = str(ROOT / "ucagent/application/presets/zh/master.yaml")
    assert locale in loaded and preset in loaded
    assert loaded.index(locale) < loaded.index(preset)
    assert cfg.workflow is None and cfg.stage == []


def test_master_child_entrypoint_exists_in_current_package(tmp_path):
    """Moving server modules deeper does not mislocate the package launcher."""
    from ucagent.interfaces.server.api_master import MasterApiServer
    server = MasterApiServer(workspace=str(tmp_path))
    command, _ = server._build_ucagent_command({"use_zip_workspace": False},
        {"workspace_dir": str(tmp_path), "dut_name": "DUT"},
        {"host": "127.0.0.1", "port": 8765, "password": ""})
    assert Path(command[1]) == ROOT / "ucagent/__main__.py"
    assert Path(command[1]).is_file()


def test_web_console_child_entrypoint_exists_in_current_package():
    """Web terminal subprocesses use the same public package file as Master children."""
    import shlex
    from ucagent.interfaces.server.api_terminal import _build_web_console_command
    command = shlex.split(_build_web_console_command(["ucagent", "workspace", "DUT"]))
    assert command[3] == str(ROOT / "ucagent/__main__.py")
    assert Path(command[3]).is_file()


def test_plugin_discovery_group_is_independent_of_loader_module():
    """Moving the loader into core preserves the installed plugin entry-point protocol."""
    from ucagent.core.plugins import PLUGIN_ENTRY_POINT_GROUP
    assert PLUGIN_ENTRY_POINT_GROUP == "ucagent.plugins"
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "ucagent.plugins" in metadata["tool"]["setuptools"]["package-data"]
