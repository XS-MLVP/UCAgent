"""SIGINT handler mixin for UCAgent TUI."""

from __future__ import annotations

import signal
from typing import Any


class SigintHandlerMixin:
    """Mixin that provides SIGINT (Ctrl+C) handling for the TUI app.

    Expected to be mixed with VerifyApp which provides:
    - call_from_thread()
    - cancel_running_command()
    - set_timer()
    - action_quit()

    Attributes:
        _sigint_prev: Previous signal handler to restore on cleanup.
        _sigint_inflight: Flag to prevent re-entrant SIGINT handling.
        _cancel_cooldown: Flag to prevent immediate quit after cancel.
    """

    _sigint_prev: Any = None
    _sigint_inflight: bool = False
    _cancel_cooldown: bool = False

    def install_sigint_handler(self) -> None:
        """Install custom SIGINT handler for the TUI."""
        if self._sigint_prev is not None:
            return
        self._sigint_prev = signal.getsignal(signal.SIGINT)

        def _sigint_handler(_signum, _frame):
            try:
                self.call_from_thread(self._handle_ctrl_c)  # type: ignore[attr-defined]
            except Exception:
                pass

        signal.signal(signal.SIGINT, _sigint_handler)

    def restore_sigint_handler(self) -> None:
        """Restore original SIGINT handler."""
        if self._sigint_prev is None:
            return
        try:
            signal.signal(signal.SIGINT, self._sigint_prev)
        finally:
            self._sigint_prev = None
            self._sigint_inflight = False
            self._cancel_cooldown = False

    def _handle_ctrl_c(self) -> None:
        """Handle Ctrl+C: cancel running command or quit."""
        if self._sigint_inflight:
            return
        self._sigint_inflight = True
        try:
            if self.cancel_running_command():  # type: ignore[attr-defined]
                self._cancel_cooldown = True
                self.set_timer(0.5, self._clear_cancel_cooldown)  # type: ignore[attr-defined]
            elif not self._cancel_cooldown:
                self.action_quit()  # type: ignore[attr-defined]
        finally:
            self._sigint_inflight = False

    def _clear_cancel_cooldown(self) -> None:
        """Clear cancel cooldown flag."""
        self._cancel_cooldown = False
