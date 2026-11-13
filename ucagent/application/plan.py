"""Normalized launch input and execution policy derived from the resolved task configuration."""

from dataclasses import dataclass, field
from typing import Any
import shlex

from ucagent.core.backends import get_backend_class
from ucagent.runtime.control.commands import DEFERRED_COMMANDS


@dataclass(frozen=True)
class LaunchRequest:
    """Carry caller intent independently of its CLI or Python entrypoint."""

    task_options: dict[str, Any] = field(repr=False)
    plugin_selectors: tuple[str, ...] = ()
    workspace_base: str = "/tmp/ucagent_workspace_base"
    temporary_prefix: str | None = None
    create_workspace: bool = False
    create_dut: bool = False
    master: bool = False
    emulate_config: bool = False
    interface: str = "none"
    services: tuple[str, ...] = ()
    service_commands: tuple[str, ...] = field(default=(), repr=False)
    commands: tuple[str, ...] = field(default=(), repr=False)
    mcp_host: str | None = None
    mcp_port: int | None = None
    mcp_no_file_tools: bool = False
    log: bool = False
    log_file: str | None = None
    msg_file: str | None = None
    web_console_session: dict | None = None


@dataclass(frozen=True)
class LaunchPlan:
    """Describe startup choices without holding owners or mutable runtime state."""

    mode: str
    backend: str
    interface: str
    services: tuple[str, ...]
    service_commands: tuple[str, ...]
    commands: tuple[str, ...]
    default_model: bool
    model_requested: bool
    embedding: bool
    fail_suggestion: bool
    pass_suggestion: bool


def build_launch_plan(request: LaunchRequest, cfg) -> LaunchPlan:
    """Validate actual backend needs and derive startup policy without creating runtime owners."""
    if request.master and cfg.get_value("runtime_options.multi_agent_enabled", False):
        raise ValueError("Multi-agent execution is not supported in Master mode")
    backend_class = get_backend_class(cfg)
    start_mcp = "mcp" in request.services
    mode = ("master" if request.master else "console" if request.interface != "none"
            else "service" if request.services else "once")
    default_model = mode == "once" and not request.emulate_config
    model_commands = {name for spec in DEFERRED_COMMANDS if spec.model
                      for name in (spec.name, *spec.aliases)}
    commands = [*request.commands, *cfg.get_value("init_cmds", [])]
    model_requested = not request.emulate_config and (default_model or any(
        tokens and tokens[0] in model_commands for tokens in (shlex.split(command) for command in commands)))
    managed = (cfg.get_value("runtime_options.multi_agent_enabled", False)
               and backend_class.capabilities.managed_sessions)
    if model_requested and backend_class.requires_mcp and not start_mcp and not managed:
        raise ValueError(f"backend={cfg.backend.key_name!r} requires '--mcp-server-no-file-tools' or '--mcp-server': "
                         "command-line backends communicate with UCAgent through MCP; "
                         "enable '--mcp-server-no-file-tools' (recommended).")
    return LaunchPlan(mode, cfg.backend.key_name, request.interface, request.services,
        request.service_commands, request.commands, default_model, model_requested,
        not request.task_options.get("no_embed_tools", False),
        cfg.get_value("vmanager.llm_suggestion.check_fail_refinement.enable", False),
        cfg.get_value("vmanager.llm_suggestion.check_pass_refinement.enable", False))
