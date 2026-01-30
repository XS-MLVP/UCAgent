"""Mixins for UCAgent TUI application."""

from .console_capture import ConsoleCaptureMixin
from .sigint import SigintHandlerMixin

__all__ = [
    "ConsoleCaptureMixin",
    "SigintHandlerMixin",
]
