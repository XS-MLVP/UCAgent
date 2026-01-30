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
    """

    vpdb: VerifyPDB
    _console_capture: ConsoleCapture | None = None
    _stdout_backup: Any = None
    _stderr_backup: Any = None
    _vpdb_stdout_backup: Any = None
    _vpdb_stderr_backup: Any = None

    def install_console_capture(self) -> None:
        """Install console output capture."""
        if self._console_capture is not None:
            return
        self._console_capture = ConsoleCapture()
        self._stdout_backup = sys.stdout
        self._stderr_backup = sys.stderr
        sys.stdout = self._console_capture  # type: ignore[assignment]
        sys.stderr = self._console_capture  # type: ignore[assignment]
        if self.vpdb.stdout is not None:
            self._vpdb_stdout_backup = self.vpdb.stdout
            self.vpdb.stdout = self._console_capture
        if getattr(self.vpdb, "stderr", None) is not None:
            self._vpdb_stderr_backup = self.vpdb.stderr
            self.vpdb.stderr = self._console_capture

    def restore_console_capture(self) -> None:
        """Restore original stdout/stderr."""
        if self._console_capture is None:
            return
        if self._stdout_backup is not None:
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
