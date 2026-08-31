"""Regression tests for model-free Master backend selection."""

import os
import sys
from unittest import mock

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, ".."))
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)

loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(
    repo_package_root + os.sep
):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

from ucagent.abackend.blank import BlankBackend
from ucagent.cli import run
from ucagent.verify_agent import VerifyAgent


def test_cli_master_selects_blank_backend_and_keeps_pdb_start_command(tmp_path):
    """Master CLI must select BlankBackend while preserving its PDB commands."""
    with mock.patch(
        "sys.argv",
        ["ucagent", str(tmp_path), "empty", "--as-master", "127.0.0.1:9900"],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    kwargs = verify_agent.call_args.kwargs
    assert "runtime_role" not in kwargs
    assert kwargs["config_file"] == "master.yaml"
    assert {"backend.key_name": "blank"} in kwargs["cfg_override"]
    assert {"langfuse.enable": False} in kwargs["cfg_override"]
    assert {
        "vmanager.llm_suggestion.check_fail_refinement.enable": False
    } in kwargs["cfg_override"]
    assert {
        "vmanager.llm_suggestion.check_pass_refinement.enable": False
    } in kwargs["cfg_override"]
    assert kwargs["no_embed_tools"] is True
    assert "master_api_start 127.0.0.1 9900" in kwargs["init_cmd"]
    verify_agent.return_value.set_break.assert_called_once_with(True)
    verify_agent.return_value.run.assert_called_once_with()


def test_cli_master_backend_is_a_child_default_without_mcp_requirement(tmp_path):
    """A Master backend option configures children and must not require local MCP."""
    with mock.patch(
        "sys.argv",
        ["ucagent", "--as-master-persist", str(tmp_path), "--as-master", "--backend", "codex"],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        run()

    kwargs = verify_agent.call_args.kwargs
    assert {"backend.key_name": "blank"} in kwargs["cfg_override"]
    assert {"backend.key_name": "codex"} not in kwargs["cfg_override"]
    assert {"launch.default_args.backend": "codex"} in kwargs["cfg_override"]
    assert not any(command.startswith("start_mcp_server") for command in kwargs["init_cmd"])


def test_cli_master_reenters_pdb_after_agent_run_returns(tmp_path):
    """Master CLI must keep its PDB control surface alive after ``continue``."""
    with mock.patch(
        "sys.argv",
        ["ucagent", str(tmp_path), "empty", "--as-master", "127.0.0.1:9900"],
    ), mock.patch("ucagent.verify_agent.VerifyAgent") as verify_agent:
        agent = verify_agent.return_value
        agent.is_exit.side_effect = [False, True]
        agent.pdb._master_api_server = None

        run()

    agent.run.assert_called_once_with()
    agent.set_break.assert_has_calls([mock.call(True), mock.call(True)])
    agent.check_pdb_trace.assert_called_once_with()


def test_blank_backend_config_uses_normal_backend_factory_without_model_integrations(
    tmp_path,
):
    """Blank selection must use the factory without constructing model clients."""
    with mock.patch(
        "ucagent.verify_agent.SemanticSearchInGuidDoc",
        side_effect=AssertionError("embedding tools must not be initialized"),
    ), mock.patch(
        "ucagent.verify_agent.Langfuse",
        side_effect=AssertionError("Langfuse must not be initialized"),
    ):
        agent = VerifyAgent(
            workspace=str(tmp_path),
            dut_name="empty",
            output="unity_test",
            config_file="master.yaml",
            cfg_override=[
                {"backend.key_name": "blank"},
                {"launch.default_args.backend": "codex"},
                {"langfuse.enable": False},
                {"vmanager.llm_suggestion.check_fail_refinement.enable": False},
                {"vmanager.llm_suggestion.check_pass_refinement.enable": False},
            ],
            no_embed_tools=True,
            no_history=True,
            gen_instruct_file=None,
        )
    try:
        assert isinstance(agent.backend, BlankBackend)
        assert agent.cfg.backend.key_name == "blank"
        assert agent.cfg.launch.default_args.backend == "codex"
        assert agent.message_manage_node is None
        assert agent.langfuse_enable is False
        assert agent.stage_manager.llm_fail_suggestion is None
        assert agent.stage_manager.llm_pass_suggestion is None
    finally:
        agent.exit()


def test_blank_backend_rejects_model_work():
    """BlankBackend must report unsupported work and stop repeated work loops."""
    agent = mock.Mock()
    backend = BlankBackend(vagent=agent, config=object())

    expected = "Model work is not supported by BlankBackend."
    assert backend.do_work_values({}, {}) == expected
    assert backend.do_work_stream({}, {}) == expected
    assert agent.message_echo.call_args_list == [mock.call(expected), mock.call(expected)]
    assert agent.set_break.call_args_list == [mock.call(True), mock.call(True)]
