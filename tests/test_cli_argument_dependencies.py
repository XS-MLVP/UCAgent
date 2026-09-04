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

from ucagent.cli import get_args, run


def _parse_args(*arguments):
    with mock.patch("sys.argv", ["ucagent", *arguments]):
        return get_args()


def test_skill_support_uses_config_default_and_accepts_explicit_overrides():
    default_args = _parse_args("workspace", "dut")
    enabled_args = _parse_args("workspace", "dut", "--use-skill")
    disabled_args = _parse_args("workspace", "dut", "--no-use-skill")

    assert default_args.use_skill is True
    assert default_args._use_skill_explicit is False
    assert enabled_args.use_skill is True
    assert enabled_args._use_skill_explicit is True
    assert disabled_args.use_skill is False
    assert disabled_args._use_skill_explicit is True


@pytest.mark.parametrize(
    ("arguments", "expected_overrides"),
    [
        ([], []),
        (["--use-skill"], [{"skill.use_skill": True}]),
        (["--no-use-skill"], [{"skill.use_skill": False}]),
    ],
)
def test_skill_cli_only_overrides_config_when_explicit(
    tmp_path, arguments, expected_overrides
):
    with mock.patch("sys.argv", ["ucagent", str(tmp_path), "dut", *arguments]), \
            mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    assert verify_agent.call_args.kwargs["cfg_override"] == expected_overrides


def test_extra_skill_path_enables_skill_support(tmp_path):
    skill_path = tmp_path / "extra-skills"
    skill_path.mkdir()

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(tmp_path),
            "dut",
            "--extra-skill-path",
            str(skill_path),
        ],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    assert verify_agent.call_args.kwargs["cfg_override"] == [
        {"skill.use_skill": True},
        {"skill.extra_skill_path": str(skill_path)},
    ]


def test_extra_skill_path_rejects_explicitly_disabled_skills(tmp_path):
    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(tmp_path),
            "dut",
            "--no-use-skill",
            "--extra-skill-path",
            str(tmp_path / "extra-skills"),
        ],
    ), pytest.raises(
        ValueError, match="--extra-skill-path cannot be used with --no-use-skill"
    ):
        run()


def test_langchain_backend_does_not_require_mcp_server():
    args = _parse_args("workspace", "dut", "--backend", "langchain")

    assert args.backend == "langchain"


def test_blank_backend_does_not_require_mcp_server():
    """BlankBackend is a local no-model backend and has no MCP dependency."""
    args = _parse_args("workspace", "dut", "--backend", "blank")

    assert args.backend == "blank"


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
