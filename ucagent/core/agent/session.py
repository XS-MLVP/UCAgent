"""Backend-independent logical Agent sessions shared by supervised and delegated work."""

from pathlib import Path

from ucagent.core.backends import get_backend


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
        """Charge one bounded execution turn and delegate only through the backend contract."""
        self.before_turn()
        return self.backend.run_turn(instructions, config, stream=stream)

    def close(self):
        """Drain the backend before revoking its owned process, model or endpoint resources."""
        return self.backend.close()
