"""Direct tools for persistent Global sessions."""
from typing import Any
from pydantic import Field
from ucagent.core.tools.uctool import UCTool, EmptyArgs
from ucagent.core.multi_agent.global_agent.session_contracts import SuperRequest, StrictContract

class DUTArgs(StrictContract):
    """Filter candidate DUT names without selecting a workflow."""
    query: str | None = Field(default=None, max_length=200, description="Optional DUT name filter, for example Adder.")

class AgentArgs(StrictContract):
    agent_id: str = Field(min_length=1, description="Agent identity returned by StartSuper or ListAgents.")

class MessageArgs(AgentArgs):
    message: str = Field(min_length=1, max_length=32000, description="Supplemental instruction for this Super.")

class RecoverArgs(AgentArgs):
    """Resume a displayed interruption without granting budgets or human approval."""
    issue_id: str = Field(min_length=1, description="Current interruption ID from AgentStatus.recovery.issue.")
    message: str = Field(default="", max_length=32000, description="User reply or supplemental guidance.")

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
            if self.action == "recover_super":
                kwargs = {"agent_id": kwargs["agent_id"], "request": {"issue_id": kwargs["issue_id"],
                          "action": "reply" if kwargs.get("message") else "resume", "message": kwargs.get("message", "")}}
            return self.service.dispatch(self.action, **kwargs)
        except (ValueError, KeyError, RuntimeError) as error:
            return {"accepted": False, "error": str(error)[:2000],
                    "next_action": "Inspect ListDUTs, ListWorkflows or AgentStatus and correct the request."}

    def display_result(self, content):
        from ucagent.core.multi_agent.global_agent.display import session_summary
        return session_summary(content)

def global_tools(agent):
    service = agent.global_service
    specs = [
        ("ListDUTs", "Find DUT sources and prepared workspaces. Use exact source_workspace when names are ambiguous.", DUTArgs, "list_duts"),
        ("ListWorkflows", "List available workflow purposes, inputs and outputs.", EmptyArgs, "list_workflows"),
        ("ListLaunchProfiles", "List trusted Super execution profiles.", EmptyArgs, "list_launch_profiles"),
        ("StartSuper", "Start a workflow asynchronously. Returns an Agent ID; completion is delivered automatically. Do not poll.", SuperRequest, "start_super"),
        ("ListAgents", "Inspect the current Agent tree when the user asks for progress.", EmptyArgs, "list_agents"),
        ("AgentStatus", "Inspect one Agent's stage, errors, attempts and accepted artifacts.", AgentArgs, "agent_status"),
        ("RecoverSuper", "Resume or reply to a live paused Super when the user requests it. Budget grants and reviews use operator controls.", RecoverArgs, "recover_super"),
        ("MessageSuper", "Queue guidance for the next planning boundary; this does not resume a paused task.", MessageArgs, "message_super"),
        ("CancelSuper", "Cancel one Super and its workers, retaining history.", AgentArgs, "cancel_super"),
        ("RetrySuper", "Retry a failed or cancelled attempt in a new workspace.", RetryArgs, "retry_super"),
        ("ReadAgentArtifact", "Read an accepted output, rechecking its digest.", ArtifactArgs, "read_agent_artifact"),
    ]
    return [GlobalTool(name=n, description=d, args_schema=s, action=a, service=service) for n,d,s,a in specs]
