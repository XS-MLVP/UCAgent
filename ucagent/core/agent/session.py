"""Backend-independent logical Agent sessions shared by supervised and delegated work."""

from pathlib import Path

from ucagent import get_backend


class AgentSession:
    """Bind one owner, tool view and execution lifecycle without rebuilding workflow resources."""

    def __init__(self, owner, *, directory, before_turn, before_model, yielded, endpoint_factory):
        """Reuse the owner's backend when present; otherwise use the shared backend factory."""
        self.owner = owner
        self.directory = Path(directory)
        self.before_turn = before_turn
        self.before_model = before_model
        self.yielded = yielded
        self.endpoint_factory = endpoint_factory
        owner.execution_session = self
        if owner.backend is None:
            owner.backend = get_backend(owner, owner.cfg)
            owner.backend.init()

    @property
    def backend(self):
        """Keep the public Agent backend reference authoritative, including explicit replacement."""
        return self.owner.backend

    def run_turn(self, instructions, config=None, *, stream=False):
        """Count a backend turn and observe managed CLI errors without setting a run deadline."""
        self.before_turn()
        try:
            result = self.backend.run_turn(instructions, config, stream=stream)
        except Exception as error:
            # LangChain records provider failures at its request boundary; command
            # backends expose failures only after their managed turn returns.
            if not self.backend.capabilities.model_rounds:
                observer = getattr(self.owner, "observe_backend_failure", None)
                if callable(observer):
                    observer(error, phase="turn")
                else:
                    service = getattr(self.owner, "multi_agent", None)
                    observer = getattr(service, "observe_supervisor_failure", None)
                    if callable(observer):
                        observer("supervisor_backend", error=error, phase="turn")
            raise
        else:
            if not self.backend.capabilities.model_rounds:
                observer = getattr(self.owner, "observe_backend_success", None)
                if callable(observer):
                    observer()
                else:
                    service = getattr(self.owner, "multi_agent", None)
                    observer = getattr(service, "observe_supervisor_success", None)
                    if callable(observer):
                        observer("supervisor_backend")
            return result

    def close(self):
        """Drain the backend before revoking its owned process, model or endpoint resources."""
        return self.backend.close()
