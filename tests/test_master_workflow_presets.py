"""Web launch presets select plugin workflows rather than removed config aliases."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from ucagent.core.plugins import load_plugin, resolve_plugin_workflow
from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.interfaces.server.api_master import MasterApiServer
from ucagent.util.config import Config, load_yaml_with_env_vars


@pytest.mark.parametrize("name,selector", [("UT", "toffee-ut:ut"), ("Formal", "formal:formal"),
                                          ("Vibe", "unittest:vibe"), ("Increment", "unittest:incremental")])
def test_web_preset_resolves_to_real_plugin_workflow(tmp_path, name, selector, monkeypatch):
    """API defaults survive child argv parsing without inheriting the default workflow."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "config.yaml").write_text("workflow: null\n")
    config = Config(load_yaml_with_env_vars(str(root / "ucagent/setting.yaml"))).freeze()
    server = MasterApiServer(workspace=str(tmp_path), cfg=config)
    monkeypatch.setattr(server, "_get_workspace", lambda identifier: {"compile": {}})
    with TestClient(server._app) as client:
        result = client.get("/api/workspace/test/config-options")
    assert result.status_code == 200
    options = result.json()["options"]
    selected = next(option for option in options if option["name"] == name)
    assert selected["value"] == selector
    request = {**selected["defaults"], "use_zip_workspace": False}
    command, _ = server._build_ucagent_command(request, {"workspace_dir": str(tmp_path), "dut_name": "DUT"},
                                              {"host": "127.0.0.1", "port": 8765, "password": ""})
    options = parse_launch_options(get_args(command[2:]))
    assert options["task_options"]["plugin_workflow"] == selector
    assert "--config" not in command and "--output" not in command
    plugin = load_plugin(request["plugin"][0], check_dependencies=False)
    owner, workflow = resolve_plugin_workflow([plugin], selector)
    assert owner is plugin and workflow.config_file.is_file()
