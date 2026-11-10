"""Regression tests for model-free Master backend selection."""

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
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(
    repo_package_root + os.sep
):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

from ucagent.core.backends.blank import BlankBackend
from ucagent.application.entry import run
from ucagent import VerifyAgent


def test_cli_master_selects_blank_backend_and_starts_owned_service(tmp_path, cli_runtime):
    """Master selects BlankBackend and starts the service through its runtime owner."""
    with mock.patch(
        "sys.argv",
        ["ucagent", str(tmp_path), "empty", "--as-master", "127.0.0.1:9900"],
    ), mock.patch("ucagent.VerifyAgent") as verify_agent:
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
    assert cli_runtime.registry.execute.call_args_list[0].args[0] == "master_api_start 127.0.0.1 9900"


def test_cli_master_backend_is_a_child_default_without_mcp_requirement(tmp_path, cli_runtime):
    """A Master backend option configures children and must not require local MCP."""
    with mock.patch(
        "sys.argv",
        ["ucagent", "--as-master-persist", str(tmp_path), "--as-master", "--backend", "codex"],
    ), mock.patch("ucagent.VerifyAgent") as verify_agent:
        run()

    kwargs = verify_agent.call_args.kwargs
    assert {"backend.key_name": "blank"} in kwargs["cfg_override"]
    assert {"backend.key_name": "codex"} not in kwargs["cfg_override"]
    assert {"launch.default_args.backend": "codex"} in kwargs["cfg_override"]
    cli_runtime.services.start_mcp.assert_not_called()


def test_cli_master_waits_for_host_shutdown(tmp_path, cli_runtime):
    """Master lifetime is owned by the host rather than by model execution."""
    with mock.patch(
        "sys.argv",
        ["ucagent", str(tmp_path), "empty", "--as-master", "127.0.0.1:9900"],
    ), mock.patch("ucagent.VerifyAgent") as verify_agent:
        agent = verify_agent.return_value
        agent.is_exit.side_effect = [False, True]
        agent.services.get.return_value = None

        run()

    cli_runtime.wait.assert_called_once_with()
    agent.pre_run.assert_called_once()


def test_blank_backend_config_uses_normal_backend_factory_without_model_integrations(
    tmp_path,
):
    """Blank selection must use the factory without constructing model clients."""
    with mock.patch(
        "ucagent.core.agent.construction.SemanticSearchInGuidDoc",
        side_effect=AssertionError("embedding tools must not be initialized"),
    ), mock.patch(
        "ucagent.core.agent.construction.Langfuse",
        side_effect=AssertionError("Langfuse must not be initialized"),
    ):
        agent = VerifyAgent(
            workspace=str(tmp_path),
            dut_name="empty",
            output="unit_test",
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
        from ucagent.runtime.host import RuntimeHost
        host = RuntimeHost(agent, mode="master")
        host.start()
        host.request_shutdown()
        assert host.wait(3)["instance"] == "closed"


def test_blank_backend_rejects_model_work():
    """BlankBackend must report unsupported work and stop repeated work loops."""
    agent = mock.Mock()
    backend = BlankBackend(vagent=agent, config=object())

    expected = "Model work is not supported by BlankBackend."
    assert backend.do_work_values({}, {}) == expected
    assert backend.do_work_stream({}, {}) == expected
    assert agent.message_echo.call_args_list == [mock.call(expected), mock.call(expected)]
    assert agent.set_break.call_args_list == [mock.call(True), mock.call(True)]
