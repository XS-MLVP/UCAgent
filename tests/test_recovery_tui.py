"""Headless interaction and narrow-terminal checks for actionable pause cards."""
import copy
import pytest
from textual.widgets import Button, Input, Static
from ucagent.interfaces.terminal.tui.global_app import AttachApp
from ucagent.interfaces.terminal.tui.agent_screen import AgentScreen
from ucagent.interfaces.terminal.tui.widgets.recovery import RecoveryDialog, RecoveryPanel


class View:
    """A detached live snapshot that records only operator recovery calls."""
    agent_id = "super-demo"

    def __init__(self, kind="budget"):
        self.calls = []
        self.data = {"role": "super", "status": "waiting_input", "readonly": False, "connected": True,
                     "stage_index": 1, "control_revision": 4, "children": [], "stages": [], "commands": [],
                     "recovery": {"issue": {"id": "pause-1", "kind": kind, "source": "runtime",
                        "summary": "Execution needs operator attention", "next_action": "Resolve and continue",
                        "task_id": "plan/task", "budget": {"dimension": "worker_tool_calls", "used": 200, "limit": 200}},
                        "planning": {"used": 2, "limit": 3}, "actions": ["grant"] if kind == "budget" else ["reply"],
                        "suggested_grant": {"worker_tool_calls": 100}}}

    def snapshot(self):
        """Return detached data, as the real session transport does."""
        return copy.deepcopy(self.data)

    def events_since(self, cursor=0):
        """No messages are needed to render persisted interruption state."""
        return {"events": [], "cursor": cursor}

    def recover(self, request):
        """Record an explicit action without creating a model or process."""
        self.calls.append(request)
        self.data["recovery"]["issue"] = None
        self.data["recovery"]["actions"] = []
        self.data["status"] = "running"
        return {"accepted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(140, 44), (80, 32)])
async def test_budget_form_is_visible_and_sends_explicit_additions(size, tmp_path):
    """Both terminal sizes keep controls reachable and send the displayed increment."""
    view = View()
    app = AttachApp(view)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(.3)
        panel = app.screen.query_one(RecoveryPanel)
        assert panel.region.right <= size[0]
        assert app.screen.query_one("#messages-panel").region.height >= 3
        assert app.screen.query_one("#recovery-grant", Button).display
        assert not app.screen.query_one("#recovery-resume", Button).display
        await pilot.click("#recovery-grant")
        await pilot.pause(.1)
        assert isinstance(app.screen, RecoveryDialog)
        assert app.screen.query_one("#recovery-dialog").region.right <= size[0]
        app.screen.query_one("#grant-worker_tool_calls", Input).value = "120"
        await pilot.click("#recovery-confirm")
        await pilot.pause(.2)
        assert view.calls == [{"issue_id": "pause-1", "action": "grant", "message": "", "grant": {"worker_tool_calls": 120}}]
        assert isinstance(app.screen, AgentScreen)
        app.save_screenshot(str(tmp_path / "recovery-layout.svg"))


@pytest.mark.asyncio
async def test_reply_requires_content_and_close_never_resumes():
    """A discussion or cancelled form cannot accidentally restart a task."""
    view = View("input")
    app = AttachApp(view)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(.2)
        await pilot.click("#recovery-reply")
        await pilot.pause(.1)
        await pilot.click("#recovery-confirm")
        assert view.calls == []
        assert app.screen.query_one("#recovery-error", Static).render()
        await pilot.press("escape")
        assert view.calls == [] and isinstance(app.screen, AgentScreen)
        await pilot.click("#recovery-reply")
        app.screen.query_one("#recovery-message", Input).value = "Use the revised inputs"
        await pilot.click("#recovery-confirm")
        await pilot.pause(.2)
        assert view.calls[0]["action"] == "reply"
