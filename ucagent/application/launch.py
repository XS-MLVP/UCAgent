"""Launch services and frontends, handing acquired resources to RuntimeHost."""

from contextlib import ExitStack
import os
import sys

from ucagent.application.preparation import prepare_launch
from ucagent.application.plan import LaunchRequest


def run_application(request: LaunchRequest):
    """Prepare one task and retain startup cleanup until its host accepts ownership."""
    from ucagent import VerifyAgent
    from ucagent.runtime.host import RuntimeHost
    from ucagent.interfaces.terminal.console import Console
    from ucagent.runtime.session import RuntimeSession
    from ucagent.interfaces.terminal.presentation import format_result, format_operation
    from ucagent.interfaces.server.api_cmd import ControlApiServer
    from ucagent.interfaces.terminal.tui import enter_tui

    with ExitStack() as workspace_cleanup:
        prepared, plan, agent_options = prepare_launch(request, cleanup=workspace_cleanup)
        agent = VerifyAgent(**agent_options)
        # The workspace is released last, after backend and file-policy cleanup.
        acquired = workspace_cleanup.pop_all()
        acquired.callback(agent._startup_cleanup.close)
        agent._startup_cleanup = acquired
        with acquired:
            if request.web_console_session is not None:
                agent.web_console_session_info = dict(request.web_console_session)

            mode = plan.mode
            host = RuntimeHost(agent, mode=mode, exit_on_completion=request.task_options.get("exit_on_completion", False), force_exit=os._exit)
            try:
                configure_services(host.services)
                session = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
                console = (Console(host, session=session, tui_factory=enter_tui)
                           if mode == "console" or (request.interface == "tui") or (mode == "master" and sys.stdin.isatty()) else None)
                host.services.command_factory = lambda **options: ControlApiServer(
                    host.controller, registry=host.registry, operations=host.operations,
                    services=host.services, host_control=host, **options)
                host.services.console_input = lambda line: session.execute_line(line, foreground=False)
                host.services.last_command = lambda: session.session.last_command
                host.services.terminal_prepare = lambda server: server.enter_pty_mode()
                host.start()
                with host.signals():
                    if "mcp" in plan.services:
                        result = host.services.start_mcp(
                            host=request.mcp_host, port=request.mcp_port,
                            no_file_ops=request.mcp_no_file_tools)
                        if not result["ok"]:
                            raise RuntimeError(result["message"])
                    # Service readiness precedes all user/model work, independently of the display.
                    for command in plan.service_commands:
                        result = host.registry.execute(command, session.session)
                        host.output.emit(session.format_result(result) + "\n")
                        if isinstance(result.data, dict) and result.data.get("ok") is False:
                            raise RuntimeError(result.data.get("message", "Service startup failed"))
                    commands = [command for command in plan.commands if command != "tui"]
                    commands.extend(agent.cfg.get_value("init_cmds", []))
                    if request.emulate_config:
                        agent.emulate_config()
                        host.request_shutdown("emulation_finished")
                    else:
                        agent.pre_run()
                        host.startup.start(commands, session, wait_for_display=(request.interface == "tui"),
                                           interactive=mode in {"console", "service", "master"},
                                           default_model=plan.default_model)
                        if request.interface == "tui":
                            console.output.write(enter_tui(session))
                            console.output.flush()
                        if mode == "console" or (mode == "master" and sys.stdin.isatty()):
                            console.run()
                            # EOF is a launch-policy decision; detaching a view never shuts down its host.
                            if host.snapshot()["instance"] == "ready" and host.services.status("cmd")["state"] != "ready":
                                host.request_shutdown("console_eof")
                    state = host.wait()
                    if state["exit_code"]:
                        for error in state.get("errors", []):
                            print(f"Cleanup failed ({error['step']}): {error['message']}")
                        raise SystemExit(state["exit_code"])
            except BaseException:
                host.request_shutdown("startup_or_runtime_failure", exit_code=1)
                host.wait(host.shutdown_timeout)
                raise



def configure_services(services):
    """Bind concrete service constructors while runtime retains their lifetime ownership."""
    from ucagent.interfaces.server.api_master.client import MasterClient
    from ucagent.interfaces.server.api_master.server import MasterApiServer
    from ucagent.interfaces.server.api_mcp import McpServer, _collect_mcp_tools
    from ucagent.interfaces.server.api_terminal import WebTerminalServer

    services.client_factory = MasterClient
    services.master_factory = MasterApiServer
    services.terminal_factory = WebTerminalServer
    services.mcp_factory = lambda host, port, no_file_ops: McpServer(
        _collect_mcp_tools(services.agent, no_file_ops), cfg=services.agent.cfg,
        host=host, port=port, no_file_ops=no_file_ops,
        logger=getattr(services.agent, "_mcps_logger", None),
    )
