"""Verify Master defaults reach child CLI service and file-tool policy independently."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.interfaces.server.api_master import MasterApiServer
from ucagent.interfaces.server.api_master.common import _merge_launch_default_args
from ucagent.util.config import Config, load_yaml_with_env_vars


@pytest.mark.parametrize("backend", ["codex", "opencode", "langchain"])
@pytest.mark.parametrize("disabled", [None, False, True])
def test_master_defaults_and_explicit_choices_reach_child_cli(tmp_path, backend, disabled):
    """The real defaults, merge and command builder must enable MCP without losing False."""
    settings = load_yaml_with_env_vars(str(Path(__file__).parents[1] / "ucagent/setting.yaml"))
    defaults = settings["launch"]["default_args"]
    assert defaults["mcp_server"] is True
    assert defaults["mcp_server_no_file_tools"] is False
    server = MasterApiServer(workspace=str(tmp_path), cfg=Config({"launch": {"default_args": defaults}}).freeze())
    response = TestClient(server._app).get("/api/launch/config")
    assert response.status_code == 200
    assert response.json()["default_args"]["mcp_server"] is True
    request = {"backend": backend, "use_zip_workspace": False, "launch_mode": "process",
               "workspace_base": str(tmp_path)}
    if disabled is not None:
        request["mcp_server_no_file_tools"] = disabled
    merged = _merge_launch_default_args(request, defaults)
    command, _ = server._build_ucagent_command(
        merged, {"workspace_dir": str(tmp_path), "dut_name": "Adder"},
        {"host": "127.0.0.1", "port": 8818, "password": ""},
    )
    assert command.count("--mcp-server") == 1
    assert ("--mcp-server-no-file-tools" in command) is bool(disabled)
    with patch("sys.argv", ["ucagent", *command[2:]]):
        options = parse_launch_options(get_args())
    assert "mcp" in options["services"]
    assert options["mcp_no_file_tools"] is bool(disabled)


def test_explicit_false_overrides_a_disabled_file_tools_default():
    """Server default merging must respect the user's opt-in to full MCP tools."""
    merged = _merge_launch_default_args(
        {"mcp_server_no_file_tools": False},
        {"mcp_server": True, "mcp_server_no_file_tools": True},
    )
    assert merged == {"mcp_server": True, "mcp_server_no_file_tools": False}
