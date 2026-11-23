"""Core policy facade; the application injects the session runtime."""
from contextvars import ContextVar
import json
from ucagent.core.workflow.contracts import WorkflowCatalog

CURRENT_REQUEST = ContextVar("global_request", default=None)

class GlobalAgentService:
    def __init__(self, agent, settings, *, catalog=None):
        self.agent = agent
        self.settings = settings
        self.catalog = catalog or WorkflowCatalog(settings, getattr(agent, "plugins", ()))
        self.runtime = None

    def attach_runtime(self, runtime):
        self.runtime = runtime

    def list_workflows(self):
        return {"workflows": [entry.describe() for entry in self.catalog.entries.values()],
                "launch_profiles": self.list_launch_profiles()}

    def list_launch_profiles(self):
        return {name: value.describe() for name, value in self.settings.launch_profiles.items()}

    def dispatch(self, action, **arguments):
        if self.runtime is None:
            raise RuntimeError("Agent session runtime is not ready")
        if action in {"start_super", "retry_super"}:
            arguments["request_id"] = CURRENT_REQUEST.get() or "operator"
        return getattr(self.runtime, action)(**arguments)

    def planning_context(self):
        return ("Respond to the current user request. Start independent Supers when needed; "
                "their accepted results arrive automatically. Do not poll or declare completion early.\n"
                + json.dumps(self.list_workflows(), ensure_ascii=False))
