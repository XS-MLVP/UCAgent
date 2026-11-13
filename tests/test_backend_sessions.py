"""Focused backend contract, inheritance and session lifecycle regressions."""

import threading
from types import SimpleNamespace

import pytest

from ucagent.core.backends.base import AgentBackendBase
from test_multi_agent import make_agent


@pytest.mark.parametrize('backend', ['langchain', 'codex', 'opencode'])
def test_worker_inherits_selected_backend_without_initializing_models(tmp_path, backend):
    """One resolved backend key controls both roles before model or CLI startup."""
    agent = make_agent(tmp_path, config_overrides={'backend.key_name': backend})
    try:
        assert agent.multi_agent.settings.roles['worker'].backend == backend
        assert not agent.multi_agent.records
    finally:
        agent._startup_cleanup.close()


def test_conflicting_role_backend_fails_during_configuration(tmp_path):
    """A legacy role default cannot silently turn Codex multi mode into a mixed run."""
    with pytest.raises(ValueError, match='conflicts'):
        make_agent(tmp_path, config_overrides={'backend.key_name': 'codex'},
                   roles={'worker': {'backend': 'langchain', 'system': 'Work'}})


def test_backend_turn_keeps_ownership_until_execution_returns():
    """Cancellation does not release a still-running synchronous backend turn."""
    entered, release = threading.Event(), threading.Event()

    class HeldBackend(AgentBackendBase):
        """Represent a backend that cannot stop its synchronous request immediately."""

        def do_work_values(self, instructions, config):
            """Retain execution until the external request actually finishes."""
            entered.set()
            assert release.wait(3)

    backend = HeldBackend(SimpleNamespace(is_break=lambda: False), None)
    thread = threading.Thread(target=backend.run_turn, args=({},))
    thread.start()
    try:
        assert entered.wait(2)
        backend.cancel()
        assert not backend.wait_idle(0)
        assert not backend.close(0)
        with pytest.raises(RuntimeError, match='already executing'):
            backend.run_turn({})
    finally:
        release.set()
        thread.join(3)
    assert backend.wait_idle(0)


def test_managed_backend_launch_does_not_depend_on_interface():
    """The same backend works with or without a public MCP service or TUI selection."""
    from ucagent.application.plan import LaunchRequest, build_launch_plan
    from ucagent.util.config import Config
    cfg = Config({"backend": {"key_name": "external", "external": {
        "clss": "ucagent.core.backends.cmdline.SessionCommandBackend", "args": {"argv": ["adapter"]}}},
        "runtime_options": {"multi_agent_enabled": True},
        "vmanager": {"llm_suggestion": {"check_fail_refinement": {"enable": False},
                                           "check_pass_refinement": {"enable": False}}}})
    for interface, services in [("none", ()), ("tui", ()), ("tui", ("mcp",))]:
        plan = build_launch_plan(LaunchRequest(task_options={}, interface=interface, services=services, commands=("loop",)), cfg)
        assert plan.backend == "external" and plan.model_requested
    cfg.set_value("runtime_options.multi_agent_enabled", False)
    with pytest.raises(ValueError, match="requires"):
        build_launch_plan(LaunchRequest(task_options={}), cfg)


def test_single_cli_endpoint_uses_ready_service_url(tmp_path):
    """Single CLI keeps the existing public-service contract and adds the MCP route once."""
    from ucagent.core.backends.cmdline import SessionCommandBackend
    from ucagent.util.config import Config
    owner = SimpleNamespace(workspace=str(tmp_path), services=SimpleNamespace(
        require_endpoint=lambda name: {"url": "http://127.0.0.1:12345", "port": 12345}))
    backend = SessionCommandBackend(owner, Config({}), argv=["adapter"])
    backend.init()
    try:
        backend.prepare()
        assert backend.endpoint["url"] == "http://127.0.0.1:12345/mcp"
        assert not hasattr(owner, "execution_session")
    finally:
        backend.close()
    from ucagent.core.backends import get_backend
    from ucagent.util.config import load_yaml_with_env_vars
    from pathlib import Path
    cfg = Config(load_yaml_with_env_vars(Path(__file__).parents[1] / "ucagent/setting.yaml"))
    cfg.set_value("backend.key_name", "codex")
    backend = get_backend(owner, cfg)
    backend.init()
    try:
        backend.prepare()
        argv = backend.build_argv()
        assert 'sandbox_mode="workspace-write"' in argv
        assert 'features.shell_tool=false' not in argv
    finally:
        backend.close()
