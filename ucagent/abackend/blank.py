# -*- coding: utf-8 -*-
"""Backend implementation for runtimes that intentionally disable model work."""

from .base import AgentBackendBase


class BlankBackend(AgentBackendBase):
    """Provide backend-shaped status hooks without constructing a model client."""

    _UNAVAILABLE_MESSAGE = "Model work is not supported by BlankBackend."

    def init(self):
        """Initialize the blank backend without external side effects."""

    def get_human_message(self, text: str):
        """Return plain text for status-only callers that format a human message."""
        return text

    def get_system_message(self, text: str):
        """Return plain text for status-only callers that format a system message."""
        return text

    def messages_get_raw(self):
        """Return the empty message history maintained by this backend."""
        return []

    def _unsupported(self):
        """Report unsupported model work and stop the caller's work loop."""
        message_echo = getattr(self.vagent, "message_echo", None)
        if callable(message_echo):
            message_echo(self._UNAVAILABLE_MESSAGE)
        set_break = getattr(self.vagent, "set_break", None)
        if callable(set_break):
            set_break(True)
        return self._UNAVAILABLE_MESSAGE

    def do_work_values(self, instructions, config):
        """Reject non-streaming model work because no model is initialized."""
        return self._unsupported()

    def do_work_stream(self, instructions, config):
        """Reject streaming model work because no model is initialized."""
        return self._unsupported()

    def model_name(self) -> str:
        """Describe the intentionally disabled model in status output."""
        return "Disabled"
