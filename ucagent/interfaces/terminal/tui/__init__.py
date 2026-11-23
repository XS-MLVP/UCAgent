"""Attach the optional Textual frontend to an existing console session."""


def enter_tui(session):
    """Detach back to the console while keeping host-owned operations alive."""
    from ucagent.interfaces.terminal.tui.app import VerifyApp

    if getattr(session.host, "agent_sessions", None) is not None:
        from ucagent.interfaces.terminal.tui.global_app import GlobalApp
        app = GlobalApp(session)
    else:
        app = VerifyApp(session)
    app.run()
    return app.session_output


__all__ = ["enter_tui"]
