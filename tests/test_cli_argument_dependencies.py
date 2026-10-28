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


def test_cli_starts_mcp_before_headless_backend_run(tmp_path):
    """Headless command-line backends must receive a ready MCP endpoint."""

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(tmp_path),
            "dut",
            "--backend",
            "opencode",
            "--mcp-server-no-file-tools",
            "--mcp-server-port",
            "-1",
        ],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        agent = verify_agent.return_value
        agent.cfg.mcp_server.host = "127.0.0.1"
        lifecycle = []

        def start_mcp(**kwargs):
            lifecycle.append(("start_mcp", kwargs))
            return True, "MCP server started"

        def run_agent():
            lifecycle.append(("run", {}))

        agent.pdb.start_mcp_server.side_effect = start_mcp
        agent.run.side_effect = run_agent

        run()

    kwargs = verify_agent.call_args.kwargs
    assert not any(
        command.startswith("start_mcp_server")
        for command in kwargs["init_cmd"]
    )
    assert lifecycle[0][0] == "start_mcp"
    assert lifecycle[0][1]["host"] == "127.0.0.1"
    assert isinstance(lifecycle[0][1]["port"], int)
    assert lifecycle[0][1]["no_file_ops"] is True
    assert lifecycle[1] == ("run", {})


def test_cli_aborts_before_backend_run_when_mcp_start_fails(tmp_path):
    """An unavailable MCP endpoint must stop command-line model execution."""

    with mock.patch(
        "sys.argv",
        [
            "ucagent",
            str(tmp_path),
            "dut",
            "--backend",
            "opencode",
            "--mcp-server-no-file-tools",
        ],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        agent = verify_agent.return_value
        agent.pdb.start_mcp_server.return_value = (
            False,
            "MCP server failed to start",
        )

        with pytest.raises(RuntimeError, match="MCP server failed to start"):
            run()

    agent.run.assert_not_called()


@pytest.mark.parametrize("interactive", [False, True])
def test_headless_worker_starts_transports_before_model_without_recording_secrets(tmp_path, interactive):
    """Start headless worker services once while keeping interactive startup deferred."""
    lifecycle = []
    arguments = ["ucagent", str(tmp_path), "dut", "--export-cmd-api", "127.0.0.1:19901 fixture-password",
                 "--master", "127.0.0.1:19902", "fixture-key", "--client-id", "fixture-agent"]
    if interactive:
        arguments.append("--human")
    with mock.patch("sys.argv", arguments), mock.patch("ucagent.verify_agent.VerifyAgent") as factory:
        agent = factory.return_value

        def make_agent(**kwargs):
            """Model the real PDB startup queue without starting any sockets."""
            agent.pdb.init_cmd = list(kwargs["init_cmd"])
            return agent

        def start_cmd(argument):
            """Record order and arguments without echoing credentials."""
            lifecycle.append("cmd")
            assert "fixture-password" in argument

        def connect_master(argument):
            """Require the CMD transport before advertising the worker."""
            lifecycle.append("master")
            assert "fixture-key" in argument and "fixture-agent" in argument

        def run_agent():
            """Observe the transport state at the first model invocation."""
            lifecycle.append("model")

        factory.side_effect = make_agent
        agent.pdb.do_cmd_api_start.side_effect = start_cmd
        agent.pdb.do_connect_master_to.side_effect = connect_master
        agent.run.side_effect = run_agent
        run()
    if interactive:
        assert lifecycle == ["model"]
        assert any(command.startswith("connect_master_to ") for command in agent.pdb.init_cmd)
    else:
        assert lifecycle == ["cmd", "master", "model"]
        assert not any(command.startswith(("cmd_api_start ", "connect_master_to "))
                       for command in agent.pdb.init_cmd)
    agent.pdb.execute_command.assert_not_called()



@pytest.mark.parametrize("interactive", [False, True])
def test_loop_message_reaches_headless_first_turn(tmp_path, interactive):
    """Explicit loop instructions reach the model instead of an undrained PDB queue."""
    message = "Resume existing evidence; do not rerun tests."
    arguments = ["ucagent", str(tmp_path), "dut", "--loop", "--loop-msg", message]
    if interactive:
        arguments.append("--human")
    with mock.patch("sys.argv", arguments), mock.patch("ucagent.verify_agent.VerifyAgent") as factory:
        agent = factory.return_value

        def make_agent(**kwargs):
            """Retain the real startup command list for headless queue assertions."""
            agent.pdb.init_cmd = list(kwargs["init_cmd"])
            return agent

        def run_agent():
            """The first model turn must already have the requested instructions."""
            if not interactive:
                agent.set_continue_msg.assert_called_once_with(message)

        factory.side_effect = make_agent
        agent.run.side_effect = run_agent
        run()
    if interactive:
        agent.set_continue_msg.assert_not_called()
        assert "loop " + message in agent.pdb.init_cmd
    else:
        assert "loop " + message not in agent.pdb.init_cmd
