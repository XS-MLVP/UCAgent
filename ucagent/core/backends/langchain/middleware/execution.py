"""LangChain-only adaptation of the owner's backend-neutral model budget callback."""

from langchain.agents.middleware import AgentMiddleware, hook_config


class ExecutionBudget(AgentMiddleware):
    """Apply the logical session's model boundary without owning task scheduling."""

    def __init__(self, *, session):
        """Adapt the session's model boundary without importing the task service."""
        self.boundary = session.before_model

    @hook_config(can_jump_to=['end'])
    def before_model(self, state, runtime):
        """Run the trusted callback before any new provider request."""
        return self.boundary()
