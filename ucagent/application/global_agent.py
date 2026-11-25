"""Application assembly for persistent Global and child Super sessions."""
from pathlib import Path
from ucagent import SubprocessSuperLauncher
from ucagent import AgentSessions
from ucagent import AgentMessages

def configure_agent_sessions(agent, prepared):
    host = agent.runtime_host
    result_path = agent.cfg.get_value("agent_run.result_path", None)
    if result_path:
        result_path = Path(result_path).resolve()
        if result_path.is_relative_to(Path(agent.workspace).resolve()):
            raise ValueError("Agent runtime state must be outside the business workspace")
        journal = AgentMessages(result_path.with_name("messages.jsonl"))
        host.messages.subscribe(journal.write)
        agent.suppress_tool_result_messages = True
        def close_journal():
            host.messages.unsubscribe(journal.write)
            journal.close()
        host.add_cleanup(close_journal)
        from ucagent import LocalAgentView
        from ucagent import AgentSessionServer
        view = LocalAgentView(host, result_path.parent, agent.cfg.get_value("agent_run.id"),
                              agent.cfg.get_value("agent_run.attempt", 1))
        host.add_cleanup(view.close)
        server = AgentSessionServer(view, result_path.parent).start()
        host.agent_view = view
        host.attach_control("agent-session")
        host.add_cleanup(lambda: host.detach_control("agent-session"))
        host.add_cleanup(server.close)
    service = getattr(agent, "global_service", None)
    if service is None: return None
    project = prepared.project_root or agent.workspace
    session_dir = Path(agent.workspace).parent if prepared.project_root else None
    launcher = SubprocessSuperLauncher(service.settings, session_dir or agent.workspace, project,
                    config_file=getattr(agent, "config_file", None))
    runtime = AgentSessions(service, project, launcher=launcher, host=host, session_dir=session_dir)
    service.attach_runtime(runtime)
    host.agent_sessions = runtime
    def global_message(text):
        for start in range(0, len(text), 16384):
            runtime.events.append("global", "message", text=text[start:start + 16384])
    host.messages.subscribe(global_message)
    host.add_cleanup(lambda: host.messages.unsubscribe(global_message))
    host.add_cleanup(runtime.close)
    runtime.start()
    return runtime
