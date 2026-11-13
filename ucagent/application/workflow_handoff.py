"""Construct fresh peer workflow instances using trusted application execution settings."""

from pathlib import Path

from ucagent import VerifyAgent
from ucagent.application.launch import configure_services
from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.core.workflow.contracts import execution_overrides, configuration_fingerprint, workflow_fingerprint
from ucagent.runtime.host import RuntimeHost


class WorkflowInstanceFactory:
    """Resolve each target from its own workflow instead of cloning the source Agent config."""

    def __init__(self, prepared, request, catalog, root):
        """Retain connection settings in memory and keep source business overrides out of B."""
        self.execution = execution_overrides(prepared.cfg)
        self.catalog = catalog
        self.request = request
        self.root = Path(root)
        self.empty_config = self.root / "target-defaults.yaml"
        self.empty_config.write_text("{}\n", encoding="utf-8")
        self.dut_name = prepared.dut_name

    def __call__(self, run):
        """Construct one ready Host with no startup commands or business model execution."""
        entry = self.catalog.entries[run["workflow_ref"]]
        if workflow_fingerprint(entry, self.catalog.settings.target_configs.get(entry.ref)) != run["fingerprint"]:
            raise ValueError("Successor workflow sources changed; refusing checkpoint recovery")
        overrides = {**self.execution, "runtime_options.multi_agent_enabled": True,
                     "runtime_options.workflow_handoff_enabled": True,
                     "workflow_handoff": self.catalog.settings.model_dump()}
        config = self.catalog.settings.target_configs.get(run["workflow_ref"], str(self.empty_config))
        prepared = resolve_task_configuration(run["workspace"], self.dut_name, config_file=config,
                    cfg_override=overrides, plugins=[entry.owner], plugin_workflow=entry.ref)
        output = Path(prepared.output)
        if not output.parts or output.is_absolute() or ".." in output.parts or output.parts[0] in {"inputs", ".ucagent", "Guide_Doc"}:
            raise ValueError("Successor output must be an independent workspace-relative business directory")
        for name in prepared.cfg.get_value("write_dirs", []):
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Successor write directories must remain inside its workspace")
        for item in run["input_manifest"]:
            import hashlib
            from ucagent.core.workflow.contracts import source_file
            data = source_file(run["workspace"], item["target"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("Successor input snapshot changed; restore its recorded bytes before recovery")
        prepared.cfg.un_freeze()
        prepared.cfg.set_value("un_write_dirs", list(dict.fromkeys(["inputs", *prepared.cfg.get_value("un_write_dirs", [])])))
        prepared.cfg.freeze()
        fingerprint = configuration_fingerprint(prepared.cfg)
        if run.get("configuration_fingerprint", fingerprint) != fingerprint:
            raise ValueError("Resolved successor configuration changed; refusing checkpoint recovery")
        run["configuration_fingerprint"] = fingerprint
        agent = VerifyAgent(run["workspace"], self.dut_name, None, config_file=config,
                _task_configuration=prepared, _defer_workspace_activation=True,
                no_embed_tools=self.request.task_options.get("no_embed_tools", False))
        host = RuntimeHost(agent, mode="service")
        host.workflow_chain_owned = True
        try:
            configure_services(host.services)
            host.start()
            agent.backend.prepare()
            agent.pre_run()
            return host
        except BaseException as error:
            host.request_shutdown("candidate_startup_failed", exit_code=1)
            # Do not discard resources owned by a still-running initialization/cleanup callback.
            while not host._closed.wait(0.1):
                pass
            error.handoff_candidate = host
            raise


def run_workflow_application(request, prepared, plan, agent_options):
    """Keep a single application lifetime while independently constructing and retiring Supers."""
    import hashlib
    import json
    import os
    import threading
    from uuid import uuid4
    from ucagent.core.workflow.contracts import WorkflowCatalog, load_handoff_settings
    from ucagent.core.workflow.chain import WorkflowChain
    from ucagent.runtime.workflow_checkpoint import WorkflowCheckpoint, policy_fingerprint
    from ucagent.runtime.workflow_handoff import WorkflowHandoff
    from ucagent.runtime.workflow_control import WorkflowApplication
    from ucagent.runtime.session import RuntimeSession
    from ucagent.interfaces.terminal.presentation import format_result, format_operation
    from ucagent.interfaces.terminal.console import Console
    from ucagent.interfaces.terminal.tui import enter_tui
    from ucagent.interfaces.server.api_cmd import ControlApiServer

    settings = load_handoff_settings(prepared.cfg)
    catalog = WorkflowCatalog(settings, prepared.plugins)
    if prepared.plugin_workflow not in catalog.entries:
        raise ValueError("Initial workflow must be present in the trusted handoff catalog")
    root = Path(settings.resume_chain or settings.chain_root or
                (Path(prepared.workspace).parent / ".ucagent-chains" / uuid4().hex)).absolute()
    if root.resolve().is_relative_to(Path(prepared.workspace).resolve()):
        raise ValueError("Chain storage must be outside the initial business workspace")
    checkpoint = WorkflowCheckpoint(root)
    app = None
    host = None
    try:
        execution_hash = hashlib.sha256(json.dumps(execution_overrides(prepared.cfg), sort_keys=True, default=str).encode()).hexdigest()
        state = checkpoint.load(catalog, execution_hash) if settings.resume_chain else None
        source_fingerprint = configuration_fingerprint(prepared.cfg)
        if state is not None and state.get("source_configuration_fingerprint") != source_fingerprint:
            raise ValueError("Resolved source configuration changed; refusing checkpoint recovery")
        if state is None and checkpoint.path.exists():
            raise ValueError("Chain already exists; use workflow_handoff.resume_chain to recover")
        if state is not None:
            if state["status"] == "completed":
                return state
            current = state["runs"][-1]
            transition = current["transition"]
            if transition and transition["kind"] == "next":
                if transition["status"] in {"committed", "retired"}:
                    # A clean checkpoint proves source resources were drained. Keep its unique successor.
                    transition["status"] = "activated"
                    state["runs"].append(transition.pop("successor"))
                elif transition["status"] != "activated":
                    transition.update(status="failed", error="Preparation interrupted by a reconciled shutdown")
                    current["history"].append(transition)
                    current["transition"] = None
            state["status"] = "running"
        chain = WorkflowChain(catalog, prepared.plugin_workflow, prepared.workspace,
                              goal=settings.goal, persist=checkpoint.save, state=state)
        chain.state.update(quiescent=False, policy_fingerprint=policy_fingerprint(settings),
                           execution_fingerprint=execution_hash, source_configuration_fingerprint=source_fingerprint)
        chain.save()
        factory = WorkflowInstanceFactory(prepared, request, catalog, root)
        if chain.current["workspace"] == prepared.workspace and chain.current["workflow_ref"] == prepared.plugin_workflow:
            options = dict(agent_options)
            if state is not None:
                options["no_history"] = False
            agent = VerifyAgent(**options)
            host = RuntimeHost(agent, mode="service")
            host.workflow_chain_owned = True
            configure_services(host.services)
            host.start()
            agent.pre_run()
        else:
            host = factory(chain.current)
        executor = WorkflowHandoff(chain, host, factory, root)
        chain.event("run_attached", run_id=chain.current["run_id"], pid=os.getpid(), session_id=host.agent.session_id.hex)
        app = WorkflowApplication(executor, force_exit=os._exit, interactive=request.interface != "none")
        configure_services(app.services)
        session = RuntimeSession(app, result_formatter=format_result, operation_formatter=format_operation)
        app.session = session
        app.services.command_factory = lambda **options: ControlApiServer(
            app.controller, registry=app.registry, operations=app.operations,
            services=app.services, host_control=app, **options)
        app.services.console_input = lambda line: session.execute_line(line, foreground=False)
        app.services.last_command = lambda: session.session.last_command
        app.services.terminal_prepare = lambda server: server.enter_pty_mode()
        with app.signals():
            if "mcp" in plan.services:
                result = app.services.start_mcp(host=request.mcp_host, port=request.mcp_port,
                                                 no_file_ops=request.mcp_no_file_tools)
                if not result["ok"]:
                    raise RuntimeError(result["message"])
            for command in plan.service_commands:
                result = app.registry.execute(command, session.session)
                if isinstance(result.data, dict) and result.data.get("ok") is False:
                    raise RuntimeError(result.data.get("message", "Service startup failed"))
            commands = [command for command in plan.commands if command != "tui"]
            commands.extend(host.agent.cfg.get_value("init_cmds", []))
            if state is not None or not commands:
                host.agent.multi_agent.start_workflow(settings.goal or None)
            else:
                host.startup.start(commands, session, default_model=plan.default_model,
                                   interactive=plan.mode != "once")
            pump = threading.Thread(target=app.pump, name="ucagent-workflow-chain", daemon=True)
            pump.start()
            console = Console(app, session=session, tui_factory=enter_tui)
            if request.interface == "tui":
                console.output.write(enter_tui(session))
            if plan.mode == "console":
                console.run()
                if not app._closed.is_set() and app.services.status("cmd")["state"] != "ready":
                    app.request_shutdown("console_eof")
            result = app.wait()
            pump.join()
            if result["exit_code"]:
                raise SystemExit(result["exit_code"])
            return chain.view()
    finally:
        if app is not None and not app._closed.is_set():
            app.request_shutdown("application_failure", exit_code=1)
            if not any(t.name == "ucagent-workflow-chain" and t.is_alive() for t in threading.enumerate()):
                app.pump()
            app.wait()
        elif app is None and host is not None:
            host.request_shutdown("application_failure", exit_code=1)
            host.wait()
        checkpoint.close()
