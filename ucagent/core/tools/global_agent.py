"""Direct tools for persistent Global sessions."""
from typing import Any
from pydantic import Field
from ucagent.core.tools.uctool import UCTool, EmptyArgs
from ucagent.core.multi_agent.global_agent.session_contracts import SuperRequest, StrictContract

class AgentArgs(StrictContract):
    agent_id: str = Field(min_length=1, description="Agent identity returned by StartSuper or ListAgents.")

class MessageArgs(AgentArgs):
    message: str = Field(min_length=1, max_length=32000, description="Supplemental instruction for this Super.")

class RetryArgs(AgentArgs):
    attempt: int = Field(ge=1, description="Failed or cancelled attempt from AgentStatus; fences duplicate retries.")

class ArtifactArgs(AgentArgs):
    attempt: int = Field(ge=1, description="Accepted attempt number.")
    path: str = Field(min_length=1, description="Exact accepted artifact path from AgentStatus.")
    max_bytes: int = Field(default=65536, ge=1, le=1048576, description="Maximum returned UTF-8 content bytes.")

class GlobalTool(UCTool):
    service: Any = Field(exclude=True)
    action: str = Field(exclude=True)

    def _run(self, **kwargs):
        """Return direct action results and bounded, actionable errors."""
        try:
            if self.action == "list_workflows": return self.service.list_workflows()
            if self.action == "list_launch_profiles": return self.service.list_launch_profiles()
            if self.action == "start_super": kwargs = {"request": SuperRequest.model_validate(kwargs)}
            return self.service.dispatch(self.action, **kwargs)
        except (ValueError, KeyError, RuntimeError) as error:
            return {"accepted": False, "error": str(error)[:2000],
                    "next_action": "Inspect ListWorkflows or AgentStatus and correct the request."}

    def display_result(self, content):
        from ucagent.core.multi_agent.global_agent.display import session_summary
        return session_summary(content)

def global_tools(agent):
    service = agent.global_service
    specs = [
        ("ListWorkflows", "List available workflow purposes, inputs and outputs.", EmptyArgs, "list_workflows"),
        ("ListLaunchProfiles", "List trusted Super execution profiles.", EmptyArgs, "list_launch_profiles"),
        ("StartSuper", "Start a workflow asynchronously. Returns an Agent ID; completion is delivered automatically. Do not poll.", SuperRequest, "start_super"),
        ("ListAgents", "Inspect the current Agent tree when the user asks for progress.", EmptyArgs, "list_agents"),
        ("AgentStatus", "Inspect one Agent's stage, errors, attempts and accepted artifacts.", AgentArgs, "agent_status"),
        ("MessageSuper", "Queue a supplemental instruction for an active Super.", MessageArgs, "message_super"),
        ("CancelSuper", "Cancel one Super and its workers, retaining history.", AgentArgs, "cancel_super"),
        ("RetrySuper", "Retry a failed or cancelled attempt in a new workspace.", RetryArgs, "retry_super"),
        ("ReadAgentArtifact", "Read an accepted output, rechecking its digest.", ArtifactArgs, "read_agent_artifact"),
    ]
    return [GlobalTool(name=n, description=d, args_schema=s, action=a, service=service) for n,d,s,a in specs]
