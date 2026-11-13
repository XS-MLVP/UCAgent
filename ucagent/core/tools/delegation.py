"""Thin local/MCP supervisor tools over the core multi-agent service."""

import asyncio
from typing import Any
from pydantic import Field

from ucagent.core.multi_agent.contracts import StrictModel, TaskPlan
from ucagent.core.tools.uctool import UCTool


class NoArgs(StrictModel):
    """Reject client-supplied identities on server-bound control tools."""


class PlanArgs(StrictModel):
    """Select one already admitted plan."""

    plan_id: str


class StatusArgs(StrictModel):
    """Inspect one plan or the complete run queue."""

    plan_id: str | None = None


class WaitArgs(PlanArgs):
    """Bound a poll independently of the worker runtime budget."""

    timeout: float = Field(default=30, ge=0, le=60, allow_inf_nan=False)


class WorkflowArgs(StrictModel):
    """Start model-led planning and bounded execution for the current workflow."""

    instruction: str | None = Field(default=None, max_length=32000)


class PauseArgs(StrictModel):
    """Report missing information or a decision requiring the user."""

    reason: str = Field(min_length=1, max_length=8000)
    planning_token: str | None = None


class SupervisorTool(UCTool):
    """Keep orchestration implementation out of the transport adapter."""

    service: Any = Field(exclude=True)
    action: str = Field(exclude=True)
    delegate: Any = Field(default=None, exclude=True)

    def display_result(self, content):
        """Use readable orchestration output while preserving read-tool bodies."""
        from ucagent.core.multi_agent.display import control_result
        return control_result(self.action, content)

    def _run(self, **kwargs):
        """Dispatch validated arguments without granting business-write capabilities."""
        self.service.charge_planning_tool(self.action)
        if self.delegate is not None:
            return self.delegate.invoke(kwargs)
        if self.action == "submit":
            try:
                return self.service.submit(kwargs)
            except ValueError as exc:
                if self.service.planning is None:
                    raise
                return {"accepted": False, "error": str(exc),
                        "next_action": "Correct the plan and resubmit within this planning turn"}
        if self.action == "roles":
            from ucagent.core.backends import get_backend_class
            from ucagent.core.multi_agent.contracts import role_backend_config
            return {name: {"description": role.description, "backend": role.backend,
                           "allowed_tools": sorted(set(role.allowed_tools) & self.service.agent.multi_agent_business_names),
                           "budgets": {"model_rounds": get_backend_class(
                               role_backend_config(self.service.agent.cfg, role)).capabilities.model_rounds,
                                       "mcp_tool_calls": True, "absolute_timeout": True},
                           "parallel_scope": "managed file tasks"}
                    for name, role in self.service.settings.roles.items()}
        if self.action == "tips":
            return self.service.planning_context()
        return getattr(self.service, self.action)(**kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        """Preserve capability errors across MCP and retain synchronous task locking."""
        arguments = dict(input)
        arguments.pop("ctx", None)
        return await asyncio.to_thread(self.invoke, arguments, config, **kwargs)


def supervisor_tools(agent):
    """Use one authoritative supervisor view for local and MCP invocation."""
    readonly = {"ReadTextFile", "PathList", "SearchText", "FindFiles", "GetFileInfo", "RoleInfo"}
    tools = [SupervisorTool(name=tool.name, description=tool.description, args_schema=tool.args_schema,
                            service=agent.multi_agent, action="read", delegate=tool)
             for tool in agent.test_tools if tool.name in readonly]
    definitions = [
        ("SubAgentTool", "Submit one plan. Use auto for continuous substages in one worker; task has file tools only. See CurrentTips.delegation before narrowing scope.", TaskPlan, "submit"),
        ("TaskStatus", "Read task results and authoritative validation status.", StatusArgs, "status"),
        ("WaitTasks", "Wait at most 60 seconds for a submitted plan.", WaitArgs, "wait"),
        ("CancelTask", "Cancel a plan; capacity is retained until its workers exit.", PlanArgs, "cancel"),
        ("ListAgentRoles", "List configured worker roles and their available capabilities.", NoArgs, "roles"),
        ("CurrentTips", "Read the active stage and trusted split-task acceptance contracts.", NoArgs, "tips"),
        ("StartWorkflow", "Start the configured Super model's planning/execution loop. Requires a non-blank supervisor backend.", WorkflowArgs, "start_workflow"),
        ("PauseWorkflow", "Stop planning and ask the user for missing information or a decision.", PauseArgs, "pause_workflow"),
    ]
    return tools + [SupervisorTool(name=name, description=description, args_schema=schema,
                                  service=agent.multi_agent, action=action)
                    for name, description, schema, action in definitions]
