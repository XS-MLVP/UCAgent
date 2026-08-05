import os
import sys
from unittest import mock

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, ".."))
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)

loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(repo_package_root + os.sep):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

from ucagent.cli import get_args


def _parse_args(*arguments):
    with mock.patch("sys.argv", ["ucagent", *arguments]):
        return get_args()


def test_langchain_backend_does_not_require_mcp_server():
    args = _parse_args("workspace", "dut", "--backend", "langchain")

    assert args.backend == "langchain"


def test_non_langchain_backend_requires_mcp_server(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_args("workspace", "dut", "--backend", "claude")

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert (
        "--backend='claude' requires '--mcp-server-no-file-tools' or '--mcp-server'"
        in error
    )
    assert "communicate with UCAgent through MCP" in error
    assert "'--mcp-server-no-file-tools' (recommended)" in error


@pytest.mark.parametrize("mcp_option", ["--mcp-server", "--mcp-server-no-file-tools"])
def test_non_langchain_backend_accepts_either_mcp_server_option(mcp_option):
    args = _parse_args(
        "workspace",
        "dut",
        "--backend",
        "claude",
        mcp_option,
    )

    assert args.mcp_server is True or args.mcp_server_no_file_tools is True


def test_non_langchain_backend_allows_embed_tools_when_mcp_is_enabled():
    args = _parse_args(
        "workspace",
        "dut",
        "--backend",
        "codex",
        "--mcp-server",
        "--no-embed-tools",
        "false",
    )

    assert args.mcp_server is True
    assert args.no_embed_tools is False
