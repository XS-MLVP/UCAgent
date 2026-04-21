"""Terminal User Interface for UCAgent verification using Textual."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ucagent.verify_pdb import VerifyPDB


def enter_tui(vpdb: "VerifyPDB") -> None:
    """Enter the Textual-based TUI.

    Args:
        vpdb: VerifyPDB instance containing the agent and configuration.
    """
    from .app import VerifyApp
    app = VerifyApp(vpdb)
    vpdb._tui_app = app
    try:
        app.run()
    finally:
        vpdb._tui_app = None
        app.cleanup()
        if app.session_output:
            stream = sys.stdout
            visited: set[int] = set()
            while hasattr(stream, "_original") and id(stream) not in visited:
                visited.add(id(stream))
                stream = stream._original
            stream.write(app.session_output)
            flush = getattr(stream, "flush", None)
            if callable(flush):
                flush()


__all__ = ["enter_tui"]
