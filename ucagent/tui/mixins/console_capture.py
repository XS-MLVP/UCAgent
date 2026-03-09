"""Console capture mixin for UCAgent TUI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from ..utils import ConsoleCapture

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


class ConsoleCaptureMixin:
    """Mixin that provides stdout/stderr capture for the TUI app.

    Expected to be mixed with VerifyApp which provides:
    - vpdb: VerifyPDB instance
    - query_one(): Widget query method

    Captures console output and redirects it to the TUI console widget.

    Attributes:
        _console_capture: The capture buffer instance.
        _stdout_backup: Original sys.stdout.
        _stderr_backup: Original sys.stderr.
        _vpdb_stdout_backup: Original vpdb.stdout.
        _vpdb_stderr_backup: Original vpdb.stderr.
        _stdout_patched_wrapper: Non-None when sys.stdout had an ``_original``
            attribute (e.g. PdbCmdApiServer's _ConsoleCapture).
        _stdout_original_backup: The value of ``_original`` before we patched it.
        _vpdb_stdout_wrapper: Non-None when vpdb.stdout had ``_original`` but
            sys.stdout did NOT (e.g. Textual replaced sys.stdout before on_mount).
            In this case we re-stack the wrapper on sys.stdout so the ring-buffer
            stays live.
        _vpdb_stdout_wrapper_orig: The original ``_original`` of the wrapper.
    """

    vpdb: VerifyPDB
    _console_capture: ConsoleCapture | None = None
    _stdout_backup: Any = None
    _stderr_backup: Any = None
    _vpdb_stdout_backup: Any = None
    _vpdb_stderr_backup: Any = None
    _stdout_patched_wrapper: Any = None
    _stdout_original_backup: Any = None
    _vpdb_stdout_wrapper: Any = None
    _vpdb_stdout_wrapper_orig: Any = None

    def install_console_capture(self) -> None:
        """Install console output capture."""
        if self._console_capture is not None:
            return
        self._console_capture = ConsoleCapture()
        self._stdout_backup = sys.stdout
        self._stderr_backup = sys.stderr
        # If sys.stdout is already a forwarding wrapper (e.g. PdbCmdApiServer's
        # _ConsoleCapture which has a ring-buffer), redirect its downstream to
        # our capture rather than replacing sys.stdout entirely.  This keeps
        # the ring-buffer live so /api/console continues to receive output
        # during the TUI session.
        if hasattr(sys.stdout, '_original'):
            self._stdout_patched_wrapper = sys.stdout
            self._stdout_original_backup = sys.stdout._original
            sys.stdout._original = self._console_capture  # type: ignore[assignment]
        else:
            self._stdout_patched_wrapper = None
            sys.stdout = self._console_capture  # type: ignore[assignment]
        sys.stderr = self._console_capture  # type: ignore[assignment]
        if self.vpdb.stdout is not None:
            # If pdb.stdout is the same wrapper we already patched above (same
            # object as sys.stdout), it's already wired correctly — skip it.
            if self.vpdb.stdout is self._stdout_patched_wrapper:
                self._vpdb_stdout_backup = None
            elif hasattr(self.vpdb.stdout, '_original'):
                # vpdb.stdout is a forwarding wrapper (e.g. _ConsoleCapture)
                # that we did NOT already handle above — this happens when a
                # TUI framework (Textual) replaced sys.stdout before on_mount
                # but vpdb.stdout still points to the wrapper.
                # Keep the wrapper alive: redirect its downstream to our TUI
                # capture so its ring-buffer still collects output, and put it
                # back on sys.stdout so ALL print() flows through the ring-
                # buffer first.
                self._vpdb_stdout_wrapper = self.vpdb.stdout
                self._vpdb_stdout_wrapper_orig = self.vpdb.stdout._original
                self.vpdb.stdout._original = self._console_capture
                sys.stdout = self.vpdb.stdout  # type: ignore[assignment]
                self._vpdb_stdout_backup = None
            else:
                self._vpdb_stdout_backup = self.vpdb.stdout
                self.vpdb.stdout = self._console_capture
        if getattr(self.vpdb, "stderr", None) is not None:
            self._vpdb_stderr_backup = self.vpdb.stderr
            self.vpdb.stderr = self._console_capture

    def restore_console_capture(self) -> None:
        """Restore original stdout/stderr."""
        if self._console_capture is None:
            return

        if getattr(self, '_vpdb_stdout_wrapper', None) is not None:
            # We patched vpdb.stdout._original and re-stacked the wrapper on
            # sys.stdout.  Restore _original only; sys.stdout will be handled
            # by the TUI framework's own restore and do_tui's finally block.
            self._vpdb_stdout_wrapper._original = self._vpdb_stdout_wrapper_orig
            self._vpdb_stdout_wrapper = None
        elif self._stdout_patched_wrapper is not None:
            # Patched-wrapper mode: cmd_api was running *before* TUI entered
            # AND was detected on sys.stdout.  Restore its downstream.
            self._stdout_patched_wrapper._original = self._stdout_original_backup
            self._stdout_patched_wrapper = None
        elif self._stdout_backup is not None:
            sys.stdout = self._stdout_backup

        if self._stderr_backup is not None:
            sys.stderr = self._stderr_backup

        if self._vpdb_stdout_backup is not None:
            self.vpdb.stdout = self._vpdb_stdout_backup

        if self._vpdb_stderr_backup is not None:
            self.vpdb.stderr = self._vpdb_stderr_backup

        self._console_capture = None

    def flush_console_output(self) -> None:
        """Flush captured console output to the console widget."""
        if self._console_capture is None:
            return
        text = self._console_capture.get_and_clear()
        if not text:
            return
        from ..widgets import ConsoleWidget
        console = self.query_one("#console", ConsoleWidget)  # type: ignore[attr-defined]
        console.append_output(text)
