"""Mixins for UCAgent TUI application."""

from .auto_scroll import AutoScrollMixin
from .console_capture import ConsoleCaptureMixin
from .sigint import SigintHandlerMixin

__all__ = [
    "AutoScrollMixin",
    "ConsoleCaptureMixin",
    "SigintHandlerMixin",
]
