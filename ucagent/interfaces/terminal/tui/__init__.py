"""Attach the optional Textual frontend to an existing console session."""


def enter_tui(session):
    """Detach back to the console while keeping host-owned operations alive."""
    from ucagent.interfaces.terminal.tui.app import VerifyApp

    app = VerifyApp(session)
    app.run()
    return app.session_output


__all__ = ["enter_tui"]
