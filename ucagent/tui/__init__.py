"""Terminal User Interface for UCAgent verification using Textual."""

from __future__ import annotations

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
    try:
        app.run()
    finally:
        app.cleanup()
        if app.session_output:
            print(app.session_output)


__all__ = ["enter_tui"]
