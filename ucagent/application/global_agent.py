"""Application assembly for persistent Global and child Super sessions."""
from pathlib import Path
from ucagent.interfaces.server.super_launcher import SubprocessSuperLauncher
from ucagent.runtime.agent_sessions import AgentSessions
from ucagent.runtime.agent_messages import AgentMessages

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
        from ucagent.runtime.agent_view import LocalAgentView
        from ucagent.interfaces.server.agent_session import AgentSessionServer
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
    launcher = SubprocessSuperLauncher(service.settings, agent.workspace, agent.workspace,
                    config_file=getattr(agent, "config_file", None), dut_name=getattr(agent, "dut_name", None))
    runtime = AgentSessions(service, agent.workspace, launcher=launcher, host=host)
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
